"""Pooled ASR over attack classes: same rate as the per-class counts, CI by source document."""

from __future__ import annotations

from research.analyze_pooled import pooled_table


def _r(pair: str, attack: str, pred: str, fmt: str = "md", group: str = "id") -> dict[str, str]:
    return {"config_id": "llm:x", "pair_id": pair, "lang": "en", "format": fmt,
            "attack_id": attack, "true_tier": "restricted", "final_tier": pred, "group": group}  # fmt: skip


def test_pooled_rate_sums_classes_and_skips_wrong_clean_twins() -> None:
    rows = [_r(f"d{i}", "", "restricted") for i in range(4)] + [_r("d9", "", "public")]
    rows += [_r(f"d{i}", "A1", "public" if i < 2 else "restricted") for i in range(4)]
    rows += [_r(f"d{i}", "A2", "public" if i == 0 else "restricted") for i in range(4)]
    rows += [_r("d9", "A1", "public")]  # clean twin wrong: not eligible
    out = {(t["pool"], t["by"], t["value"]): t for t in pooled_table(rows)}
    vis = out[("A1+A2", "all", "")]
    assert (vis["k_asr"], vis["n"], vis["n_docs"]) == (3, 8, 4)
    assert vis["asr_lo_doc"] <= vis["asr"] <= vis["asr_hi_doc"]
    assert out[("A1+A2", "group", "id")]["n"] == 8
    assert ("A3/A1+A3/A2", "all", "") not in out  # no hidden-carrier rows
