"""Defense analysis: config keys per defense set, de-duplication across detector files, D4 gate."""

from __future__ import annotations

import csv
from pathlib import Path

from research.analyze_defenses import d4_clean, defense_label, keyed, load_defended

COLS = ["config_id", "defenses", "file", "attack_id", "pair_id", "lang", "format", "true_tier",
        "final_tier"]  # fmt: skip


def test_keys_name_the_defense_set_and_keep_the_hybrid_suffix() -> None:
    assert defense_label("", "pg2") == "none"
    assert defense_label("D2,D4", "pg2") == "D2,D4(pg2)"
    assert keyed("llm:q+presidio", "D2") == "llm:q@D2+presidio"
    assert keyed("nli_en", "none") == "nli_en@none"


def _csv(path: Path, cols: list[str], rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return path


def test_rows_without_d4_are_kept_once_d4_rows_per_detector(tmp_path: Path) -> None:
    def row(defenses: str, final: str) -> dict[str, str]:
        return {"config_id": "llm:q", "defenses": defenses, "file": "f1", "attack_id": "A1",
                "pair_id": "d1", "lang": "en", "format": "md", "true_tier": "restricted",
                "final_tier": final}  # fmt: skip

    manifest = _csv(
        tmp_path / "m.csv", ["file", "difficulty"], [{"file": "f1", "difficulty": "base"}]
    )
    pg2 = _csv(tmp_path / "pg2_d2.csv", COLS, [row("", "public"), row("D4", "public")])
    pai = _csv(tmp_path / "protectai_d2.csv", COLS, [row("", "public"), row("D4", "restricted")])
    rows = {r["config_id"]: r["final_tier"] for r in load_defended([pg2, pai], manifest)}
    assert rows == {"llm:q@none": "public", "llm:q@D4(pg2)": "public",
                    "llm:q@D4(protectai)": "restricted"}  # fmt: skip


def test_d4_gate_turns_flagged_clean_docs_restricted(tmp_path: Path) -> None:
    clean = [
        {"run_id": "wp2_x", "config_id": "c", "file": "pub.md", "lang": "uk", "true_tier": "public",
         "final_tier": "public", "latency_ms": "1"},
        {"run_id": "wp2_x", "config_id": "c", "file": "int.md", "lang": "en",
         "true_tier": "internal", "final_tier": "internal", "latency_ms": "1"},
    ]  # fmt: skip
    scores = _csv(tmp_path / "s.csv", ["file", "detector", "score"],
                  [{"file": "pub.md", "detector": "protectai", "score": "0.9"},
                   {"file": "int.md", "detector": "protectai", "score": "0.1"}])  # fmt: skip
    out = d4_clean(clean, scores, 0.5)
    alarms = {(r["by"], r["value"]): r["rate"] for r in out if r["config"] == ""}
    assert alarms[("all", "")] == 0.5 and alarms[("tier", "public")] == 1.0
    gated = {r["gate"]: r for r in out if r["config"] == "c"}
    assert (gated["none"]["acc"], gated["D4"]["acc"]) == (1.0, 0.5)
    assert gated["D4"]["over"] == 0.5
