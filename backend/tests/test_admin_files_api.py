"""Phase 13 — admin reclassify endpoint."""

from __future__ import annotations

import io
import uuid
from unittest.mock import patch

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.classification import Classification, ClassificationStatus


def _upload(client, csrf_token, filename, content):
    return client.post(
        "/api/files",
        data={"file": (io.BytesIO(content), filename, "text/plain")},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )


def test_reclassify_creates_pending_row_and_enqueues(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = up.json["id"]

    with patch("app.tasks.classification.classify_file.delay") as mock_delay:
        resp = client.post(
            f"/api/admin/files/{file_id}/reclassify",
            headers={"X-CSRF-Token": csrf_token},
        )
    assert resp.status_code == 202
    mock_delay.assert_called_once_with(file_id)

    body = resp.json
    assert body["status"] == "pending"
    assert body["classification_version"] >= 2

    # Two Classification rows: the original PENDING from upload + the new reclassify
    rows = db_session.scalars(
        select(Classification).where(Classification.file_id == uuid.UUID(file_id))
    ).all()
    assert len(rows) >= 2
    assert any(r.version == 2 and r.status == ClassificationStatus.PENDING for r in rows)

    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "admin.file.reclassify_requested")
    ).all()
    assert len(audits) == 1


def test_reclassify_requires_admin(
    client, db_session, logged_in_user, csrf_token
) -> None:
    resp = client.post(
        f"/api/admin/files/{uuid.uuid4()}/reclassify",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert resp.status_code == 403


def test_reclassify_unknown_file_404(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    resp = client.post(
        f"/api/admin/files/{uuid.uuid4()}/reclassify",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert resp.status_code == 404
