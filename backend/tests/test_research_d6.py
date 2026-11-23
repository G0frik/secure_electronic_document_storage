"""research.d6: D6 rows keep the semantic tier and take the folded Presidio tier."""

from __future__ import annotations

from research.d6 import d6_rows


def _row(config_id: str, semantic: str, presidio: str, defenses: str = "") -> dict[str, str]:
    return {"config_id": config_id, "semantic_tier": semantic, "presidio_tier": presidio,
            "final_tier": max(semantic, presidio), "defenses": defenses, "file": "a.md"}  # fmt: skip


def test_d6_rows_raise_only_through_presidio() -> None:
    rows = [
        _row("nli_en", "public", "public"),  # semantic config: not a D6 row
        _row("nli_en+presidio", "public", "public"),
        _row("nli_en+presidio", "public", "public", defenses="D2"),  # other defense set: skipped
        _row("llm:x+presidio", "restricted", "public"),
        _row("llm:y+presidio", "", "public"),  # invalid semantic answer stays invalid
    ]
    out = d6_rows(rows, {"a.md": ("confidential", True)})
    assert [(r["config_id"], r["final_tier"], r["defenses"]) for r in out] == [
        ("nli_en+presidio", "confidential", "D6"),
        ("llm:x+presidio", "restricted", "D6"),
        ("llm:y+presidio", "", "D6"),
    ]
