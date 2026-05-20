"""Pydantic schemas for /api/shares/*."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field

from app.models.share import SharePermission, ShareTargetType


class ShareCreateRequest(BaseModel):
    target_type: ShareTargetType
    target_id: uuid.UUID
    recipient_email: EmailStr
    permission: SharePermission = SharePermission.VIEWER
    note: str | None = Field(default=None, max_length=256)
