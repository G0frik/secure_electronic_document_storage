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
    assert record.classifier_version == "v7"
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


def test_run_classification_keeps_plaintext_off_the_disk(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    import docx

    doc = docx.Document()
    doc.add_paragraph("Salary report: alice $90k bob $110k")
    body = io.BytesIO()
    doc.save(body)
    docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    with patch("app.tasks.classification.classify_file.delay"):
        response = _upload(client, csrf_token, "memo.docx", body.getvalue(), docx_mime)
    file_id = uuid.UUID(response.json["id"])

    seen: list[str] = []

    def spy(text: str) -> ClassifyResult:
        seen.append(text)
        return _fake_classify(text)

    no_disk = AssertionError("decrypted file written to disk")
    with (
        patch("tempfile.NamedTemporaryFile", side_effect=no_disk),
        patch("tempfile.mkstemp", side_effect=no_disk),
        patch("tempfile.TemporaryFile", side_effect=no_disk),
    ):
        record = classification_service.run_classification(file_id, classifier_fn=spy)

    assert record.status == ClassificationStatus.COMPLETED, record.error_message
    assert "Salary report" in seen[0]


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


def test_classification_endpoint_403_for_regular_user_on_other_users_file(
    client, db_session, logged_in_user, seeded_admin
) -> None:
    """Phase 5: a non-owner non-admin can't peek at another user's classification."""
    from app.models.file import File

    other_file = File(
        owner_id=seeded_admin.id,
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
    assert response.status_code == 403
    assert response.json["reason"] == "classification_pending"


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


# --- One classification row per file version ---


def _tier_classifier(tier: Tier):
    result = ClassifyResult(final_tier=tier, zero_shot_tier=tier, presidio_tier=Tier.PUBLIC)
    return lambda _text: result


def _upload_version(client, csrf_token, file_id, content):
    return client.post(
        f"/api/files/{file_id}/versions",
        data={"file": (io.BytesIO(content), "doc.txt", "text/plain")},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )


def _rows(db_session, file_id) -> list[Classification]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(Classification)
            .where(Classification.file_id == file_id)
            .order_by(Classification.version)
        )
    )


def test_new_file_version_gets_its_own_classification_row(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "doc.txt", b"plain notes")
    file_id = uuid.UUID(up.json["id"])
    classification_service.run_classification(file_id, classifier_fn=_tier_classifier(Tier.PUBLIC))

    assert _upload_version(client, csrf_token, file_id, b"salary data").status_code == 201
    v1, v2 = _rows(db_session, file_id)
    assert (v1.status, v1.final_tier) == (ClassificationStatus.COMPLETED, ClassificationTier.PUBLIC)
    assert v2.status == ClassificationStatus.PENDING
    assert classification_service.get_latest(file_id).id == v2.id

    # The worker writes to the newest row and leaves the old decision alone.
    record = classification_service.run_classification(
        file_id, classifier_fn=_tier_classifier(Tier.RESTRICTED)
    )
    assert record.id == v2.id
    v1, v2 = _rows(db_session, file_id)
    assert v1.final_tier == ClassificationTier.PUBLIC
    assert (v2.status, v2.final_tier) == (ClassificationStatus.COMPLETED, ClassificationTier.RESTRICTED)


def test_approved_override_does_not_carry_over_to_new_version(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    from app.services import tier_overrides
    from app.services.files import get_by_id

    up = _upload(client, csrf_token, "doc.txt", b"plain notes")
    file_id = uuid.UUID(up.json["id"])
    classification_service.run_classification(
        file_id, classifier_fn=_tier_classifier(Tier.CONFIDENTIAL)
    )
    req = tier_overrides.create_request(
        file=get_by_id(file_id),
        requested_tier=ClassificationTier.PUBLIC,
        justification="nothing sensitive",
        actor=logged_in_admin,
    )
    override = tier_overrides.approve(req, reviewer=logged_in_admin)

    # A repeated worker run must not overwrite the human decision.
    classification_service.run_classification(file_id, classifier_fn=_tier_classifier(Tier.RESTRICTED))
    assert classification_service.get_latest(file_id).id == override.id
    assert classification_service.get_latest(file_id).final_tier == ClassificationTier.PUBLIC

    _upload_version(client, csrf_token, file_id, b"salary data")
    latest = classification_service.get_latest(file_id)
    assert latest.id != override.id
    assert latest.status == ClassificationStatus.PENDING

    classification_service.run_classification(file_id, classifier_fn=_tier_classifier(Tier.RESTRICTED))
    assert classification_service.get_latest(file_id).final_tier == ClassificationTier.RESTRICTED


def test_admin_reclassify_row_reaches_completed(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "doc.txt", b"plain notes")
    file_id = uuid.UUID(up.json["id"])
    resp = client.post(
        f"/api/admin/files/{file_id}/reclassify", headers={"X-CSRF-Token": csrf_token}
    )
    assert resp.status_code == 202

    record = classification_service.run_classification(
        file_id, classifier_fn=_tier_classifier(Tier.INTERNAL)
    )
    assert record.version == resp.json["classification_version"]
    assert record.status == ClassificationStatus.COMPLETED
    assert classification_service.get_latest(file_id).id == record.id


def test_override_approved_after_new_version_is_refused_and_closed(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    from app.models.tier_override import OverrideStatus
    from app.services import tier_overrides
    from app.services.files import get_by_id

    up = _upload(client, csrf_token, "doc.txt", b"plain notes")
    file_id = uuid.UUID(up.json["id"])
    classification_service.run_classification(
        file_id, classifier_fn=_tier_classifier(Tier.CONFIDENTIAL)
    )
    req = tier_overrides.create_request(
        file=get_by_id(file_id),
        requested_tier=ClassificationTier.PUBLIC,
        justification="nothing sensitive",
        actor=logged_in_admin,
    )
    _upload_version(client, csrf_token, file_id, b"salary data")
    classification_service.run_classification(file_id, classifier_fn=_tier_classifier(Tier.RESTRICTED))

    resp = client.post(
        f"/api/admin/tier-override-requests/{req.id}/approve",
        json={},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert resp.status_code == 409
    assert resp.json["error"] == "stale_request"
    db_session.expire_all()
    assert tier_overrides.get_by_id(req.id).status == OverrideStatus.DENIED
    assert classification_service.get_latest(file_id).final_tier == ClassificationTier.RESTRICTED
    # The closed request no longer blocks a fresh one on the new version.
    tier_overrides.create_request(
        file=get_by_id(file_id),
        requested_tier=ClassificationTier.CONFIDENTIAL,
        justification="no identifiers",
        actor=logged_in_admin,
    )
