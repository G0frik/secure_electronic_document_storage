"""End-to-end classification pipeline.

The public `classify(text)` function returns a structured, JSON-serializable
`ClassifyResult`. Internally it loads (and caches) the HuggingFace zero-shot
pipeline + Presidio analyzer, then combines the two signals via
`max_tier(zero_shot_tier, presidio_tier)` — defense in depth. With
CLASSIFIER_ENGINE=llm the semantic tier comes from the LLM instead (stored in
the same `zero_shot_tier` field). `classify_views` adds the configured
prompt-injection defenses (D2 two views, D4 detector gate).

Cached instances are module-level singletons. Tests can reset via
`reset_classifier_cache()`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from app.classifier_core import presidio_layer, zero_shot
from app.classifier_core.docx_text import TextViews
from app.classifier_core.tiers import Tier, max_tier
from app.config import settings
from app.logging_config import get_logger

log = get_logger(__name__)

CLASSIFIER_VERSION = "v7"


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

    needs_review: bool = False
    """D4: an injection detector flagged the text, so the tier was forced to RESTRICTED."""

    config: dict[str, Any] = field(default_factory=dict)
    """Engine, model, prompt and defenses that produced this result (stored per row)."""

    def to_jsonable(self) -> dict[str, Any]:
        out: dict[str, Any] = asdict(self)
        out["final_tier"] = self.final_tier.value
        out["zero_shot_tier"] = self.zero_shot_tier.value
        out["presidio_tier"] = self.presidio_tier.value
        return out


# Module-level singletons (lazy-loaded). One per worker process.
_zero_shot_pipeline = None
_zero_shot_max_words: int | None = None
_zero_shot_model_id: str | None = None
_presidio_analyzer = None
_llm_engine = None
_detector = None

DETECTOR_THRESHOLD = 0.5


def _nli_model() -> tuple[str, int]:
    model_selection = settings.classifier_model
    if settings.classifier_multilingual and model_selection == "base":
        model_selection = "multilingual"
    return zero_shot.select_model(model_selection)


def _ensure_loaded() -> tuple[Any, int, Any | None]:
    """Return (pipeline, max_words, analyzer-or-None). Loads on first call."""
    global _zero_shot_pipeline, _zero_shot_max_words, _zero_shot_model_id

    if _zero_shot_pipeline is None:
        model_id, max_words = _nli_model()
        log.info("classifier.loading_zero_shot", model=model_id, max_words=max_words)
        _zero_shot_pipeline = zero_shot.load_classifier(model_id)
        _zero_shot_max_words = max_words
        _zero_shot_model_id = model_id

    if _zero_shot_max_words is None:
        raise RuntimeError("zero-shot model failed to load")
    return _zero_shot_pipeline, _zero_shot_max_words, _ensure_presidio()


def _ensure_presidio() -> Any | None:
    global _presidio_analyzer
    if _presidio_analyzer is None and not settings.classifier_disable_presidio:
        log.info("classifier.loading_presidio")
        _presidio_analyzer = presidio_layer.build_analyzer()
    return _presidio_analyzer


def _llm_prompt() -> str:
    return "classify_hardened_v1" if "D1" in settings.defenses else settings.llm_prompt


def _ensure_llm() -> Any:
    global _llm_engine
    if _llm_engine is None:
        from app.classifier_core.llm import LlmEngine

        _llm_engine = LlmEngine(
            settings.llm_base_url, settings.llm_model, _llm_prompt(), seed=42,
            timeout=settings.llm_timeout,
        )  # fmt: skip
    return _llm_engine


def _ensure_detector() -> Any:
    global _detector
    if _detector is None:
        from app.classifier_core.detector import Detector

        log.info("classifier.loading_detector", detector=settings.classifier_detector)
        _detector = Detector(settings.classifier_detector)
    return _detector


def reset_classifier_cache() -> None:
    """For tests: drop cached pipelines so the next call re-loads."""
    global _zero_shot_pipeline, _zero_shot_max_words, _zero_shot_model_id, _presidio_analyzer
    global _llm_engine, _detector
    _zero_shot_pipeline = None
    _zero_shot_max_words = None
    _zero_shot_model_id = None
    _presidio_analyzer = None
    _llm_engine = None
    _detector = None


def _semantic(text: str) -> tuple[Tier, list[str], dict[str, float]]:
    """(tier, triggered category short names, scores) from the configured engine."""
    if settings.classifier_engine == "llm":
        result = _ensure_llm().classify(text)
        if result.tier is None:  # fail closed: the row becomes FAILED, never PUBLIC
            raise ValueError(f"LLM answer unusable: {result.error}")
        return result.tier, result.categories, {}
    pipeline, max_words, _ = _ensure_loaded()
    raw_scores_full = zero_shot.zero_shot_classify(pipeline, text, max_words)
    zs_tier, zs_triggered = zero_shot.zero_shot_tier(raw_scores_full)
    # Short category names, so the long hypothesis strings are not stored in the DB.
    triggered_short = [zero_shot.short_name(cat) for cat, _, _ in zs_triggered]
    raw_scores_short = {
        zero_shot.short_name(cat): round(score, 4) for cat, score in raw_scores_full.items()
    }
    return zs_tier, triggered_short, raw_scores_short


def classify(text: str) -> ClassifyResult:
    """Run the semantic engine + Presidio on *text* and return the combined tier."""
    zs_tier, triggered_short, raw_scores_short = _semantic(text)
    analyzer = _ensure_presidio()

    if analyzer is not None:
        if "D6" in settings.defenses:
            entity_summary, p_tier, _ = presidio_layer.presidio_scan_folded(analyzer, text)
        else:
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

    return ClassifyResult(
        final_tier=final,
        zero_shot_tier=zs_tier,
        presidio_tier=p_tier,
        raw_scores=raw_scores_short,
        categories_triggered=triggered_short,
        presidio_entities=presidio_clean,
    )


def _higher(a: ClassifyResult, b: ClassifyResult) -> ClassifyResult:
    """D2: each tier is the higher of the two views; categories and scores are merged."""
    scores = a.raw_scores | {k: max(v, a.raw_scores.get(k, v)) for k, v in b.raw_scores.items()}
    return replace(
        a,
        final_tier=max_tier(a.final_tier, b.final_tier),
        zero_shot_tier=max_tier(a.zero_shot_tier, b.zero_shot_tier),
        presidio_tier=max_tier(a.presidio_tier, b.presidio_tier),
        raw_scores=scores,
        categories_triggered=list(dict.fromkeys(a.categories_triggered + b.categories_triggered)),
        presidio_entities=b.presidio_entities | a.presidio_entities,
    )


def classifier_config() -> dict[str, Any]:
    """What produced a result: engine, model, prompt, Presidio on/off, defenses."""
    if settings.classifier_engine == "llm":
        engine = {"engine": "llm", "model": settings.llm_model, "prompt": _llm_prompt()}
    else:
        engine = {"engine": "nli", "model": _zero_shot_model_id or _nli_model()[0]}
    return engine | {"presidio": not settings.classifier_disable_presidio,
                     "defenses": sorted(settings.defenses)}  # fmt: skip


def classify_views(
    views: TextViews, classifier_fn: Callable[[str], Any] | None = None
) -> ClassifyResult:
    """Classify a document's full text and apply the configured defenses.

    D2: the visible text is classified too where it differs, and the higher tier wins, so text
    hidden from a reader can raise the tier but never lower it. D4: if the injection detector
    flags any classified text, the tier becomes RESTRICTED and the result needs review.
    """
    fn = classifier_fn or classify
    defenses = settings.defenses
    texts = [views.full]
    if "D2" in defenses and views.visible != views.full:
        texts.append(views.visible)
    results = [fn(t) for t in texts]
    for r in results:
        if not isinstance(r, ClassifyResult):
            raise TypeError(f"classifier returned {type(r).__name__}, expected ClassifyResult")
    result = results[0] if len(results) == 1 else _higher(results[0], results[1])
    config = classifier_config()
    flagged = False
    if "D4" in defenses:
        score = max(_ensure_detector().score(t)[0] for t in texts)
        flagged = score >= DETECTOR_THRESHOLD
        config |= {"detector": settings.classifier_detector, "detector_score": round(score, 4)}
    config["needs_review"] = flagged
    final = Tier.RESTRICTED if flagged else result.final_tier
    return replace(result, final_tier=final, needs_review=flagged, config=config)
