"""Phase 6 — TOTP service unit tests.

Covers: secret round-trip, code verification (drift window), recovery codes
single-use, enable/disable lifecycle, idempotent re-setup of an un-verified row.
"""

from __future__ import annotations

import pyotp
import pytest
from sqlalchemy import select

from app.models.user_totp import UserTotp
from app.services import totp
from app.services.totp import TotpError


def _read_secret(db_session, user) -> str:
    """Pull the encrypted secret back off the row and decode it."""
    row = db_session.scalar(select(UserTotp).where(UserTotp.user_id == user.id))
    assert row is not None
    return totp._decrypt_secret(row)  # type: ignore[attr-defined]


def test_setup_creates_row_disabled(db_session, seeded_user) -> None:
    bundle = totp.setup_for_user(seeded_user)
    assert bundle.secret_b32
    assert bundle.otpauth_uri.startswith("otpauth://totp/")
    assert seeded_user.email in bundle.otpauth_uri or seeded_user.email.replace("@", "%40") in bundle.otpauth_uri
    assert len(bundle.recovery_codes) == 10

    row = totp.get_for_user(seeded_user)
    assert row is not None
    assert row.enabled is False
    assert row.enabled_at is None
    assert len(row.recovery_codes) == 10


def test_setup_secret_round_trips_through_kek(db_session, seeded_user) -> None:
    bundle = totp.setup_for_user(seeded_user)
    decrypted = _read_secret(db_session, seeded_user)
    assert decrypted == bundle.secret_b32


def test_enable_with_valid_code(db_session, seeded_user) -> None:
    bundle = totp.setup_for_user(seeded_user)
    code = pyotp.TOTP(bundle.secret_b32).now()
    totp.enable_for_user(seeded_user, code)

    row = totp.get_for_user(seeded_user)
    assert row is not None
    assert row.enabled
    assert row.enabled_at is not None


def test_enable_rejects_wrong_code(db_session, seeded_user) -> None:
    totp.setup_for_user(seeded_user)
    with pytest.raises(TotpError):
        totp.enable_for_user(seeded_user, "000000")
    row = totp.get_for_user(seeded_user)
    assert row is not None
    assert not row.enabled


def test_setup_blocks_when_already_enabled(db_session, seeded_user) -> None:
    bundle = totp.setup_for_user(seeded_user)
    totp.enable_for_user(seeded_user, pyotp.TOTP(bundle.secret_b32).now())
    with pytest.raises(TotpError):
        totp.setup_for_user(seeded_user)


def test_setup_replaces_unverified_row(db_session, seeded_user) -> None:
    """Calling setup again on a never-verified enrolment rotates the secret."""
    first = totp.setup_for_user(seeded_user)
    second = totp.setup_for_user(seeded_user)
    assert first.secret_b32 != second.secret_b32
    # Only one row exists
    rows = db_session.scalars(select(UserTotp).where(UserTotp.user_id == seeded_user.id)).all()
    assert len(rows) == 1


def test_disable_requires_valid_code(db_session, seeded_user) -> None:
    bundle = totp.setup_for_user(seeded_user)
    totp.enable_for_user(seeded_user, pyotp.TOTP(bundle.secret_b32).now())

    with pytest.raises(TotpError):
        totp.disable_for_user(seeded_user, "000000")
    assert totp.is_enabled(seeded_user)

    totp.disable_for_user(seeded_user, pyotp.TOTP(bundle.secret_b32).now())
    assert not totp.is_enabled(seeded_user)
    assert totp.get_for_user(seeded_user) is None


def test_disable_when_not_enabled_raises(db_session, seeded_user) -> None:
    with pytest.raises(TotpError):
        totp.disable_for_user(seeded_user, "000000")


def test_verify_for_login_with_totp_code(db_session, seeded_user) -> None:
    bundle = totp.setup_for_user(seeded_user)
    totp.enable_for_user(seeded_user, pyotp.TOTP(bundle.secret_b32).now())

    assert totp.verify_for_login(seeded_user, pyotp.TOTP(bundle.secret_b32).now()) is True


def test_verify_for_login_with_recovery_code_single_use(db_session, seeded_user) -> None:
    bundle = totp.setup_for_user(seeded_user)
    totp.enable_for_user(seeded_user, pyotp.TOTP(bundle.secret_b32).now())

    code = bundle.recovery_codes[0]
    assert totp.verify_for_login(seeded_user, code) is True
    # Same code rejected next time
    assert totp.verify_for_login(seeded_user, code) is False

    # Another untouched code still works
    second = bundle.recovery_codes[1]
    assert totp.verify_for_login(seeded_user, second) is True


def test_recovery_code_lowercase_and_spaced(db_session, seeded_user) -> None:
    """Users tend to mistype recovery codes — we normalise case + spaces."""
    bundle = totp.setup_for_user(seeded_user)
    totp.enable_for_user(seeded_user, pyotp.TOTP(bundle.secret_b32).now())

    raw = bundle.recovery_codes[0]
    munged = f"  {raw.lower()}  "
    assert totp.verify_for_login(seeded_user, munged) is True


def test_verify_for_login_fails_when_disabled(db_session, seeded_user) -> None:
    # No enrolment at all
    assert totp.verify_for_login(seeded_user, "000000") is False
    # Setup-but-not-enabled also fails
    bundle = totp.setup_for_user(seeded_user)
    assert totp.verify_for_login(seeded_user, pyotp.TOTP(bundle.secret_b32).now()) is False


def test_remaining_recovery_codes(db_session, seeded_user) -> None:
    bundle = totp.setup_for_user(seeded_user)
    totp.enable_for_user(seeded_user, pyotp.TOTP(bundle.secret_b32).now())
    row = totp.get_for_user(seeded_user)
    assert totp.remaining_recovery_codes(row) == 10
    totp.verify_for_login(seeded_user, bundle.recovery_codes[0])
    db_session.refresh(row)
    assert totp.remaining_recovery_codes(row) == 9
