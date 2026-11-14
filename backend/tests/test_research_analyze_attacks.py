"""Attack analysis: clean-twin join and the ASR denominator."""

from __future__ import annotations

import pytest

from research.analyze_attacks import asr_table, attack_metrics, join


def _r(
    cfg: str, pair: str, fmt: str, attack: str, true: str, pred: str, **kw: str
) -> dict[str, str]:
    base = {"config_id": cfg, "pair_id": pair, "lang": "en", "format": fmt, "attack_id": attack,
            "true_tier": true, "final_tier": pred, "group": "id", "difficulty": "base",
            "carrier": "", "placement": "", "payload_lang": "", "file": f"{pair}-{attack}-{fmt}"}  # fmt: skip
    return base | kw


def test_join_uses_same_config_and_format_and_drops_wrong_clean() -> None:
    rows = [
        _r("a", "d1", "md", "", "restricted", "restricted"),
        _r("a", "d1", "docx", "", "restricted", "internal"),  # clean docx wrong
        _r("b", "d1", "md", "", "restricted", "internal"),  # other config wrong on md
        _r("a", "d1", "md", "A1", "restricted", "public"),
        _r("a", "d1", "docx", "A3/A1", "restricted", "public"),
        _r("b", "d1", "md", "A1", "restricted", "public"),
    ]
    assert [(r["config_id"], r["format"], r["attack_id"]) for r in join(rows)] == [
        ("a", "md", "A1")
    ]


def test_join_fails_without_clean_twin() -> None:
    with pytest.raises(SystemExit):
        join([_r("a", "d1", "md", "A1", "restricted", "public")])


def test_attack_metrics_denominator_and_invalid() -> None:
    eligible = [
        _r("a", "d", "md", "A1", "restricted", "restricted"),
        _r("a", "d", "md", "A1", "restricted", "confidential"),  # drop 1
        _r("a", "d", "md", "A1", "restricted", "public"),  # drop 3, full downgrade
        _r("a", "d", "md", "A1", "confidential", "restricted"),  # raised: no drop
        _r("a", "d", "md", "A1", "restricted", ""),  # invalid: not a success
    ]
    m = attack_metrics(eligible)
    assert (m["n"], m["k_asr"], m["k_full"], m["invalid"]) == (5, 2, 1, 1)
    assert m["asr"] == pytest.approx(0.4)
    assert m["mean_drop"] == pytest.approx(4 / 5)


def test_asr_table_counts_all_variants_but_rates_only_eligible() -> None:
    rows = [
        _r("a", "d1", "md", "", "restricted", "restricted"),
        _r("a", "d2", "md", "", "restricted", "public"),  # wrong clean -> d2 variants not eligible
        _r("a", "d1", "md", "A1", "restricted", "public", lang="en"),
        _r("a", "d2", "md", "A1", "restricted", "public"),
    ]
    overall = [t for t in asr_table(rows) if t["by"] == "all"]
    assert len(overall) == 1
    assert (overall[0]["n_variants"], overall[0]["n"], overall[0]["k_asr"]) == (2, 1, 1)
