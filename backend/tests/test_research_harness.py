"""Research harness: cache keys and LLM answer validation."""

from __future__ import annotations

import pytest

from app.classifier_core.tiers import Tier
from research.cache import Cache, cache_key
from research.engines import parse_llm_output


def test_cache_key_changes_with_every_component() -> None:
    base = cache_key("doc", "llm", "gemma@abc", "classify_v1")
    assert base == cache_key("doc", "llm", "gemma@abc", "classify_v1")
    assert base != cache_key("doc!", "llm", "gemma@abc", "classify_v1")
    assert base != cache_key("doc", "nli_en", "gemma@abc", "classify_v1")
    assert base != cache_key("doc", "llm", "gemma@abd", "classify_v1")
    assert base != cache_key("doc", "llm", "gemma@abc", "classify_hardened_v1")


def test_cache_roundtrip(tmp_path) -> None:
    cache = Cache(tmp_path)
    assert cache.get("ab12") is None
    cache.put("ab12", {"tier": "public", "raw": "Гриф"})
    assert cache.get("ab12") == {"tier": "public", "raw": "Гриф"}


def test_parse_llm_output_valid_and_filters_unknown_categories() -> None:
    tier, cats = parse_llm_output(
        '{"tier": "Restricted", "categories": ["medical records", "made up"]}'
    )
    assert tier is Tier.RESTRICTED
    assert cats == ["medical records"]


@pytest.mark.parametrize("raw", ["", "not json", "[]", '{"categories": []}', '{"tier": "secret"}'])
def test_parse_llm_output_rejects_off_schema(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_llm_output(raw)


def test_llm_request_version_default_unchanged_and_thinking_separate() -> None:
    import hashlib
    import json

    from research.engines import LLM_MAX_TOKENS, LLM_SCHEMA, LlmEngine

    def rv(**kw: object) -> str:
        return LlmEngine("http://x", "m", "classify_v1", 42, **kw).request_version  # type: ignore[arg-type]

    # default runs must keep the cache keys they had before these options existed
    old = hashlib.sha256(
        json.dumps([LLM_SCHEMA, LLM_MAX_TOKENS], sort_keys=True).encode()
    ).hexdigest()[:8]
    assert rv() == old
    assert rv(template_kwargs={"enable_thinking": False}) == old
    assert rv(template_kwargs={"enable_thinking": True}) != old
    assert rv(max_tokens=4096) != old
