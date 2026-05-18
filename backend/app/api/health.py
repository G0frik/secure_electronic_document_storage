"""Health and readiness endpoints."""

from __future__ import annotations

from flask import Blueprint
from sqlalchemy import text

from app.extensions import db
from app.logging_config import get_logger

log = get_logger(__name__)

bp = Blueprint("health", __name__)


@bp.get("/healthz")
def healthz() -> tuple[dict[str, str], int]:
    """Liveness probe. Returns ok if the process is up."""
    return {"status": "ok"}, 200


@bp.get("/readyz")
def readyz() -> tuple[dict[str, object], int]:
    """Readiness probe. Checks DB connectivity."""
    checks: dict[str, str] = {}
    overall = "ok"

    try:
        db.session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        log.warning("readyz.db_check_failed", error=str(exc))
        checks["database"] = "fail"
        overall = "degraded"

    return {"status": overall, "checks": checks}, 200 if overall == "ok" else 503
