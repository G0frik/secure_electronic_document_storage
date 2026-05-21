"""Zero-shot NLI tier prediction.

Lifted from `classify_sensitivity.py` (v6) — same categories, hypotheses,
and per-tier thresholds. The DirectML/ORT GPU path from the CLI is omitted:
the worker runs in a Linux container with CPU PyTorch.
"""

from __future__ import annotations

from app.classifier_core.tiers import TIER_RANK, Tier

CATEGORY_TO_TIER: dict[str, Tier] = {
    "personally identifiable information such as social security numbers, full names with addresses, or government ID numbers": Tier.RESTRICTED,
    "payment card data such as credit card numbers, primary account numbers, or CVV security codes": Tier.RESTRICTED,
    "authentication credentials such as passwords, API keys, VPN shared secrets, or private keys": Tier.RESTRICTED,
    "medical records, patient health information, diagnoses, or prescriptions": Tier.RESTRICTED,
    "salary, compensation, or employee financial records": Tier.CONFIDENTIAL,
    "proprietary technology, trade secrets, source code, or technical security specifications": Tier.CONFIDENTIAL,
    "non-public business strategy, mergers and acquisitions, valuation models, unannounced financial projections, or material non-public information": Tier.CONFIDENTIAL,
    "internal business operations, company memos, non-public meeting notes, sprint retrospectives, product roadmaps, working drafts, postmortems, or internal team communications": Tier.INTERNAL,
    "publicly available marketing material, press releases, or general public information": Tier.PUBLIC,
}
CATEGORIES = list(CATEGORY_TO_TIER.keys())

# DeBERTa-v3 caps at 512 tokens → ~400 words. bge-m3 supports 8192 tokens,
# we use 6000 words there. Set by `select_model`.
MAX_WORDS_DEBERTA = 400
MAX_WORDS_MULTILINGUAL = 6000

# Per-tier zero-shot thresholds (v6).
PER_TIER_THRESHOLDS: dict[Tier, float] = {
    Tier.PUBLIC: 0.35,
    Tier.INTERNAL: 0.35,
    Tier.CONFIDENTIAL: 0.50,
    Tier.RESTRICTED: 0.70,
}

DEFAULT_MODEL = "MoritzLaurer/deberta-v3-base-zeroshot-v2.0"
LARGE_MODEL = "MoritzLaurer/deberta-v3-large-zeroshot-v2.0"
MULTILINGUAL_MODEL = "MoritzLaurer/bge-m3-zeroshot-v2.0-c"


def short_name(cat: str) -> str:
    """Human-readable shorthand for a category label (first clause only)."""
    return cat.split(" such as")[0].split(",")[0].strip()


def select_model(model_name_or_multilingual: str | bool) -> tuple[str, int]:
    """Return (model_id, max_words) for the requested mode."""
    if isinstance(model_name_or_multilingual, bool):
        if model_name_or_multilingual:
            return MULTILINGUAL_MODEL, MAX_WORDS_MULTILINGUAL
        return DEFAULT_MODEL, MAX_WORDS_DEBERTA

    name = model_name_or_multilingual.lower().strip()
    if name in ("multilingual", MULTILINGUAL_MODEL.lower()):
        return MULTILINGUAL_MODEL, MAX_WORDS_MULTILINGUAL
    if name in ("large", LARGE_MODEL.lower()):
        return LARGE_MODEL, MAX_WORDS_DEBERTA
    if name in ("base", DEFAULT_MODEL.lower()):
        return DEFAULT_MODEL, MAX_WORDS_DEBERTA

    return model_name_or_multilingual, MAX_WORDS_DEBERTA


def load_classifier(model_id: str):  # type: ignore[no-untyped-def]
    """Build a HuggingFace zero-shot pipeline (CPU PyTorch)."""
    from transformers import pipeline

    return pipeline("zero-shot-classification", model=model_id)


def zero_shot_classify(classifier, text: str, max_words: int) -> dict[str, float]:  # type: ignore[no-untyped-def]
    """Run the zero-shot pipeline and return a {category: score} mapping."""
    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words])
    result = classifier(
        text,
        candidate_labels=CATEGORIES,
        hypothesis_template="This document contains {}.",
        multi_label=True,
    )
    return dict(zip(result["labels"], result["scores"]))


def zero_shot_tier(
    scores_by_category: dict[str, float], threshold: float | None = None
) -> tuple[Tier, list[tuple[str, float, Tier]]]:
    """Pick the highest-tier category whose score clears the per-tier floor.

    Returns (tier, triggered) where `triggered` is a list of
    (category, score, implied_tier) tuples for inspection / audit.
    """
    triggered: list[tuple[str, float, Tier]] = []
    for cat, score in scores_by_category.items():
        implied = CATEGORY_TO_TIER[cat]
        floor = threshold if threshold is not None else PER_TIER_THRESHOLDS[implied]
        if score >= floor:
            triggered.append((cat, score, implied))
    if not triggered:
        return Tier.PUBLIC, []
    triggered.sort(key=lambda t: (TIER_RANK[t[2]], t[1]), reverse=True)
    return triggered[0][2], triggered
