"""Document sensitivity classifier (v6).

Public API:

    from app.classifier_core import classify, ClassifyResult, Tier, CLASSIFIER_VERSION

    result = classify(text)              # ClassifyResult
    result.final_tier                    # Tier enum
    result.raw_scores                    # dict[str, float]
    result.categories_triggered          # list[str]
    result.presidio_entities             # dict[str, int] (entity_type -> count)

The first call loads the HuggingFace zero-shot model and Presidio analyzer
(~30s on CPU). Subsequent calls reuse the cached instances. Designed to be
called from the Celery worker; do not import in the Flask web process.

Extracted from the original `classify_sensitivity.py` (root) which now wraps
this library as a CLI.
"""

from __future__ import annotations

from app.classifier_core.extract import EXTRACTORS, get_text
from app.classifier_core.pipeline import (
    CLASSIFIER_VERSION,
    ClassifyResult,
    classify,
    reset_classifier_cache,
)
from app.classifier_core.tiers import Tier, max_tier, tier_rank

__all__ = [
    "CLASSIFIER_VERSION",
    "ClassifyResult",
    "EXTRACTORS",
    "Tier",
    "classify",
    "get_text",
    "max_tier",
    "reset_classifier_cache",
    "tier_rank",
]
