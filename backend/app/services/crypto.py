"""Envelope encryption for files at rest.

Phase 3 design:
- A per-file Data Encryption Key (DEK) of 32 random bytes is generated for
  every upload. The file body is encrypted with AES-256-GCM using that DEK.
- The DEK itself is then encrypted ("wrapped") with the Key Encryption Key
  (KEK), also via AES-256-GCM. The KEK is loaded from the env at startup.
- We persist `wrapped_dek`, `nonce`, `auth_tag`, and `kek_version` on the
  `files` row. The MinIO object holds only the file-body ciphertext.

The wrapped_dek blob is self-contained: it embeds its own nonce and tag in
the format `nonce_dek (12) || dek_ciphertext (32) || dek_tag (16)`.

Memory note: we encrypt/decrypt the whole file in memory. Acceptable at the
current 50 MB upload cap; true streaming AES-GCM is future work.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings
from app.logging_config import get_logger

log = get_logger(__name__)

_KEY_BYTES = 32  # AES-256
_GCM_NONCE_BYTES = 12
_GCM_TAG_BYTES = 16

_kek_cache: bytes | None = None


class CryptoError(Exception):
    """Raised on crypto failures (bad key, tampered ciphertext, malformed blob)."""


@dataclass(frozen=True)
class EncryptedBlob:
    """Output of `encrypt_file`. Caller persists everything except `ciphertext`,
    which goes to MinIO.
    """

    ciphertext: bytes
    wrapped_dek: bytes
    nonce: bytes
    auth_tag: bytes
    kek_version: int


def load_kek() -> bytes:
    """Return the KEK bytes (32B), caching after first call.

    Resolution order:
    1. `KEK` env var (base64 of 32 raw bytes)
    2. Dev-only fallback: SHA-256(SECRET_KEY) with a loud WARNING
    """
    global _kek_cache
    if _kek_cache is not None:
        return _kek_cache

    if settings.kek_base64:
        try:
            decoded = base64.b64decode(settings.kek_base64, validate=True)
        except (ValueError, TypeError) as exc:
            raise CryptoError(f"KEK env var is not valid base64: {exc}") from exc
        if len(decoded) != _KEY_BYTES:
            raise CryptoError(
                f"KEK must decode to {_KEY_BYTES} bytes, got {len(decoded)}."
            )
        _kek_cache = decoded
        return _kek_cache

    if not settings.is_development:
        raise CryptoError(
            "KEK env var is required in production. Generate with: "
            "python -c \"import os,base64; print(base64.b64encode(os.urandom(32)).decode())\""
        )

    log.warning(
        "kek.derived_from_secret_key",
        message=(
            "KEK env var unset; deriving from SECRET_KEY for dev. "
            "Set KEK explicitly for stable file-restore across SECRET_KEY changes."
        ),
    )
    _kek_cache = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return _kek_cache


def reset_kek_cache() -> None:
    """For tests: drop the cached KEK so the next call re-reads settings."""
    global _kek_cache
    _kek_cache = None


def _wrap_dek(dek: bytes, kek: bytes) -> bytes:
    """Encrypt the DEK with the KEK. Returns `nonce || ciphertext || tag` (60 B)."""
    nonce = os.urandom(_GCM_NONCE_BYTES)
    wrapped = AESGCM(kek).encrypt(nonce, dek, None)  # ct || tag (32 + 16 = 48 B)
    return nonce + wrapped


def _unwrap_dek(wrapped_dek_blob: bytes, kek: bytes) -> bytes:
    """Decrypt a wrapped-DEK blob produced by `_wrap_dek`."""
    if len(wrapped_dek_blob) < _GCM_NONCE_BYTES + _KEY_BYTES + _GCM_TAG_BYTES:
        raise CryptoError("Wrapped DEK blob is shorter than expected.")
    nonce = wrapped_dek_blob[:_GCM_NONCE_BYTES]
    wrapped = wrapped_dek_blob[_GCM_NONCE_BYTES:]
    try:
        return AESGCM(kek).decrypt(nonce, wrapped, None)
    except InvalidTag as exc:
        raise CryptoError("Wrapped DEK failed authentication (tampered or wrong KEK).") from exc


def encrypt_file(plaintext: bytes) -> EncryptedBlob:
    """Encrypt *plaintext* under a fresh DEK; wrap the DEK with the KEK."""
    kek = load_kek()
    dek = secrets.token_bytes(_KEY_BYTES)
    nonce = os.urandom(_GCM_NONCE_BYTES)

    ct_with_tag = AESGCM(dek).encrypt(nonce, plaintext, None)
    ciphertext = ct_with_tag[:-_GCM_TAG_BYTES]
    auth_tag = ct_with_tag[-_GCM_TAG_BYTES:]

    wrapped_dek = _wrap_dek(dek, kek)

    return EncryptedBlob(
        ciphertext=ciphertext,
        wrapped_dek=wrapped_dek,
        nonce=nonce,
        auth_tag=auth_tag,
        kek_version=settings.kek_version,
    )


# --- Small-blob helpers (Phase 6: TOTP secrets, future: any small at-rest
#     secret that doesn't justify a per-record DEK). Encrypts the blob
#     directly with the KEK — fine for small payloads because GCM nonce
#     uniqueness is preserved by `os.urandom(12)` per call, and the data
#     volume per key stays well below the AES-GCM ~2^32 invocations limit. ---


@dataclass(frozen=True)
class EncryptedSecret:
    """KEK-wrapped small payload. Persisted on the relevant row."""

    ciphertext: bytes
    nonce: bytes
    auth_tag: bytes
    kek_version: int


def encrypt_secret(plaintext: bytes) -> EncryptedSecret:
    """Encrypt a small blob (≤ a few KB) under the KEK directly."""
    kek = load_kek()
    nonce = os.urandom(_GCM_NONCE_BYTES)
    ct_with_tag = AESGCM(kek).encrypt(nonce, plaintext, None)
    ciphertext = ct_with_tag[:-_GCM_TAG_BYTES]
    auth_tag = ct_with_tag[-_GCM_TAG_BYTES:]
    return EncryptedSecret(
        ciphertext=ciphertext,
        nonce=nonce,
        auth_tag=auth_tag,
        kek_version=settings.kek_version,
    )


def decrypt_secret(
    *, ciphertext: bytes, nonce: bytes, auth_tag: bytes, kek_version: int
) -> bytes:
    """Inverse of `encrypt_secret`. Raises CryptoError on tampering."""
    if kek_version != settings.kek_version:
        raise CryptoError(
            f"Secret was wrapped under KEK version {kek_version}; "
            f"current version is {settings.kek_version}."
        )
    if len(nonce) != _GCM_NONCE_BYTES:
        raise CryptoError(f"Secret nonce must be {_GCM_NONCE_BYTES} bytes.")
    if len(auth_tag) != _GCM_TAG_BYTES:
        raise CryptoError(f"Secret auth tag must be {_GCM_TAG_BYTES} bytes.")
    kek = load_kek()
    try:
        return AESGCM(kek).decrypt(nonce, ciphertext + auth_tag, None)
    except InvalidTag as exc:
        raise CryptoError("Secret ciphertext failed authentication (tampered).") from exc


def decrypt_file(
    *,
    ciphertext: bytes,
    wrapped_dek: bytes,
    nonce: bytes,
    auth_tag: bytes,
    kek_version: int,
) -> bytes:
    """Inverse of `encrypt_file`. Raises CryptoError on tampering."""
    if kek_version != settings.kek_version:
        raise CryptoError(
            f"File was wrapped under KEK version {kek_version}; "
            f"current version is {settings.kek_version}. Re-wrap before decrypting."
        )
    if len(nonce) != _GCM_NONCE_BYTES:
        raise CryptoError(f"File nonce must be {_GCM_NONCE_BYTES} bytes.")
    if len(auth_tag) != _GCM_TAG_BYTES:
        raise CryptoError(f"File auth tag must be {_GCM_TAG_BYTES} bytes.")

    kek = load_kek()
    dek = _unwrap_dek(wrapped_dek, kek)

    try:
        return AESGCM(dek).decrypt(nonce, ciphertext + auth_tag, None)
    except InvalidTag as exc:
        raise CryptoError("File ciphertext failed authentication (tampered).") from exc
