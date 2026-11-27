"""Celery task for the admin playground (queue `playground`, own worker in playground mode)."""

from __future__ import annotations

import uuid

from app.app_factory import create_app
from app.tasks.celery_app import celery


@celery.task(name="playground.run", queue="playground")  # type: ignore[misc]
def run_playground(run_id: str) -> str:
    app = create_app()
    with app.app_context():
        from app.services import playground

        return playground.execute(uuid.UUID(run_id))
