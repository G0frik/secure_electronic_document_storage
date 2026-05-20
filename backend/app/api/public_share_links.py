"""Public consumer endpoints for external share links (Phase 8).

Mounted at `/api/public/share-links/<token>` — no session auth, no CSRF,
rate-limited. The token is the high-entropy URL-safe secret; the server
hashes it and looks up the matching row.

Status codes:
    200 — valid landing / successful download
    404 — token doesn't match any row (don't leak whether the file exists)
    410 Gone — token matched but revoked / expired / exhausted
"""

from __future__ import annotations

from urllib.parse import quote

from flask import Blueprint, Response, jsonify, request
from werkzeug.utils import secure_filename

from app.extensions import limiter
from app.services import share_links
from app.services.share_links import (
    ShareLinkInvalidError,
    ShareLinkNotFoundError,
)

bp = Blueprint("public_share_links", __name__, url_prefix="/api/public/share-links")


def _client_ip() -> str | None:
    return request.remote_addr


@bp.get("/<token>")
@limiter.limit("30 per minute")
def landing(token: str):  # type: ignore[no-untyped-def]
    """Public landing-page lookup. Returns file metadata + remaining uses
    so the SPA can render a "Download this file" page.
    """
    try:
        link = share_links.lookup_active(token)
    except ShareLinkNotFoundError:
        share_links.record_use_denied("not_found", requester_ip=_client_ip())
        return jsonify({"error": "not_found"}), 404
    except ShareLinkInvalidError as exc:
        share_links.record_use_denied(exc.reason, requester_ip=_client_ip())
        return jsonify({"error": "invalid", "reason": exc.reason}), 410

    share_links.record_viewed(link, requester_ip=_client_ip())
    file_row = link.file
    return (
        jsonify(
            {
                "filename": file_row.original_filename,
                "mime_type": file_row.mime_type,
                "size_bytes": file_row.size_bytes,
                "expires_at": link.expires_at.isoformat() if link.expires_at else None,
                "max_uses": link.max_uses,
                "use_count": link.use_count,
                "remaining_uses": (
                    None if link.max_uses is None else max(0, link.max_uses - link.use_count)
                ),
            }
        ),
        200,
    )


@bp.get("/<token>/download")
@limiter.limit("30 per minute")
def download(token: str):  # type: ignore[no-untyped-def]
    """Stream the decrypted file. Increments `use_count` BEFORE streaming so
    a concurrent second hit on a `max_uses=1` link gets 410.
    """
    try:
        link = share_links.lookup_active(token)
    except ShareLinkNotFoundError:
        share_links.record_use_denied("not_found", requester_ip=_client_ip())
        return jsonify({"error": "not_found"}), 404
    except ShareLinkInvalidError as exc:
        share_links.record_use_denied(exc.reason, requester_ip=_client_ip())
        return jsonify({"error": "invalid", "reason": exc.reason}), 410

    file_row, chunks = share_links.consume_and_stream(link, requester_ip=_client_ip())
    ascii_name = secure_filename(file_row.original_filename) or "download"
    quoted = quote(file_row.original_filename, safe="")
    headers = {
        "Content-Length": str(file_row.size_bytes),
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quoted}'
        ),
    }
    return Response(chunks, mimetype=file_row.mime_type, headers=headers)
