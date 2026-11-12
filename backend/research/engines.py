"""Classifier engines for the experiments.

Semantic layers (NLI, LLM) and Presidio run separately; hybrids are built from
their outputs with `max_tier`, so every hybrid is free.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from app.classifier_core import presidio_layer, zero_shot
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

CATEGORY_NAMES = [zero_shot.short_name(c) for c in zero_shot.CATEGORIES]
PROMPTS_DIR = Path(__file__).parent / "prompts"

# llama-server runs with -c 8192; Ukrainian is ~2 tokens/word, so 3000 words leaves room
# for the prompt and the answer.
LLM_MAX_WORDS = 3000
LLM_MAX_TOKENS = 256  # a valid answer is under 100 tokens

LLM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tier": {"type": "string", "enum": [t.value for t in Tier]},
        # maxItems stops repetition loops ("salary", "salary", ...) seen with MamayLM.
        "categories": {
            "type": "array",
            "items": {"type": "string", "enum": CATEGORY_NAMES},
            "maxItems": len(CATEGORY_NAMES),
        },
    },
    "required": ["tier", "categories"],
    "additionalProperties": False,
}


@dataclass
class SemanticResult:
    tier: Tier | None  # None when the engine produced no usable answer
    categories: list[str] = field(default_factory=list)
    raw: Any = None  # NLI: category scores; LLM: the raw completion text
    truncated: bool = False
    error: str = ""


def _truncate(text: str, max_words: int) -> tuple[str, bool]:
    words = text.split()
    if len(words) <= max_words:
        return text, False
    return " ".join(words[:max_words]), True


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


def parse_llm_output(raw: str) -> tuple[Tier, list[str]]:
    """Validate the model's JSON answer. Raises ValueError on anything off-schema."""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(obj, dict) or "tier" not in obj:
        raise ValueError("missing 'tier'")
    tier = Tier(str(obj["tier"]).strip().lower())  # ValueError on unknown tier
    cats = obj.get("categories") or []
    return tier, [c for c in cats if c in CATEGORY_NAMES]


class LlmEngine:
    """OpenAI-compatible client for llama.cpp `llama-server`."""

    def __init__(
        self, base_url: str, model: str, prompt_version: str, seed: int, timeout: int = 600
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.prompt_version = prompt_version
        self.prompt = (PROMPTS_DIR / f"{prompt_version}.txt").read_text(encoding="utf-8")
        self.seed = seed
        self.timeout = timeout
        # Part of the cache key: changing the schema or token cap must not reuse old answers.
        self.request_version = hashlib.sha256(
            json.dumps([LLM_SCHEMA, LLM_MAX_TOKENS], sort_keys=True).encode()
        ).hexdigest()[:8]

    def server_info(self) -> dict[str, Any]:
        """What llama-server reports about itself, for the manifest."""
        props = requests.get(f"{self.base_url}/props", timeout=10).json()
        gen = props.get("default_generation_settings", {})
        return {
            "model_path": props.get("model_path"),
            "build_info": props.get("build_info"),
            "n_ctx": gen.get("n_ctx", props.get("n_ctx")),
        }

    def classify(self, text: str) -> SemanticResult:
        doc, truncated = _truncate(text, LLM_MAX_WORDS)
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": self.prompt.replace("{document}", doc)}],
            "temperature": 0,
            "max_tokens": LLM_MAX_TOKENS,
            "seed": self.seed,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "classification", "schema": LLM_SCHEMA},
            },
            # Qwen3.5 thinks by default in some builds; other templates ignore this.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        resp = requests.post(
            f"{self.base_url}/v1/chat/completions", json=body, timeout=self.timeout
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"] or ""
        try:
            tier, cats = parse_llm_output(raw)
        except ValueError as exc:
            return SemanticResult(tier=None, raw=raw, truncated=truncated, error=str(exc))
        return SemanticResult(tier=tier, categories=cats, raw=raw, truncated=truncated)


class PresidioEngine:
    def __init__(self) -> None:
        self._analyzer: Any = None

    def classify(self, text: str) -> tuple[Tier, list[str]]:
        if self._analyzer is None:
            self._analyzer = presidio_layer.build_analyzer()
        summary = presidio_layer.presidio_scan(self._analyzer, text)
        return presidio_layer.presidio_tier(summary), sorted(summary)
