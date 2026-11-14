"""Offline defense combinations: truth table for D2 removal, D3 and the D4 gate."""

from __future__ import annotations

import pytest

from research.defend import combine


def _row(cfg: str, sem: str, pres: str, final: str, defenses: str = "", vref: str = "") -> dict:  # type: ignore[type-arg]
    return {"config_id": cfg, "file": "f.docx", "defenses": defenses, "semantic_tier": sem,
            "presidio_tier": pres, "final_tier": final, "detector_flag": "", "error": "",
            "raw_output_ref": "cache/full.json", "visible_ref": vref}  # fmt: skip


def _by_def(rows: list[dict]) -> dict[str, dict]:  # type: ignore[type-arg]
    return {r["defenses"]: r for r in rows}


def test_d4_flag_forces_restricted_and_unflagged_keeps_the_tier() -> None:
    rows = combine([_row("llm:m", "public", "public", "public")], {"f.docx"}, lambda ref: "")
    out = _by_def(rows)
    assert (out[""]["final_tier"], out["D4"]["final_tier"], out["D4"]["detector_flag"]) == (
        "public",
        "restricted",
        "1",
    )
    rows = combine([_row("llm:m", "public", "public", "public")], set(), lambda ref: "")
    assert _by_def(rows)["D4"]["final_tier"] == "public"


def test_d2_row_also_yields_full_only_answer_from_the_cache() -> None:
    d2 = _row("llm:m+presidio", "restricted", "internal", "restricted", "D1,D2", "cache/vis.json")
    out = _by_def(combine([d2], set(), lambda ref: {"cache/full.json": "public"}[ref]))
    assert set(out) == {"D1,D2", "D1,D2,D4", "D1", "D1,D4"}
    # without D2 only the full text counts; D3 (+presidio) still lifts it to the Presidio tier
    assert (out["D1"]["semantic_tier"], out["D1"]["final_tier"]) == ("public", "internal")
    assert out["D1,D2"]["final_tier"] == "restricted"


def test_d2_single_view_row_needs_no_cache() -> None:
    out = _by_def(combine([_row("nli_en", "internal", "", "internal", "D2")], set(), None))  # type: ignore[arg-type]
    assert out[""]["final_tier"] == "internal"


def test_error_rows_stop_the_combiner() -> None:
    with pytest.raises(SystemExit):
        combine([_row("llm:m", "", "", "") | {"error": "engine exception: x"}], set(), str)
