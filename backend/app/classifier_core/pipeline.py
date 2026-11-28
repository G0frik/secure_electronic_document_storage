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

import hashlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

from app.classifier_core import presidio_layer, zero_shot
from app.classifier_core.docx_text import TextViews
from app.classifier_core.llm import LLM_MAX_TOKENS
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


@dataclass(frozen=True)
class ClassifierConfig:
    """Everything that decides how a text is classified. `from_settings()` is what the service uses;
    callers that compare setups (the admin playground) pass their own."""

    engine: Literal["nli", "llm"] = "nli"
    nli_model: str = zero_shot.LARGE_MODEL
    nli_max_words: int = zero_shot.MAX_WORDS_DEBERTA
    nli_windows: bool = True  # False: score the first window only (the pre-windowing behaviour)
    nli_url: str = ""  # set: forward pass on a remote NLI server (research/nli_server.py)
    llm_base_url: str = ""
    llm_model: str = ""
    llm_prompt: str = "classify_v1"  # prompt file name; ignored when llm_prompt_text is set
    llm_prompt_text: str | None = None
    seed: int = 42
    temperature: float = 0.0
    top_p: float | None = None
    max_tokens: int = LLM_MAX_TOKENS
    thinking: bool = False
    llm_timeout: int = 120
    presidio: bool = True
    defenses: frozenset[str] = frozenset()
    detector: str = "pg2"

    def __post_init__(self) -> None:
        if self.engine not in ("nli", "llm"):
            raise ValueError(f"unknown engine {self.engine!r}")

    @classmethod
    def from_settings(cls) -> ClassifierConfig:
        model_id, max_words = _nli_model()
        return cls(
            engine=settings.classifier_engine, nli_model=model_id, nli_max_words=max_words,
            llm_base_url=settings.llm_base_url, llm_model=settings.llm_model,
            llm_prompt=settings.llm_prompt, llm_timeout=settings.llm_timeout,
            presidio=not settings.classifier_disable_presidio, defenses=settings.defenses,
            detector=settings.classifier_detector,
        )  # fmt: skip

    def prompt_name(self) -> str:
        if "D1" in self.defenses:
            return "classify_hardened_v1"
        return "custom" if self.llm_prompt_text is not None else self.llm_prompt


# Module-level caches (lazy-loaded). One per worker process. The service only ever uses the
# settings' config, so each cache holds one entry there; the playground may swap entries.
_zero_shot_pipeline = None
_zero_shot_model_id: str | None = None
_presidio_analyzer = None
_llm_engine = None
_llm_key: tuple[Any, ...] | None = None
_detector = None
_other_detectors: dict[str, Any] = {}

DETECTOR_THRESHOLD = 0.5


def _nli_model() -> tuple[str, int]:
    model_selection = settings.classifier_model
    if settings.classifier_multilingual:
        model_selection = "multilingual"
    return zero_shot.select_model(model_selection)


def _nli_pipe(model_id: str) -> Any:
    """The local zero-shot pipeline for `model_id`; at most one is kept loaded (RAM)."""
    global _zero_shot_pipeline, _zero_shot_model_id
    if _zero_shot_pipeline is None or _zero_shot_model_id != model_id:
        log.info("classifier.loading_zero_shot", model=model_id)
        _zero_shot_pipeline = None  # free the old one before loading the next
        _zero_shot_pipeline = zero_shot.load_classifier(model_id)
        _zero_shot_model_id = model_id
    return _zero_shot_pipeline


def _ensure_presidio() -> Any:
    global _presidio_analyzer
    if _presidio_analyzer is None:
        log.info("classifier.loading_presidio")
        _presidio_analyzer = presidio_layer.build_analyzer()
    return _presidio_analyzer


def _ensure_llm(cfg: ClassifierConfig) -> Any:
    global _llm_engine, _llm_key
    key = (cfg.llm_base_url, cfg.llm_model, cfg.prompt_name(), cfg.llm_prompt_text, cfg.seed,
           cfg.temperature, cfg.top_p, cfg.max_tokens, cfg.thinking, cfg.llm_timeout)  # fmt: skip
    if _llm_engine is None or _llm_key != key:
        from app.classifier_core.llm import LlmEngine

        _llm_engine = LlmEngine(
            cfg.llm_base_url, cfg.llm_model, cfg.prompt_name(), seed=cfg.seed,
            timeout=cfg.llm_timeout, max_tokens=cfg.max_tokens,
            template_kwargs={"enable_thinking": cfg.thinking}, temperature=cfg.temperature,
            top_p=cfg.top_p,
            prompt_text=None if "D1" in cfg.defenses else cfg.llm_prompt_text,
        )  # fmt: skip
        _llm_key = key
    return _llm_engine


def _ensure_detector(name: str) -> Any:
    global _detector
    from app.classifier_core.detector import Detector

    if name != settings.classifier_detector:  # only the playground asks for another detector
        if name not in _other_detectors:
            log.info("classifier.loading_detector", detector=name)
            _other_detectors[name] = Detector(name)
        return _other_detectors[name]
    if _detector is None:
        log.info("classifier.loading_detector", detector=name)
        _detector = Detector(name)
    return _detector


def reset_classifier_cache() -> None:
    """For tests: drop cached pipelines so the next call re-loads."""
    global _zero_shot_pipeline, _zero_shot_model_id, _presidio_analyzer
    global _llm_engine, _llm_key, _detector
    _zero_shot_pipeline = None
    _zero_shot_model_id = None
    _presidio_analyzer = None
    _llm_engine = None
    _llm_key = None
    _detector = None
    _other_detectors.clear()


def _semantic(
    text: str, cfg: ClassifierConfig, trace: list[dict[str, Any]] | None = None
) -> tuple[Tier, list[str], dict[str, float]]:
    """(tier, triggered category short names, scores) from the configured engine.

    `trace`, when given, gets the LLM's raw answer and reasoning text (the playground shows them).
    """
    if cfg.engine == "llm":
        result = _ensure_llm(cfg).classify(text)
        if trace is not None:
            trace.append({"raw": result.raw, "reasoning": result.reasoning,
                          "truncated": result.truncated})  # fmt: skip
        if result.tier is None:  # fail closed: the row becomes FAILED, never PUBLIC
            raise ValueError(f"LLM answer unusable: {result.error}")
        return result.tier, result.categories, {}
    if cfg.nli_url:
        raw_scores_full = zero_shot.remote_zero_shot(
            cfg.nli_url, cfg.nli_model, text, cfg.nli_max_words, cfg.nli_windows
        )
    else:
        raw_scores_full = zero_shot.zero_shot_classify(
            _nli_pipe(cfg.nli_model), text, cfg.nli_max_words, cfg.nli_windows
        )
    zs_tier, zs_triggered = zero_shot.zero_shot_tier(raw_scores_full)
    # Short category names, so the long hypothesis strings are not stored in the DB.
    triggered_short = [zero_shot.short_name(cat) for cat, _, _ in zs_triggered]
    raw_scores_short = {
        zero_shot.short_name(cat): round(score, 4) for cat, score in raw_scores_full.items()
    }
    return zs_tier, triggered_short, raw_scores_short


def classify(
    text: str, cfg: ClassifierConfig | None = None, trace: list[dict[str, Any]] | None = None
) -> ClassifyResult:
    """Run the semantic engine + Presidio on *text* and return the combined tier."""
    cfg = cfg or ClassifierConfig.from_settings()
    zs_tier, triggered_short, raw_scores_short = _semantic(text, cfg, trace)

    if cfg.presidio:
        analyzer = _ensure_presidio()
        if "D6" in cfg.defenses:
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


def classifier_config(cfg: ClassifierConfig | None = None) -> dict[str, Any]:
    """What produced a result: engine, model, prompt, Presidio on/off, defenses."""
    cfg = cfg or ClassifierConfig.from_settings()
    engine: dict[str, Any]
    if cfg.engine == "llm":
        engine = {"engine": "llm", "model": cfg.llm_model, "prompt": cfg.prompt_name()}
        if engine["prompt"] == "custom" and cfg.llm_prompt_text is not None:
            engine["prompt_sha256"] = hashlib.sha256(cfg.llm_prompt_text.encode()).hexdigest()[:12]
        defaults = ClassifierConfig()
        for name in ("seed", "temperature", "top_p", "max_tokens", "thinking"):
            if getattr(cfg, name) != getattr(defaults, name):  # stored only when changed
                engine[name] = getattr(cfg, name)
    else:
        engine = {"engine": "nli", "model": cfg.nli_model}
        if not cfg.nli_windows:
            engine["windows"] = False
        if cfg.nli_max_words != zero_shot.MAX_WORDS_DEBERTA:
            engine["max_words"] = cfg.nli_max_words
        if cfg.nli_url:
            engine["remote"] = True  # forward pass on the NLI server (ONNX), not local PyTorch
    return engine | {"presidio": cfg.presidio, "defenses": sorted(cfg.defenses)}


def classify_views(
    views: TextViews,
    classifier_fn: Callable[[str], Any] | None = None,
    cfg: ClassifierConfig | None = None,
) -> ClassifyResult:
    """Classify a document's full text and apply the configured defenses.

    D2: the visible text is classified too where it differs, and the higher tier wins, so text
    hidden from a reader can raise the tier but never lower it. D4: if the injection detector
    flags any classified text, the tier becomes RESTRICTED and the result needs review.
    `cfg` defaults to the service settings; `classifier_fn` replaces the per-text classifier (tests).
    """
    cfg = cfg or ClassifierConfig.from_settings()
    fn = classifier_fn or (lambda t: classify(t, cfg))
    texts = [views.full]
    if "D2" in cfg.defenses and views.visible != views.full:
        texts.append(views.visible)
    results = [fn(t) for t in texts]
    for r in results:
        if not isinstance(r, ClassifyResult):
            raise TypeError(f"classifier returned {type(r).__name__}, expected ClassifyResult")
    result = results[0] if len(results) == 1 else _higher(results[0], results[1])
    config = classifier_config(cfg)
    if len(results) == 2:
        config["view_tiers"] = {"full": results[0].final_tier.value,
                                "visible": results[1].final_tier.value}  # fmt: skip
    flagged = False
    if "D4" in cfg.defenses:
        score = max(_ensure_detector(cfg.detector).score(t)[0] for t in texts)
        flagged = score >= DETECTOR_THRESHOLD
        config |= {"detector": cfg.detector, "detector_score": round(score, 4)}
    config["needs_review"] = flagged
    final = Tier.RESTRICTED if flagged else result.final_tier
    return replace(result, final_tier=final, needs_review=flagged, config=config)
