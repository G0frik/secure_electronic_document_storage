"""Pydantic schemas for /api/share-links/*."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ShareLinkCreateRequest(BaseModel):
    file_id: uuid.UUID
    expires_at: datetime | None = None
    max_uses: int | None = Field(default=None, ge=1, le=10_000)
    force_for_restricted: bool = False
