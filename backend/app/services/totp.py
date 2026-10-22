"""TOTP service — enrollment, verification, recovery codes.

Phase 6 — RFC 6238 time-based one-time passwords, plus 10 single-use
Argon2-hashed recovery codes per user. Secrets are KEK-wrapped at rest
(see `services/crypto.py::encrypt_secret`).

Lifecycle:
    setup_for_user(user)
        ─ generates new base32 secret + 10 recovery codes
        ─ replaces any existing row, marks DISABLED
        ─ returns plaintext otpauth URI + plaintext recovery codes
          (the only time the user sees them)

    enable_for_user(user, code)
        ─ verifies the first code, flips enabled=True

    disable_for_user(user, code)
        ─ verifies, deletes the row

    verify_for_login(user, code)
        ─ tries the TOTP code first, then each unused recovery code
        ─ on recovery match: marks the code used_at = now
        ─ updates last_used_at on success
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

import pyotp
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.extensions import db
from app.logging_config import get_logger
from app.models.user import User
from app.models.user_totp import UserTotp
from app.services import crypto, passwords

log = get_logger(__name__)

# RFC 6238 / Google Authenticator defaults: SHA1, 6 digits, 30 s period.
_TOTP_DIGITS = 6
_TOTP_PERIOD = 30
# ± 1 step grace window to forgive minor clock drift.
_TOTP_VALID_WINDOW = 1
_RECOVERY_CODE_COUNT = 10
_RECOVERY_CODE_BYTES = 6  # → 12 hex chars, presented as XXXX-XXXX-XXXX
_ISSUER_NAME = "Secure DocStore"


class TotpError(Exception):
    """Raised on TOTP setup/verify failures."""


@dataclass(frozen=True)
class SetupBundle:
    """Returned by `setup_for_user` — the only moment the user sees plaintext."""

    otpauth_uri: str
    secret_b32: str
    recovery_codes: list[str]


# --- Secret + recovery helpers ---


def _generate_secret_b32() -> str:
    """20 random bytes → 32 base32 chars (matches pyotp.random_base32 default)."""
    return pyotp.random_base32()


def _generate_recovery_codes() -> list[str]:
    """10 codes in `XXXX-XXXX-XXXX` form (12 hex chars). Single-use, shown once."""
    codes: list[str] = []
    for _ in range(_RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(_RECOVERY_CODE_BYTES).upper()
        codes.append(f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}")
    return codes


def _hash_codes(codes: list[str]) -> list[dict]:
    """Argon2-hash each code; persist alongside a `used_at` marker."""
    return [{"hash": passwords.hash_password(c), "used_at": None} for c in codes]


def _provisioning_uri(user: User, secret_b32: str) -> str:
    return pyotp.totp.TOTP(
        secret_b32, digits=_TOTP_DIGITS, interval=_TOTP_PERIOD
    ).provisioning_uri(name=user.email, issuer_name=_ISSUER_NAME)


def _decrypt_secret(row: UserTotp) -> str:
    plaintext = crypto.decrypt_secret(
        ciphertext=row.secret_ciphertext,
        nonce=row.secret_nonce,
        auth_tag=row.secret_tag,
        kek_version=row.kek_version,
    )
    return plaintext.decode("ascii")


def _verify_totp_code(secret_b32: str, code: str) -> bool:
    if not code or not code.strip().isdigit():
        return False
    totp = pyotp.TOTP(secret_b32, digits=_TOTP_DIGITS, interval=_TOTP_PERIOD)
    return totp.verify(code.strip(), valid_window=_TOTP_VALID_WINDOW)


# --- Public API ---


def get_for_user(user: User) -> UserTotp | None:
    return db.session.scalar(select(UserTotp).where(UserTotp.user_id == user.id))


def is_enabled(user: User) -> bool:
    row = get_for_user(user)
    return bool(row and row.enabled)


def setup_for_user(user: User) -> SetupBundle:
    """Start enrollment. Replaces any prior un-verified row. If a row was
    already enabled, the caller must `disable_for_user` first — we don't
    silently rotate active 2FA.
    """
    existing = get_for_user(user)
    if existing is not None and existing.enabled:
        raise TotpError("2FA is already enabled. Disable it first to re-enrol.")

    secret = _generate_secret_b32()
    encrypted = crypto.encrypt_secret(secret.encode("ascii"))
    recovery_plain = _generate_recovery_codes()
    recovery_hashed = _hash_codes(recovery_plain)

    if existing is not None:
        existing.secret_ciphertext = encrypted.ciphertext
        existing.secret_nonce = encrypted.nonce
        existing.secret_tag = encrypted.auth_tag
        existing.kek_version = encrypted.kek_version
        existing.enabled = False
        existing.enabled_at = None
        existing.last_used_at = None
        existing.recovery_codes = recovery_hashed
        row = existing
    else:
        row = UserTotp(
            user_id=user.id,
            secret_ciphertext=encrypted.ciphertext,
            secret_nonce=encrypted.nonce,
            secret_tag=encrypted.auth_tag,
            kek_version=encrypted.kek_version,
            enabled=False,
            recovery_codes=recovery_hashed,
        )
        db.session.add(row)
    db.session.commit()

    return SetupBundle(
        otpauth_uri=_provisioning_uri(user, secret),
        secret_b32=secret,
        recovery_codes=recovery_plain,
    )


def enable_for_user(user: User, code: str) -> None:
    """Confirm the first code from the authenticator app and flip enabled=True."""
    row = get_for_user(user)
    if row is None:
        raise TotpError("No pending TOTP enrolment. Run setup first.")
    if row.enabled:
        raise TotpError("2FA is already enabled.")

    secret = _decrypt_secret(row)
    if not _verify_totp_code(secret, code):
        raise TotpError("Invalid TOTP code.")

    row.enabled = True
    row.enabled_at = datetime.now(UTC)
    row.last_used_at = row.enabled_at
    db.session.commit()


def disable_for_user(user: User, code: str) -> None:
    """Tear down 2FA. Requires a fresh TOTP code (or recovery code) to prove
    the holder is still the user.
    """
    row = get_for_user(user)
    if row is None or not row.enabled:
        raise TotpError("2FA is not enabled.")

    if not _verify_or_consume_recovery(row, code):
        raise TotpError("Invalid TOTP or recovery code.")

    db.session.delete(row)
    db.session.commit()


def verify_for_login(user: User, code: str) -> bool:
    """Used during the 2-step login flow. Tries TOTP first, then recovery
    codes. Returns True on first match; persists `used_at` for recovery
    codes so each one is single-use. Returns False on miss.
    """
    row = get_for_user(user)
    if row is None or not row.enabled:
        return False
    matched = _verify_or_consume_recovery(row, code)
    if matched:
        row.last_used_at = datetime.now(UTC)
        db.session.commit()
    return matched


# --- Internals shared by disable + login verification ---


def _verify_or_consume_recovery(row: UserTotp, code: str) -> bool:
    """Verify *code* against the TOTP secret first, then unused recovery
    hashes. On a recovery hit, mark the entry used_at=now (caller commits).
    """
    secret = _decrypt_secret(row)
    if _verify_totp_code(secret, code):
        return True

    normalised = code.strip().upper().replace(" ", "")
    codes = list(row.recovery_codes or [])
    changed = False
    for entry in codes:
        if entry.get("used_at"):
            continue
        if passwords.verify_password(normalised, entry["hash"]):
            entry["used_at"] = datetime.now(UTC).isoformat()
            changed = True
            break
    if not changed:
        return False
    # JSONB mutation in-place isn't picked up by SQLAlchemy by default. We
    # reassign AND explicitly flag the attribute dirty so the commit at the
    # call-site actually writes the updated `used_at` markers back.
    row.recovery_codes = codes
    flag_modified(row, "recovery_codes")
    return True


# --- Helper used by audit-friendly reporting ---


def remaining_recovery_codes(row: UserTotp) -> int:
    return sum(1 for c in (row.recovery_codes or []) if not c.get("used_at"))
