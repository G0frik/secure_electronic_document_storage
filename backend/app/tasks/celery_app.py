"""Celery application instance and queue config.

Phase 0: configured but with no real tasks yet. The `classification`,
`av_scan`, `cleanup`, and `notify` queues are declared now so they can be
wired into worker autoscaling later without re-architecting.
"""

from __future__ import annotations

from celery import Celery
from kombu import Queue

from app.config import settings
from app.logging_config import configure_logging, get_logger

configure_logging(settings.log_level)
log = get_logger(__name__)

celery = Celery(
    "docstore",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.classification"],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_queues=(
        Queue("classification"),
        Queue("av_scan"),
        Queue("cleanup"),
        Queue("notify"),
        Queue("default"),
    ),
    task_default_queue="default",
)


@celery.task(name="health.ping")
def ping() -> str:
    """Trivial task to verify the worker is alive."""
    log.info("celery.ping")
    return "pong"
