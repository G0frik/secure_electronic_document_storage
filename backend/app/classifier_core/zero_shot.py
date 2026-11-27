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
HYPOTHESIS_TEMPLATE = "This document contains {}."

# DeBERTa-v3 caps at 512 tokens → ~400 words. bge-m3 supports 8192 tokens (~6000 words), but one
# long input lets a long public part outweigh a short sensitive one (dilution, attack A5), so the
# service scores bge-m3 in 400-word windows too. MAX_WORDS_MULTILINGUAL stays for research's
# one-pass nli_ml config. Set by `select_model`.
MAX_WORDS_DEBERTA = 400
MAX_WORDS_MULTILINGUAL = 6000
WINDOW_WORDS_MULTILINGUAL = 400
# Overlap between NLI windows, so a sentence cut at a window edge is seen whole in one of them.
WINDOW_OVERLAP_WORDS = 50

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
            return MULTILINGUAL_MODEL, WINDOW_WORDS_MULTILINGUAL
        return DEFAULT_MODEL, MAX_WORDS_DEBERTA

    name = model_name_or_multilingual.lower().strip()
    if name in ("multilingual", MULTILINGUAL_MODEL.lower()):
        return MULTILINGUAL_MODEL, WINDOW_WORDS_MULTILINGUAL
    if name in ("large", LARGE_MODEL.lower()):
        return LARGE_MODEL, MAX_WORDS_DEBERTA
    if name in ("base", DEFAULT_MODEL.lower()):
        return DEFAULT_MODEL, MAX_WORDS_DEBERTA

    return model_name_or_multilingual, MAX_WORDS_DEBERTA


def load_classifier(model_id: str):  # type: ignore[no-untyped-def]
    """Build a HuggingFace zero-shot pipeline (CPU PyTorch)."""
    from transformers import pipeline

    return pipeline("zero-shot-classification", model=model_id)


def word_windows(text: str, max_words: int, overlap: int = WINDOW_OVERLAP_WORDS) -> list[str]:
    """Windows of at most `max_words` words covering the whole text; a text that fits is returned as is."""
    words = text.split()
    if len(words) <= max_words:
        return [text]
    step = max_words - overlap
    return [" ".join(words[i : i + max_words]) for i in range(0, len(words) - overlap, step)]


def max_scores(per_window: list[dict[str, float]]) -> dict[str, float]:
    """Per-category maximum over windows: a category found in any window counts for the document."""
    return {cat: max(s[cat] for s in per_window) for cat in per_window[0]}


def zero_shot_classify(  # type: ignore[no-untyped-def]
    classifier, text: str, max_words: int, windows: bool = True
) -> dict[str, float]:
    """Run the zero-shot pipeline and return a {category: score} mapping.

    A text longer than `max_words` is scored window by window and each category keeps its highest
    score, so content after the model's input limit is not lost (padding a document with public text
    no longer hides the rest). `windows=False` keeps the old behaviour: score the first window only.
    """
    chunks = word_windows(text, max_words)
    if not windows:
        chunks = chunks[:1]
    out = []
    for chunk in chunks:
        result = classifier(
            chunk,
            candidate_labels=CATEGORIES,
            hypothesis_template=HYPOTHESIS_TEMPLATE,
            multi_label=True,
        )
        out.append(dict(zip(result["labels"], result["scores"], strict=False)))
    return max_scores(out)


def remote_zero_shot(
    url: str, model_id: str, text: str, max_words: int, windows: bool = True, timeout: int = 600
) -> dict[str, float]:
    """Same as `zero_shot_classify`, but each window's forward pass runs on a remote NLI server
    (`research/nli_server.py`: ONNX Runtime on the host GPU). Windowing and max stay here."""
    import requests

    chunks = word_windows(text, max_words)
    if not windows:
        chunks = chunks[:1]
    out = []
    for chunk in chunks:
        payload = {"model": model_id, "text": chunk, "labels": CATEGORIES,
                   "template": HYPOTHESIS_TEMPLATE, "multi_label": True}  # fmt: skip
        r = requests.post(f"{url.rstrip('/')}/zero-shot", json=payload, timeout=timeout)
        if r.status_code != 200:
            raise RuntimeError(f"NLI server: {r.text[:300]}")
        out.append(r.json()["scores"])
    return max_scores(out)


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
