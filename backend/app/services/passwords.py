"""Password hashing and policy enforcement.

Algorithm: Argon2id (argon2-cffi default). Memory-hard, OWASP-recommended.
Policy: length-only (per NIST 800-63B), plus HaveIBeenPwned k-anonymity check.
"""

from __future__ import annotations

import hashlib

import requests
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import settings
from app.logging_config import get_logger

log = get_logger(__name__)

_HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/{prefix}"

_hasher = PasswordHasher()


class WeakPasswordError(ValueError):
    """Raised when a password fails policy (too short, breached, etc.)."""

    def __init__(self, reason: str, code: str) -> None:
        super().__init__(reason)
        self.code = code


def hash_password(plain: str) -> str:
    """Return an Argon2id hash for *plain*."""
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches *hashed*."""
    try:
        _hasher.verify(hashed, plain)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    """Return True if *hashed* uses outdated Argon2 parameters."""
    try:
        return _hasher.check_needs_rehash(hashed)
    except InvalidHashError:
        return True


def _is_pwned(plain: str) -> tuple[bool, int]:
    """Check HIBP k-anonymity API. Returns (is_pwned, count)."""
    sha1 = hashlib.sha1(plain.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]
    try:
        response = requests.get(
            _HIBP_RANGE_URL.format(prefix=prefix),
            headers={"User-Agent": settings.hibp_user_agent},
            timeout=settings.hibp_timeout_seconds,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        # Fail open: log but don't block registration on a transient HIBP outage.
        log.warning("hibp.check_failed", error=str(exc))
        return False, 0

    for line in response.text.splitlines():
        if ":" not in line:
            continue
        h, count = line.split(":", 1)
        if h.strip() == suffix:
            return True, int(count.strip())
    return False, 0


def validate_password_policy(plain: str) -> None:
    """Raise WeakPasswordError if *plain* fails policy."""
    if len(plain) < settings.password_min_length:
        raise WeakPasswordError(
            f"Password must be at least {settings.password_min_length} characters.",
            code="too_short",
        )
    if settings.hibp_enabled:
        pwned, count = _is_pwned(plain)
        if pwned:
            raise WeakPasswordError(
                f"This password has appeared in {count:,} known data breaches. Choose another.",
                code="breached",
            )
