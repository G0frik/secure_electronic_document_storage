"""Sensitivity tier enum + ordering helpers."""

from __future__ import annotations

import enum


class Tier(str, enum.Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


# Numeric rank — higher = more sensitive. Used to combine signals.
TIER_RANK: dict[Tier, int] = {
    Tier.PUBLIC: 0,
    Tier.INTERNAL: 1,
    Tier.CONFIDENTIAL: 2,
    Tier.RESTRICTED: 3,
}


def tier_rank(tier: Tier | str) -> int:
    """Return the numeric rank of a tier (string or enum)."""
    if isinstance(tier, str):
        tier = Tier(tier)
    return TIER_RANK[tier]


def max_tier(*tiers: Tier | str) -> Tier:
    """Return the highest-sensitivity tier among the inputs."""
    if not tiers:
        return Tier.PUBLIC
    normalised = [t if isinstance(t, Tier) else Tier(t) for t in tiers]
    return max(normalised, key=lambda t: TIER_RANK[t])
