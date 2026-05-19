"""MinIO storage adapter.

Bytes only — no domain logic. `services/files.py` orchestrates DB writes
and audit; this module just talks to MinIO.

In Phase 3 the ciphertext goes through here instead of plaintext, with the
same interface. The adapter doesn't know or care.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import IO

from minio import Minio
from minio.error import S3Error

from app.config import settings
from app.logging_config import get_logger

log = get_logger(__name__)

_client: Minio | None = None


def get_client() -> Minio:
    """Lazily construct a MinIO client (idempotent)."""
    global _client
    if _client is None:
        _client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
    return _client


def ensure_bucket() -> None:
    """Create the configured bucket if missing. Safe to call repeatedly."""
    client = get_client()
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)
        log.info("storage.bucket_created", bucket=settings.minio_bucket)


def put(key: str, stream: IO[bytes], length: int, content_type: str) -> None:
    """Upload *stream* of *length* bytes to MinIO under *key*."""
    get_client().put_object(
        settings.minio_bucket,
        key,
        stream,
        length=length,
        content_type=content_type,
    )


def get(key: str):  # type: ignore[no-untyped-def]
    """Open a streaming download for *key*. Caller MUST close/release.

    Returns the urllib3 HTTPResponse from MinIO. Use `.stream(chunk_size)`
    to iterate bytes, then `.close()` and `.release_conn()` in a finally.
    """
    return get_client().get_object(settings.minio_bucket, key)


def delete(key: str) -> None:
    """Remove an object. No-op if it doesn't exist."""
    try:
        get_client().remove_object(settings.minio_bucket, key)
    except S3Error as exc:
        if exc.code != "NoSuchKey":
            raise


def list_keys() -> Iterator[str]:
    """Yield every object key in the bucket. Intended for test cleanup."""
    client = get_client()
    if not client.bucket_exists(settings.minio_bucket):
        return
    for obj in client.list_objects(settings.minio_bucket, recursive=True):
        if obj.object_name:
            yield obj.object_name
