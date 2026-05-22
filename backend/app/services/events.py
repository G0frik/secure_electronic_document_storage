"""SIEM-friendly event stream (Phase 11).

Every `audit.record` call funnels through here to produce one line of
ECS-shaped NDJSON in the rotating event log file. Filebeat (Elastic) and
Wazuh agent both read that file directly — see
[[Roadmap/SIEM Ingestion]] for the agent configs.

ECS = Elastic Common Schema. Both Elastic and Wazuh map the field names
to their internal indices without custom parsers, so the same line is
queryable as `event.action: "auth.login.success"` everywhere.

The mapping function `to_ecs(audit_row)` is the single source of truth.
Anything we emit on the wire — file output, admin API, debug stdout —
goes through it.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

from app.config import settings
from app.logging_config import get_logger
from app.models.audit import AuditLog, AuditSeverity

log = get_logger(__name__)


# --- Severity mapping ----------------------------------------------------
# ECS lets `event.severity` be a number 0-100 (higher = worse). Map our
# three-bucket enum to round numbers SIEM dashboards can threshold on.
_SEVERITY_TO_ECS: dict[str, int] = {
    AuditSeverity.INFO.value: 20,
    AuditSeverity.WARNING.value: 50,
    AuditSeverity.CRITICAL.value: 80,
}


# --- ECS category / outcome derivation ----------------------------------
# Each prefix maps to ECS `event.category` (a list — ECS expects an array)
# plus a `event.type` array. See https://www.elastic.co/guide/en/ecs/current/ecs-allowed-values-event-category.html
_CATEGORY_RULES: list[tuple[str, list[str], list[str]]] = [
    # (prefix, category[], type[])
    ("auth.totp.", ["authentication"], ["info"]),
    ("auth.login.", ["authentication"], ["start"]),
    ("auth.logout", ["authentication"], ["end"]),
    ("user.created", ["iam"], ["user", "creation"]),
    ("policy.decision.deny", ["iam"], ["denied"]),
    ("policy.decision.allow", ["iam"], ["allowed"]),
    ("policy.created", ["configuration"], ["creation"]),
    ("policy.updated", ["configuration"], ["change"]),
    ("policy.deleted", ["configuration"], ["deletion"]),
    ("file.uploaded", ["file"], ["creation"]),
    ("file.downloaded", ["file"], ["access"]),
    ("file.listed", ["file"], ["info"]),
    ("file.soft_deleted", ["file"], ["deletion"]),
    ("file.restored", ["file"], ["change"]),
    ("file.hard_deleted", ["file"], ["deletion"]),
    ("file.storage_removed", ["file"], ["deletion"]),
    ("trash.reaped", ["file"], ["deletion"]),
    ("folder.", ["file"], ["change"]),
    ("classification.", ["file", "process"], ["info"]),
    ("share.", ["file"], ["change"]),
    ("share_link.", ["file"], ["access"]),
    ("tag.", ["file"], ["change"]),
    ("tier_override.", ["iam", "process"], ["change"]),
]


def _categorise(action_type: str) -> tuple[list[str], list[str]]:
    for prefix, category, type_ in _CATEGORY_RULES:
        if action_type.startswith(prefix):
            return category, type_
    return ["process"], ["info"]


def _outcome_for(action_type: str, severity: str) -> str:
    if action_type.endswith(".failure") or action_type.endswith(".denied"):
        return "failure"
    if action_type.endswith(".failed") or action_type.endswith(".rejected"):
        return "failure"
    if "use_denied" in action_type or "challenge_failed" in action_type:
        return "failure"
    if "tier_blocked" in action_type:
        return "failure"
    if severity in (AuditSeverity.CRITICAL.value, AuditSeverity.WARNING.value):
        # Many warning-level rows are still successes (e.g. share.revoked) —
        # only flag as failure when the action_type semantics say so. The
        # default for warnings is still success.
        return "success"
    return "success"


def to_ecs(row: AuditLog) -> dict[str, Any]:
    """Translate an `AuditLog` row to an ECS-shaped dict ready for JSON
    serialisation. All keys present here are standard ECS field paths
    that Elastic, Wazuh, and most other SIEMs index natively.
    """
    severity_value = row.severity.value if hasattr(row.severity, "value") else str(row.severity)
    timestamp = row.timestamp or datetime.now(timezone.utc)
    category, type_ = _categorise(row.action_type)

    payload: dict[str, Any] = {
        "@timestamp": timestamp.isoformat(),
        "event": {
            "kind": "event",
            "action": row.action_type,
            "category": category,
            "type": type_,
            "outcome": _outcome_for(row.action_type, severity_value),
            "severity": _SEVERITY_TO_ECS.get(severity_value, 20),
            "dataset": "docstore.audit",
            "module": "docstore",
            "id": str(row.id),
        },
        "service": {
            "name": "docstore",
            "type": "audit",
        },
        "log": {
            "level": severity_value,
        },
        "message": _human_message(row),
        # Our own domain labels — anything off the dotted ECS paths goes
        # under `labels.*`, which is what ECS docs recommend.
        "labels": {
            "target_type": row.target_type,
            "target_id": str(row.target_id) if row.target_id else None,
        },
    }

    if row.actor_user_id is not None:
        payload["user"] = {"id": str(row.actor_user_id)}
        # Resolve email: prefer the actor relationship (always available
        # when the user row exists), fall back to event_metadata.email
        # (set explicitly at login-time when the relationship may not be
        # loaded yet).
        actor_email = None
        if row.actor is not None:
            actor_email = row.actor.email
        if not actor_email:
            actor_email = (row.event_metadata or {}).get("email")
        if actor_email:
            payload["user"]["email"] = actor_email

    if row.actor_ip:
        payload["source"] = {"ip": row.actor_ip}

    # File-specific events: lift `filename`, `size_bytes`, `tier` out of
    # the metadata into ECS `file.*` so dashboards can query them directly.
    meta = row.event_metadata or {}
    file_block: dict[str, Any] = {}
    if row.target_type == "file" and row.target_id:
        file_block["id"] = str(row.target_id)
        if "filename" in meta:
            file_block["name"] = meta["filename"]
        if "size_bytes" in meta:
            file_block["size"] = meta["size_bytes"]
        if "mime_type" in meta:
            file_block["mime_type"] = meta["mime_type"]
        if "sha256" in meta:
            file_block["hash"] = {"sha256": meta["sha256"]}
        if file_block:
            payload["file"] = file_block

    # Whatever metadata we didn't lift into ECS, keep under labels.metadata
    # so the original payload is searchable in the SIEM.
    leftover = {
        k: v
        for k, v in meta.items()
        if k not in {"filename", "size_bytes", "mime_type", "sha256", "email"}
    }
    if leftover:
        payload["labels"]["metadata"] = leftover

    return payload


def _human_message(row: AuditLog) -> str:
    """Short human-readable summary for the bell / SIEM message field."""
    meta = row.event_metadata or {}
    action = row.action_type
    if action == "auth.login.success":
        return f"User {meta.get('email', '?')} logged in"
    if action == "auth.login.failure":
        return f"Failed login: {meta.get('reason', 'unknown')}"
    if action == "file.uploaded":
        return f"Uploaded {meta.get('filename', '?')}"
    if action == "file.downloaded":
        return f"Downloaded {meta.get('filename', '?')}"
    if action == "file.soft_deleted":
        return f"Trashed {meta.get('filename', '?')}"
    if action == "file.hard_deleted":
        return f"Permanently deleted {meta.get('filename', '?')}"
    if action == "classification.completed":
        return f"Classified as {meta.get('final_tier', '?')}"
    if action == "classification.restricted":
        return f"File classified RESTRICTED: {meta.get('filename', '?')}"
    if action == "share_link.created":
        return f"External link minted (tier {meta.get('tier', '?')})"
    if action == "share_link.tier_blocked":
        return f"External link blocked: {meta.get('filename', '?')} is RESTRICTED"
    if action == "share_link.downloaded":
        return f"External link used (use #{meta.get('use_count_after', '?')})"
    if action == "tier_override.requested":
        return (
            f"Override request: {meta.get('current_tier', '?')} → "
            f"{meta.get('requested_tier', '?')}"
        )
    if action == "tier_override.approved":
        return f"Override approved: now {meta.get('requested_tier', '?')}"
    if action == "tier_override.denied":
        return "Override request denied"
    if action == "policy.decision.deny":
        return f"Access denied ({meta.get('reason', '?')})"
    return action


# --- NDJSON sink -------------------------------------------------------


_file_logger: logging.Logger | None = None


def _file_sink() -> logging.Logger | None:
    """Lazily build the rotating-file logger. Returns None when
    `EVENT_LOG_PATH` is empty (file output disabled, e.g. in tests).
    """
    global _file_logger
    if _file_logger is not None:
        return _file_logger
    if not settings.event_log_path:
        return None
    try:
        os.makedirs(os.path.dirname(settings.event_log_path) or ".", exist_ok=True)
        handler = RotatingFileHandler(
            settings.event_log_path,
            maxBytes=settings.event_log_max_bytes,
            backupCount=settings.event_log_backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        sink = logging.getLogger("docstore.events.ndjson")
        sink.setLevel(logging.INFO)
        sink.addHandler(handler)
        # Don't bubble to root — we already control the format here.
        sink.propagate = False
        _file_logger = sink
    except OSError as exc:
        log.warning("events.file_sink_failed", path=settings.event_log_path, error=str(exc))
        return None
    return _file_logger


def _reset_file_sink_for_tests() -> None:
    """Tests rotate settings; expose a hook to drop the cached handler."""
    global _file_logger
    if _file_logger is not None:
        for h in list(_file_logger.handlers):
            h.close()
            _file_logger.removeHandler(h)
        _file_logger = None


# --- Public emit ------------------------------------------------------


def emit(row: AuditLog) -> dict[str, Any]:
    """Convert *row* to ECS, write to the NDJSON sink (best effort), and
    return the payload so callers can inspect it in tests or surface
    via the admin events endpoint."""
    payload = to_ecs(row)
    sink = _file_sink()
    if sink is not None:
        try:
            sink.info(json.dumps(payload, default=_json_default, separators=(",", ":")))
        except Exception as exc:  # noqa: BLE001 — never let logging break the request
            log.warning("events.emit_failed", error=str(exc), action=row.action_type)
    return payload


def _json_default(obj: Any) -> Any:
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Cannot serialise {type(obj).__name__} to JSON")
