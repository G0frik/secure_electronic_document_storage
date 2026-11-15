"""LLM classifier client: an OpenAI-compatible llama.cpp `llama-server` with a JSON-schema answer.

Used by the service (CLASSIFIER_ENGINE=llm) and by the research harness. The schema, prompt files
and request are hashed into `request_version` there, so keep this code and the prompts stable.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from app.classifier_core import zero_shot
from app.classifier_core.tiers import Tier

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
    reasoning: str = ""  # LLM thinking text, when the model reasons before answering


def _truncate(text: str, max_words: int) -> tuple[str, bool]:
    words = text.split()
    if len(words) <= max_words:
        return text, False
    return " ".join(words[:max_words]), True


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
        self,
        base_url: str,
        model: str,
        prompt_version: str,
        seed: int,
        timeout: int = 600,
        template_kwargs: dict[str, Any] | None = None,
        max_tokens: int = LLM_MAX_TOKENS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.prompt_version = prompt_version
        self.prompt = (PROMPTS_DIR / f"{prompt_version}.txt").read_text(encoding="utf-8")
        self.seed = seed
        self.timeout = timeout
        # Qwen3.5 thinks by default in some builds; other templates ignore this.
        self.template_kwargs = template_kwargs or {"enable_thinking": False}
        self.max_tokens = max_tokens
        # Part of the cache key: changing the request must not reuse old answers. Non-default
        # template kwargs / token caps are appended only, so default runs keep their old keys.
        parts: list[Any] = [LLM_SCHEMA, max_tokens]
        if self.template_kwargs != {"enable_thinking": False}:
            parts.append(self.template_kwargs)
        self.request_version = hashlib.sha256(
            json.dumps(parts, sort_keys=True).encode()
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
        if "<document>" in self.prompt:  # D1: the document cannot close its own delimiter
            doc = re.sub(r"<(/?)document>", r"&lt;\1document&gt;", doc, flags=re.IGNORECASE)
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": self.prompt.replace("{document}", doc)}],
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "seed": self.seed,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "classification", "schema": LLM_SCHEMA},
            },
            "chat_template_kwargs": self.template_kwargs,
        }
        resp = requests.post(
            f"{self.base_url}/v1/chat/completions", json=body, timeout=self.timeout
        )
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        raw = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or ""
        try:
            tier, cats = parse_llm_output(raw)
        except ValueError as exc:
            return SemanticResult(
                tier=None, raw=raw, truncated=truncated, error=str(exc), reasoning=reasoning
            )
        return SemanticResult(
            tier=tier, categories=cats, raw=raw, truncated=truncated, reasoning=reasoning
        )
