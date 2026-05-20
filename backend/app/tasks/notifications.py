"""Notification Celery tasks (Phase 11). One worker, one task: send an
email via the configured SMTP server (Mailhog in dev, real MTA in prod).
The worker fetches a `Notification` row by ID, looks up the recipient,
and sends a plain-text email summarising the event.
"""

from __future__ import annotations

import smtplib
import uuid
from email.message import EmailMessage

from app.app_factory import create_app
from app.config import settings
from app.logging_config import get_logger
from app.tasks.celery_app import celery

log = get_logger(__name__)


@celery.task(name="notifications.email", queue="notify", autoretry_for=(OSError,), retry_backoff=True, max_retries=3)
def send_email_for_notification(notification_id: str) -> str:
    """Send an email for the Notification with id *notification_id*. Returns
    "sent" on success, "skipped" when email is disabled or the recipient
    is missing, "error" on permanent failure (retriable failures raise so
    Celery retries automatically).
    """
    app = create_app()
    with app.app_context():
        if not settings.notifications_email_enabled:
            log.info("notifications.email_disabled", notification_id=notification_id)
            return "skipped"

        from app.extensions import db
        from app.models.notification import Notification
        from app.models.user import User

        n = db.session.get(Notification, uuid.UUID(notification_id))
        if n is None:
            log.warning(
                "notifications.email_unknown_notification",
                notification_id=notification_id,
            )
            return "skipped"

        recipient = db.session.get(User, n.recipient_user_id)
        if recipient is None or not recipient.is_active:
            log.warning(
                "notifications.email_inactive_recipient",
                notification_id=notification_id,
                recipient_user_id=str(n.recipient_user_id),
            )
            return "skipped"

        msg = EmailMessage()
        msg["From"] = "docstore@example.com"
        msg["To"] = recipient.email
        msg["Subject"] = f"[docstore][{n.severity}] {n.title}"
        msg.set_content(
            "\n".join(
                [
                    n.title,
                    "",
                    n.body or "",
                    "",
                    f"Event: {n.action_type}",
                    f"Severity: {n.severity}",
                    f"Audit log id: {n.audit_log_id}",
                    "",
                    "— Secure Document Storage",
                ]
            )
        )

        try:
            with smtplib.SMTP(settings.mail_server, settings.mail_port, timeout=10) as smtp:
                smtp.send_message(msg)
        except smtplib.SMTPException as exc:
            log.warning(
                "notifications.email_smtp_failed",
                notification_id=notification_id,
                error=str(exc),
            )
            return "error"

        log.info(
            "notifications.email_sent",
            notification_id=notification_id,
            to=recipient.email,
            severity=n.severity,
        )
        return "sent"
