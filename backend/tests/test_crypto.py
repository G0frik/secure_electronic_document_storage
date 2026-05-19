"""Tests for envelope encryption (services/crypto.py)."""

from __future__ import annotations

import base64
import secrets

import pytest

from app.config import settings
from app.services import crypto
from app.services.crypto import CryptoError


@pytest.fixture(autouse=True)
def _fresh_kek_cache():
    """Drop the cached KEK so monkeypatch'd settings take effect per test."""
    crypto.reset_kek_cache()
    yield
    crypto.reset_kek_cache()


@pytest.fixture
def explicit_kek(monkeypatch):
    """Set a known KEK via env-style config override."""
    raw = secrets.token_bytes(32)
    monkeypatch.setattr(settings, "kek_base64", base64.b64encode(raw).decode())
    return raw


# --- Roundtrip ---


def test_roundtrip_short(explicit_kek) -> None:
    pt = b"hello world"
    blob = crypto.encrypt_file(pt)
    out = crypto.decrypt_file(
        ciphertext=blob.ciphertext,
        wrapped_dek=blob.wrapped_dek,
        nonce=blob.nonce,
        auth_tag=blob.auth_tag,
        kek_version=blob.kek_version,
    )
    assert out == pt


def test_roundtrip_large(explicit_kek) -> None:
    pt = secrets.token_bytes(2 * 1024 * 1024)  # 2 MB
    blob = crypto.encrypt_file(pt)
    out = crypto.decrypt_file(
        ciphertext=blob.ciphertext,
        wrapped_dek=blob.wrapped_dek,
        nonce=blob.nonce,
        auth_tag=blob.auth_tag,
        kek_version=blob.kek_version,
    )
    assert out == pt


def test_ciphertext_differs_from_plaintext(explicit_kek) -> None:
    pt = b"a" * 4096
    blob = crypto.encrypt_file(pt)
    assert blob.ciphertext != pt
    assert len(blob.ciphertext) == len(pt)  # GCM is a stream cipher, tag stored separately


def test_each_call_uses_fresh_dek(explicit_kek) -> None:
    pt = b"same plaintext"
    b1 = crypto.encrypt_file(pt)
    b2 = crypto.encrypt_file(pt)
    assert b1.wrapped_dek != b2.wrapped_dek
    assert b1.ciphertext != b2.ciphertext  # different DEK + nonce → different ciphertext
    assert b1.nonce != b2.nonce


# --- Tampering ---


def test_tampered_ciphertext_rejected(explicit_kek) -> None:
    blob = crypto.encrypt_file(b"important data")
    tampered = bytearray(blob.ciphertext)
    tampered[0] ^= 0xFF
    with pytest.raises(CryptoError):
        crypto.decrypt_file(
            ciphertext=bytes(tampered),
            wrapped_dek=blob.wrapped_dek,
            nonce=blob.nonce,
            auth_tag=blob.auth_tag,
            kek_version=blob.kek_version,
        )


def test_tampered_auth_tag_rejected(explicit_kek) -> None:
    blob = crypto.encrypt_file(b"important data")
    tampered = bytearray(blob.auth_tag)
    tampered[0] ^= 0x01
    with pytest.raises(CryptoError):
        crypto.decrypt_file(
            ciphertext=blob.ciphertext,
            wrapped_dek=blob.wrapped_dek,
            nonce=blob.nonce,
            auth_tag=bytes(tampered),
            kek_version=blob.kek_version,
        )


def test_tampered_wrapped_dek_rejected(explicit_kek) -> None:
    blob = crypto.encrypt_file(b"important data")
    tampered = bytearray(blob.wrapped_dek)
    tampered[20] ^= 0xAA  # flip a byte inside the DEK ciphertext region
    with pytest.raises(CryptoError):
        crypto.decrypt_file(
            ciphertext=blob.ciphertext,
            wrapped_dek=bytes(tampered),
            nonce=blob.nonce,
            auth_tag=blob.auth_tag,
            kek_version=blob.kek_version,
        )


def test_wrong_nonce_rejected(explicit_kek) -> None:
    blob = crypto.encrypt_file(b"important data")
    with pytest.raises(CryptoError):
        crypto.decrypt_file(
            ciphertext=blob.ciphertext,
            wrapped_dek=blob.wrapped_dek,
            nonce=secrets.token_bytes(12),
            auth_tag=blob.auth_tag,
            kek_version=blob.kek_version,
        )


def test_kek_version_mismatch_rejected(explicit_kek, monkeypatch) -> None:
    blob = crypto.encrypt_file(b"x")
    monkeypatch.setattr(settings, "kek_version", blob.kek_version + 1)
    with pytest.raises(CryptoError, match="KEK version"):
        crypto.decrypt_file(
            ciphertext=blob.ciphertext,
            wrapped_dek=blob.wrapped_dek,
            nonce=blob.nonce,
            auth_tag=blob.auth_tag,
            kek_version=blob.kek_version,
        )


# --- KEK loading ---


def test_kek_loader_rejects_wrong_length(monkeypatch) -> None:
    monkeypatch.setattr(settings, "kek_base64", base64.b64encode(b"short").decode())
    crypto.reset_kek_cache()
    with pytest.raises(CryptoError, match="32 bytes"):
        crypto.load_kek()


def test_kek_loader_rejects_invalid_base64(monkeypatch) -> None:
    monkeypatch.setattr(settings, "kek_base64", "not!valid!base64!!!!")
    crypto.reset_kek_cache()
    with pytest.raises(CryptoError, match="base64"):
        crypto.load_kek()


def test_kek_loader_dev_fallback(monkeypatch) -> None:
    monkeypatch.setattr(settings, "kek_base64", "")
    monkeypatch.setattr(settings, "flask_env", "development")
    crypto.reset_kek_cache()
    kek = crypto.load_kek()
    assert len(kek) == 32


def test_kek_loader_requires_explicit_kek_in_prod(monkeypatch) -> None:
    monkeypatch.setattr(settings, "kek_base64", "")
    monkeypatch.setattr(settings, "flask_env", "production")
    crypto.reset_kek_cache()
    with pytest.raises(CryptoError, match="required in production"):
        crypto.load_kek()
