"""Pydantic schemas for /api/files/<id>/tier-override-requests + admin endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.classification import ClassificationTier


class TierOverrideCreateRequest(BaseModel):
    requested_tier: ClassificationTier
    justification: str = Field(min_length=1, max_length=2000)


class TierOverrideDecisionRequest(BaseModel):
    decision_reason: str | None = Field(default=None, max_length=2000)
