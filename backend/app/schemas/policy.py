"""Pydantic schemas for /api/admin/policies endpoints."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.models.classification import ClassificationTier
from app.models.user import Role


class PolicyCreateRequest(BaseModel):
    role: Role
    department_id: uuid.UUID | None = None
    allowed_max_tier: ClassificationTier
    allowed_categories: list[str] | None = None
    denied_categories: list[str] | None = None
    description: str | None = Field(default=None, max_length=256)


class PolicyUpdateRequest(BaseModel):
    """All fields optional — only the ones present are applied."""

    allowed_max_tier: ClassificationTier | None = None
    allowed_categories: list[str] | None = None
    denied_categories: list[str] | None = None
    description: str | None = Field(default=None, max_length=256)
    # Sentinels for "clear this field" — Pydantic v2 can't natively distinguish
    # "missing" from "None", so the patch handler treats `None` as "no change"
    # for nullable JSONB columns. Explicit clear via separate flags.
    clear_allowed_categories: bool = False
    clear_denied_categories: bool = False
    clear_department: bool = False
    clear_description: bool = False
