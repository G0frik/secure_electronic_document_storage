"""End-to-end classification pipeline.

The public `classify(text)` function returns a structured, JSON-serializable
`ClassifyResult`. Internally it loads (and caches) the HuggingFace zero-shot
pipeline + Presidio analyzer, then combines the two signals via
`max_tier(zero_shot_tier, presidio_tier)` — defense in depth.

Cached instances are module-level singletons. Tests can reset via
`reset_classifier_cache()`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.classifier_core import presidio_layer, zero_shot
from app.classifier_core.tiers import Tier, max_tier
from app.config import settings
from app.logging_config import get_logger

log = get_logger(__name__)

CLASSIFIER_VERSION = "v6"


@dataclass(frozen=True)
class ClassifyResult:
    """JSON-serializable classification outcome."""

    final_tier: Tier
    zero_shot_tier: Tier
    presidio_tier: Tier
    raw_scores: dict[str, float] = field(default_factory=dict)
    """Category short-name → score for every category fed to NLI."""

    categories_triggered: list[str] = field(default_factory=list)
    """Short names of categories that cleared their per-tier floor."""

    presidio_entities: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Per-entity {count, max_score, samples}. `raw_values` is stripped."""

    classifier_version: str = CLASSIFIER_VERSION

    def to_jsonable(self) -> dict[str, Any]:
        out: dict[str, Any] = asdict(self)
        out["final_tier"] = self.final_tier.value
        out["zero_shot_tier"] = self.zero_shot_tier.value
        out["presidio_tier"] = self.presidio_tier.value
        return out


# Module-level singletons (lazy-loaded). One per worker process.
_zero_shot_pipeline = None
_zero_shot_max_words: int | None = None
_presidio_analyzer = None


def _ensure_loaded() -> tuple[Any, int, Any | None]:
    """Return (pipeline, max_words, analyzer-or-None). Loads on first call."""
    global _zero_shot_pipeline, _zero_shot_max_words, _presidio_analyzer

    if _zero_shot_pipeline is None:
        model_selection = settings.classifier_model
        if settings.classifier_multilingual and model_selection == "base":
            model_selection = "multilingual"
        model_id, max_words = zero_shot.select_model(model_selection)
        log.info("classifier.loading_zero_shot", model=model_id, max_words=max_words)
        _zero_shot_pipeline = zero_shot.load_classifier(model_id)
        _zero_shot_max_words = max_words

    if _presidio_analyzer is None and not settings.classifier_disable_presidio:
        log.info("classifier.loading_presidio")
        _presidio_analyzer = presidio_layer.build_analyzer()

    assert _zero_shot_max_words is not None
    return _zero_shot_pipeline, _zero_shot_max_words, _presidio_analyzer


def reset_classifier_cache() -> None:
    """For tests: drop cached pipelines so the next call re-loads."""
    global _zero_shot_pipeline, _zero_shot_max_words, _presidio_analyzer
    _zero_shot_pipeline = None
    _zero_shot_max_words = None
    _presidio_analyzer = None


def classify(text: str) -> ClassifyResult:
    """Run zero-shot + Presidio on *text* and return the combined tier."""
    pipeline, max_words, analyzer = _ensure_loaded()

    raw_scores_full = zero_shot.zero_shot_classify(pipeline, text, max_words)
    zs_tier, zs_triggered = zero_shot.zero_shot_tier(raw_scores_full)

    if analyzer is not None:
        entity_summary = presidio_layer.presidio_scan(analyzer, text)
        p_tier = presidio_layer.presidio_tier(entity_summary)
    else:
        entity_summary = {}
        p_tier = Tier.PUBLIC

    final = max_tier(zs_tier, p_tier)

    # Strip raw_values from the per-entity summary before storing — those
    # are the actual matched PII strings and have no place in audit data.
    presidio_clean = {}
    for ent, info in entity_summary.items():
        cleaned = {k: v for k, v in info.items() if k != "raw_values"}
        presidio_clean[ent] = cleaned

    # Shorthand category names for the trigger list.
    triggered_short = [zero_shot.short_name(cat) for cat, _, _ in zs_triggered]

    # Map full category labels → short names in raw_scores too, so we don't
    # store the long hypothesis strings in the DB.
    raw_scores_short = {
        zero_shot.short_name(cat): round(score, 4) for cat, score in raw_scores_full.items()
    }

    return ClassifyResult(
        final_tier=final,
        zero_shot_tier=zs_tier,
        presidio_tier=p_tier,
        raw_scores=raw_scores_short,
        categories_triggered=triggered_short,
        presidio_entities=presidio_clean,
    )
