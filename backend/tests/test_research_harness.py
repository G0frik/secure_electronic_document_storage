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
