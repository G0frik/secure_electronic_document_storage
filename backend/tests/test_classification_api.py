"""Tests for the classification service + /api/files/<id>/classification endpoint.

The heavy ML model is mocked everywhere — these tests check the wiring
(DB rows, status transitions, audit events, payload shape), not the
classifier behaviour itself.
"""

from __future__ import annotations

import io
import uuid
from unittest.mock import patch

from sqlalchemy import select

from app.classifier_core import ClassifyResult
from app.classifier_core.tiers import Tier
from app.models.audit import AuditLog
from app.models.classification import Classification, ClassificationStatus, ClassificationTier
from app.services import classification as classification_service


def _fake_classify(text: str) -> ClassifyResult:
    return ClassifyResult(
        final_tier=Tier.CONFIDENTIAL,
        zero_shot_tier=Tier.CONFIDENTIAL,
        presidio_tier=Tier.PUBLIC,
        raw_scores={"salary": 0.92, "marketing": 0.05},
        categories_triggered=["salary, compensation, or employee financial records"],
        presidio_entities={},
    )


def _upload(client, csrf_token, filename, content, content_type="text/plain"):
    return client.post(
        "/api/files",
        data={"file": (io.BytesIO(content), filename, content_type)},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )


# --- Upload integration: pending row gets created ---


def test_upload_creates_pending_classification_row(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    # Patch `delay` so the Celery task isn't actually enqueued in tests.
    with patch("app.tasks.classification.classify_file.delay") as mock_delay:
        response = _upload(client, csrf_token, "doc.txt", b"hello world")
        assert response.status_code == 201
        mock_delay.assert_called_once()

    rows = db_session.scalars(select(Classification)).all()
    assert len(rows) == 1
    assert rows[0].status == ClassificationStatus.PENDING
    assert rows[0].final_tier is None
    assert rows[0].version == 1


# --- Service: run_classification end-to-end with a fake classifier ---


def test_run_classification_completes_with_mock(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    with patch("app.tasks.classification.classify_file.delay"):
        response = _upload(client, csrf_token, "salary.txt", b"Salary report: alice $90k bob $110k")
    file_id = uuid.UUID(response.json["id"])

    record = classification_service.run_classification(file_id, classifier_fn=_fake_classify)

    assert record.status == ClassificationStatus.COMPLETED
    assert record.final_tier == ClassificationTier.CONFIDENTIAL
    assert record.zero_shot_tier == ClassificationTier.CONFIDENTIAL
    assert record.presidio_tier == ClassificationTier.PUBLIC
    assert "salary, compensation, or employee financial records" in record.categories_triggered
    assert record.raw_scores["salary"] == 0.92
    assert record.classifier_version == "v6"
    assert record.classified_at is not None

    audit_rows = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "classification.completed")
    ).all()
    assert len(audit_rows) == 1


def test_run_classification_marks_failed_on_extraction_error(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    # An empty payload (after extraction) trips the "no text" guard.
    with patch("app.tasks.classification.classify_file.delay"):
        response = _upload(client, csrf_token, "blank.txt", b"   \n\t  ")
    file_id = uuid.UUID(response.json["id"])

    record = classification_service.run_classification(file_id, classifier_fn=_fake_classify)
    assert record.status == ClassificationStatus.FAILED
    assert record.error_message
    failures = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "classification.failed")
    ).all()
    assert len(failures) == 1


def test_run_classification_handles_classifier_exception(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    with patch("app.tasks.classification.classify_file.delay"):
        response = _upload(client, csrf_token, "doc.txt", b"some content here")
    file_id = uuid.UUID(response.json["id"])

    def boom(_text):
        raise RuntimeError("model exploded")

    record = classification_service.run_classification(file_id, classifier_fn=boom)
    assert record.status == ClassificationStatus.FAILED
    assert "model exploded" in (record.error_message or "")


# --- API endpoint ---


def test_classification_endpoint_returns_pending_immediately(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    with patch("app.tasks.classification.classify_file.delay"):
        response = _upload(client, csrf_token, "doc.txt", b"hello")
    file_id = response.json["id"]
    poll = client.get(f"/api/files/{file_id}/classification")
    assert poll.status_code == 200
    assert poll.json["status"] == "pending"
    assert poll.json["final_tier"] is None


def test_classification_endpoint_returns_completed_result(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    with patch("app.tasks.classification.classify_file.delay"):
        response = _upload(client, csrf_token, "doc.txt", b"hello salary world")
    file_id = response.json["id"]
    classification_service.run_classification(uuid.UUID(file_id), classifier_fn=_fake_classify)

    poll = client.get(f"/api/files/{file_id}/classification")
    assert poll.status_code == 200
    assert poll.json["status"] == "completed"
    assert poll.json["final_tier"] == "confidential"
    assert poll.json["categories_triggered"]


def test_classification_endpoint_404_for_other_users_file(
    client, db_session, logged_in_admin, seeded_other_user
) -> None:
    from app.models.file import File

    other_file = File(
        owner_id=seeded_other_user.id,
        original_filename="theirs.txt",
        storage_key=uuid.uuid4(),
        mime_type="text/plain",
        size_bytes=5,
        sha256="0" * 64,
        wrapped_dek=b"\x00" * 60,
        nonce=b"\x00" * 12,
        auth_tag=b"\x00" * 16,
        kek_version=1,
    )
    db_session.add(other_file)
    db_session.commit()
    response = client.get(f"/api/files/{other_file.id}/classification")
    assert response.status_code == 404


def test_create_pending_is_idempotent(db_session, logged_in_admin) -> None:
    # Reuse the same file_id; second call should return the same row.
    fake_file_id = uuid.uuid4()
    # Insert a minimal File row so the FK passes.
    from app.models.file import File

    f = File(
        id=fake_file_id,
        owner_id=logged_in_admin.id,
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

    r1 = classification_service.create_pending(fake_file_id)
    r2 = classification_service.create_pending(fake_file_id)
    assert r1.id == r2.id
