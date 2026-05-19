"""Tests for password hashing + policy."""

from __future__ import annotations

import hashlib

import pytest
import responses

from app.config import settings
from app.services import passwords
from app.services.passwords import WeakPasswordError


def test_hash_and_verify_roundtrip() -> None:
    hashed = passwords.hash_password("CorrectHorseBatteryStaple")  # noqa: S106
    assert passwords.verify_password("CorrectHorseBatteryStaple", hashed) is True
    assert passwords.verify_password("wrong", hashed) is False


def test_hash_produces_argon2id() -> None:
    hashed = passwords.hash_password("SomePassword123!")  # noqa: S106
    assert hashed.startswith("$argon2id$")


def test_policy_rejects_short_password() -> None:
    with pytest.raises(WeakPasswordError) as exc_info:
        passwords.validate_password_policy("short")
    assert exc_info.value.code == "too_short"


def _hibp_response_for(password: str, count: int = 5) -> tuple[str, str]:
    sha1 = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]
    body = f"{suffix}:{count}\nABCDE12345:99\n"
    return prefix, body


@responses.activate
def test_policy_rejects_breached_password(monkeypatch) -> None:
    monkeypatch.setattr(settings, "hibp_enabled", True)
    password = "this-is-a-long-but-breached-password"
    prefix, body = _hibp_response_for(password, count=1234)
    responses.add(
        responses.GET,
        f"https://api.pwnedpasswords.com/range/{prefix}",
        body=body,
        status=200,
    )
    with pytest.raises(WeakPasswordError) as exc_info:
        passwords.validate_password_policy(password)
    assert exc_info.value.code == "breached"


@responses.activate
def test_policy_allows_unseen_password(monkeypatch) -> None:
    monkeypatch.setattr(settings, "hibp_enabled", True)
    password = "totally-novel-password-string-9921"
    prefix, _ = _hibp_response_for(password)
    # Return a range that does NOT include our password's suffix.
    responses.add(
        responses.GET,
        f"https://api.pwnedpasswords.com/range/{prefix}",
        body="0000000000000000000000000000000000000:1\n",
        status=200,
    )
    # Should not raise.
    passwords.validate_password_policy(password)


def test_policy_with_hibp_disabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "hibp_enabled", False)
    # Long enough; HIBP skipped → must not raise.
    passwords.validate_password_policy("LongEnoughPassword!1")
