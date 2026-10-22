"""Phase 8 — external share-link API.

Covers:
  - Create link (success, tier block, classification pending)
  - List granted links
  - Revoke (granter or admin only)
  - Public landing endpoint: valid, not-found, revoked, expired, exhausted
  - Public download endpoint: bytes round-trip, use_count increments, max_uses=1 enforced
  - Token stored as SHA-256 (no plaintext on disk)
  - Audit events written for each lifecycle stage
"""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.classification import (
    Classification,
    ClassificationStatus,
    ClassificationTier,
)
from app.models.share_link import ShareLink


def _upload(client, csrf_token, filename, content, content_type="text/plain"):
    return client.post(
        "/api/files",
        data={"file": (io.BytesIO(content), filename, content_type)},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )


def _classify(
    db_session, file_id, tier=ClassificationTier.PUBLIC, categories=None
):
    """Mark a file as classified. The upload flow inserts a PENDING row;
    we either update that in place or insert a fresh row when none exists.
    """
    from sqlalchemy import select as sa_select

    existing = db_session.scalar(
        sa_select(Classification).where(Classification.file_id == file_id)
    )
    if existing is None:
        existing = Classification(file_id=file_id, version=1)
        db_session.add(existing)
    existing.status = ClassificationStatus.COMPLETED
    existing.final_tier = tier
    existing.zero_shot_tier = tier
    existing.presidio_tier = ClassificationTier.PUBLIC
    existing.categories_triggered = categories or []
    existing.classifier_version = "v6"
    existing.classified_at = datetime.now(UTC)
    db_session.commit()
    return existing


# --- Create ---


def test_create_link_for_owned_file(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    body = b"the quick brown fox"
    up = _upload(client, csrf_token, "fox.txt", body)
    file_id = up.json["id"]
    _classify(db_session, uuid.UUID(file_id), ClassificationTier.PUBLIC)

    resp = client.post(
        "/api/share-links",
        json={"file_id": file_id, "max_uses": 5},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert resp.status_code == 201, resp.data
    body_json = resp.json
    assert body_json["token"]  # shown once
    assert body_json["use_count"] == 0
    assert body_json["max_uses"] == 5

    # Token is hashed at rest — the raw value MUST NOT appear in the DB row.
    row = db_session.scalar(select(ShareLink).where(ShareLink.id == uuid.UUID(body_json["id"])))
    assert row is not None
    assert row.token_hash != body_json["token"]
    expected_hash = hashlib.sha256(body_json["token"].encode("ascii")).hexdigest()
    assert row.token_hash == expected_hash

    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "share_link.created")
    ).all()
    assert len(audits) == 1


def test_create_link_blocked_for_restricted_by_default(
    client, db_session, logged_in_user, csrf_token
) -> None:
    """Non-admin user can't mint a link for a RESTRICTED file."""
    up = _upload(client, csrf_token, "secret.txt", b"the secret")
    file_id = uuid.UUID(up.json["id"])
    _classify(
        db_session,
        file_id,
        ClassificationTier.RESTRICTED,
        categories=["personally identifiable information"],
    )

    resp = client.post(
        "/api/share-links",
        json={"file_id": str(file_id)},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert resp.status_code == 403
    assert resp.json["error"] == "tier_blocked"


def test_admin_can_force_restricted_link(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    """Admin with force_for_restricted=true gets a link AND a warning audit row."""
    up = _upload(client, csrf_token, "secret.txt", b"the secret")
    file_id = uuid.UUID(up.json["id"])
    _classify(
        db_session,
        file_id,
        ClassificationTier.RESTRICTED,
        categories=["personally identifiable information"],
    )

    resp = client.post(
        "/api/share-links",
        json={"file_id": str(file_id), "force_for_restricted": True},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert resp.status_code == 201

    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "share_link.created")
    ).all()
    assert len(audits) == 1
    assert audits[0].severity.value == "warning"
    assert audits[0].event_metadata["tier_override"] is True


def test_create_link_for_unclassified_is_409(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    resp = client.post(
        "/api/share-links",
        json={"file_id": up.json["id"]},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert resp.status_code == 409
    assert resp.json["error"] == "classification_pending"


def test_cannot_create_link_for_other_users_file(
    client, db_session, logged_in_user, seeded_admin, csrf_token
) -> None:
    """Regular user can't mint a link for somebody else's file."""
    from app.models.file import File

    other_file = File(
        owner_id=seeded_admin.id,
        original_filename="theirs.txt",
        storage_key=uuid.uuid4(),
        mime_type="text/plain",
        size_bytes=1,
        sha256="0" * 64,
        wrapped_dek=b"\x00" * 60,
        nonce=b"\x00" * 12,
        auth_tag=b"\x00" * 16,
        kek_version=1,
    )
    db_session.add(other_file)
    db_session.commit()
    _classify(db_session, other_file.id, ClassificationTier.PUBLIC)

    resp = client.post(
        "/api/share-links",
        json={"file_id": str(other_file.id)},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400


# --- List + revoke ---


def test_list_granted_returns_users_links(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    _classify(db_session, uuid.UUID(up.json["id"]), ClassificationTier.PUBLIC)
    client.post(
        "/api/share-links",
        json={"file_id": up.json["id"]},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    resp = client.get("/api/share-links/granted")
    assert resp.status_code == 200
    assert len(resp.json["items"]) == 1
    # Tokens are NOT re-served on the listing endpoint
    assert resp.json["items"][0]["token"] is None


def test_revoke_link(client, db_session, logged_in_admin, csrf_token) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    _classify(db_session, uuid.UUID(up.json["id"]), ClassificationTier.PUBLIC)
    created = client.post(
        "/api/share-links",
        json={"file_id": up.json["id"]},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    ).json
    resp = client.delete(
        f"/api/share-links/{created['id']}", headers={"X-CSRF-Token": csrf_token}
    )
    assert resp.status_code == 204

    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "share_link.revoked")
    ).all()
    assert len(audits) == 1


def test_revoke_by_other_user_is_403(
    client, db_session, logged_in_user, seeded_admin, csrf_token
) -> None:
    """A link minted by admin can't be revoked by a regular user."""
    from app.models.file import File

    f = File(
        owner_id=seeded_admin.id,
        original_filename="x.txt",
        storage_key=uuid.uuid4(),
        mime_type="text/plain",
        size_bytes=1,
        sha256="0" * 64,
        wrapped_dek=b"\x00" * 60,
        nonce=b"\x00" * 12,
        auth_tag=b"\x00" * 16,
        kek_version=1,
    )
    db_session.add(f)
    db_session.commit()
    _classify(db_session, f.id, ClassificationTier.PUBLIC)
    link = ShareLink(
        file_id=f.id,
        token_hash="x" * 64,
        created_by_id=seeded_admin.id,
    )
    db_session.add(link)
    db_session.commit()

    resp = client.delete(f"/api/share-links/{link.id}", headers={"X-CSRF-Token": csrf_token})
    assert resp.status_code == 403


# --- Public landing + download ---


def test_public_landing_returns_metadata(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    body = b"hello world from external link"
    up = _upload(client, csrf_token, "x.txt", body)
    _classify(db_session, uuid.UUID(up.json["id"]), ClassificationTier.PUBLIC)
    minted = client.post(
        "/api/share-links",
        json={"file_id": up.json["id"], "max_uses": 3},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    ).json

    # Public — no session needed
    client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    resp = client.get(f"/api/public/share-links/{minted['token']}")
    assert resp.status_code == 200
    body_json = resp.json
    assert body_json["filename"] == "x.txt"
    assert body_json["size_bytes"] == len(body)
    assert body_json["max_uses"] == 3
    assert body_json["use_count"] == 0
    assert body_json["remaining_uses"] == 3

    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "share_link.viewed")
    ).all()
    assert len(audits) == 1


def test_public_download_returns_bytes_and_increments(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    body = b"the original bytes that came back through the link"
    up = _upload(client, csrf_token, "x.bin", body, "application/octet-stream")
    _classify(db_session, uuid.UUID(up.json["id"]), ClassificationTier.PUBLIC)
    minted = client.post(
        "/api/share-links",
        json={"file_id": up.json["id"], "max_uses": 2},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    ).json

    client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    resp = client.get(f"/api/public/share-links/{minted['token']}/download")
    assert resp.status_code == 200
    assert resp.data == body

    # Use-count incremented to 1; one more download still allowed
    row = db_session.scalar(select(ShareLink).where(ShareLink.id == uuid.UUID(minted["id"])))
    db_session.refresh(row)
    assert row.use_count == 1

    resp2 = client.get(f"/api/public/share-links/{minted['token']}/download")
    assert resp2.status_code == 200
    db_session.refresh(row)
    assert row.use_count == 2

    # Third hit → exhausted → 410
    resp3 = client.get(f"/api/public/share-links/{minted['token']}/download")
    assert resp3.status_code == 410
    assert resp3.json["reason"] == "exhausted"


def test_public_unknown_token_is_404(client) -> None:
    resp = client.get("/api/public/share-links/totally-fake-token-with-some-length")
    assert resp.status_code == 404


def test_public_revoked_link_is_410(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    _classify(db_session, uuid.UUID(up.json["id"]), ClassificationTier.PUBLIC)
    minted = client.post(
        "/api/share-links",
        json={"file_id": up.json["id"]},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    ).json
    client.delete(
        f"/api/share-links/{minted['id']}", headers={"X-CSRF-Token": csrf_token}
    )

    client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    resp = client.get(f"/api/public/share-links/{minted['token']}")
    assert resp.status_code == 410
    assert resp.json["reason"] == "revoked"


def test_public_expired_link_is_410(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    _classify(db_session, uuid.UUID(up.json["id"]), ClassificationTier.PUBLIC)
    # Mint with a tomorrow expiry, then poke the DB to back-date it.
    minted = client.post(
        "/api/share-links",
        json={
            "file_id": up.json["id"],
            "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    ).json
    row = db_session.scalar(select(ShareLink).where(ShareLink.id == uuid.UUID(minted["id"])))
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    resp = client.get(f"/api/public/share-links/{minted['token']}")
    assert resp.status_code == 410
    assert resp.json["reason"] == "expired"


def test_create_with_past_expiry_is_400(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    _classify(db_session, uuid.UUID(up.json["id"]), ClassificationTier.PUBLIC)
    resp = client.post(
        "/api/share-links",
        json={
            "file_id": up.json["id"],
            "expires_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
        },
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
