"""Celery tasks for the classification queue."""

from __future__ import annotations

import uuid

from app.app_factory import create_app
from app.logging_config import get_logger
from app.tasks.celery_app import celery

log = get_logger(__name__)


@celery.task(name="files.classify", queue="classification")
def classify_file(file_id: str) -> str:
    """Worker entrypoint. Wraps the service call in a Flask app context so
    SQLAlchemy + audit + crypto all have the configured app available.

    Returns the resulting status string (for debugging / Flower).
    """
    # Build a fresh app context per task. The Celery worker is a long-lived
    # process; we don't reuse a global Flask app to avoid weird state leaks
    # between concurrent tasks (in Phase 4 concurrency=1, so this is overkill,
    # but it keeps the contract clean as we scale later).
    app = create_app()
    with app.app_context():
        from app.services import classification

        record = classification.run_classification(uuid.UUID(file_id))
        return record.status.value
