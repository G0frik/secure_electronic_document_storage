"""Celery tasks on the `cleanup` queue.

Phase 9 ships `trash.reap` — hard-deletes files trashed more than 30 days
ago. A production deployment wires this to Celery Beat or an external cron
hitting the equivalent `flask reap-trash` CLI command (see `cli.py`).
"""

from __future__ import annotations

from app.app_factory import create_app
from app.logging_config import get_logger
from app.tasks.celery_app import celery

log = get_logger(__name__)


@celery.task(name="trash.reap", queue="cleanup")
def reap_trash(retention_days: int = 30) -> int:
    """Hard-delete every file trashed before now - retention_days. Returns
    the count purged. Idempotent — if there's nothing past the cutoff this
    is a no-op.
    """
    app = create_app()
    with app.app_context():
        from app.services import trash

        count = trash.reap_expired_trash(retention_days=retention_days)
        log.info("trash.reap.complete", retention_days=retention_days, count=count)
        return count


@celery.task(name="quota.recompute", queue="cleanup")
def recompute_quota_usage() -> int:
    """Phase 12 drift protection: recompute every user's `used_bytes` from
    `SUM(files.size_bytes)`. Run nightly in production; the inline updates
    on upload + hard-delete are the hot path.
    """
    app = create_app()
    with app.app_context():
        from app.services import quota

        affected = quota.recompute_all()
        log.info("quota.recompute.complete", affected=affected)
        return affected
