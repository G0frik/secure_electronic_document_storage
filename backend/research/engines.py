"""Classifier engines for the experiments.

Semantic layers (NLI, LLM: `app.classifier_core.llm`) and Presidio run separately; hybrids are built from
their outputs with `max_tier`, so every hybrid is free.
"""

from __future__ import annotations

from typing import Any

import requests

from app.classifier_core import presidio_layer, zero_shot
from app.classifier_core.llm import SemanticResult, _truncate
from app.classifier_core.tiers import Tier

# config_id -> (HF model id, max words fed to the model)
NLI_MODELS: dict[str, tuple[str, int]] = {
    "nli_en": (zero_shot.LARGE_MODEL, zero_shot.MAX_WORDS_DEBERTA),
    "nli_ml": (zero_shot.MULTILINGUAL_MODEL, zero_shot.MAX_WORDS_MULTILINGUAL),
    "nli_mdeberta": (
        "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7",
        zero_shot.MAX_WORDS_DEBERTA,
    ),
}


class NliEngine:
    """Zero-shot NLI as the service runs it. With `remote_url`, the forward pass runs on the host GPU
    (research/nli_server.py, ONNX Runtime + DirectML); truncation and the tier mapping stay here."""

    def __init__(self, config_id: str, remote_url: str = "") -> None:
        self.model_id, self.max_words = NLI_MODELS[config_id]
        self.remote_url = remote_url.rstrip("/")
        self._pipe: Any = None

    def server_info(self) -> dict[str, Any]:
        return requests.get(self.remote_url, timeout=10).json() if self.remote_url else {}

    def _remote_scores(self, text: str) -> dict[str, float]:
        payload = {"model": self.model_id, "text": text, "labels": zero_shot.CATEGORIES,
                   "template": zero_shot.HYPOTHESIS_TEMPLATE, "multi_label": True}  # fmt: skip
        r = requests.post(f"{self.remote_url}/zero-shot", json=payload, timeout=600)
        body = r.json()
        if r.status_code != 200:
            raise RuntimeError(body.get("error", r.text))
        return body["scores"]

    def classify(self, text: str) -> SemanticResult:
        clipped, truncated = _truncate(text, self.max_words)
        if self.remote_url:
            scores = self._remote_scores(clipped)
        else:
            if self._pipe is None:
                self._pipe = zero_shot.load_classifier(self.model_id)
            scores = zero_shot.zero_shot_classify(self._pipe, text, self.max_words)
        tier, triggered = zero_shot.zero_shot_tier(scores)
        return SemanticResult(
            tier=tier,
            categories=[zero_shot.short_name(c) for c, _, _ in triggered],
            raw={zero_shot.short_name(c): round(s, 4) for c, s in scores.items()},
            truncated=truncated,
        )


class PresidioEngine:
    def __init__(self) -> None:
        self._analyzer: Any = None

    def classify(self, text: str) -> tuple[Tier, list[str]]:
        if self._analyzer is None:
            self._analyzer = presidio_layer.build_analyzer()
        summary = presidio_layer.presidio_scan(self._analyzer, text)
        return presidio_layer.presidio_tier(summary), sorted(summary)
