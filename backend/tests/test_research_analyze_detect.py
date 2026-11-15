"""Detector metrics: per-file max over views, 1%-FPR threshold, AUC, flag rates."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from research.analyze_detect import auc, detect_table, load, threshold_at_fpr

MANIFEST = ["variant_id", "pair_id", "lang", "tier", "group", "difficulty", "attack_id",
            "carrier", "placement", "payload_lang", "format", "file"]  # fmt: skip


def test_threshold_flags_at_most_one_percent_of_negatives() -> None:
    neg = np.array([0.0] * 197 + [0.5, 0.9, 0.95])  # 200 clean files: 1% = 2 may be flagged
    t = threshold_at_fpr(neg)
    assert (neg >= t).sum() == 2
    assert 0.5 < t <= 0.9


def test_threshold_with_ties_never_exceeds_the_budget() -> None:
    neg = np.array([0.1] * 98 + [0.7, 0.7])  # 1% of 100 = 1, but the top two tie
    assert (neg >= threshold_at_fpr(neg)).sum() == 0


def test_auc_perfect_random_and_ties() -> None:
    assert auc(np.array([0.9, 0.8]), np.array([0.1, 0.2])) == 1.0
    assert auc(np.array([0.1]), np.array([0.9])) == 0.0
    assert auc(np.array([0.5]), np.array([0.5])) == 0.5


def _manifest_row(file: str, pair: str, attack: str, fmt: str = "md", **kw: str) -> dict[str, str]:
    row = dict.fromkeys(MANIFEST, "") | {"file": file, "pair_id": pair, "lang": "en",
                                          "attack_id": attack, "format": fmt, "group": "id"}  # fmt: skip
    return row | kw


def test_load_takes_max_over_views_and_table_counts_flags(tmp_path: Path) -> None:
    manifest = [
        _manifest_row("c1", "d1", ""),
        _manifest_row("c2", "d2", ""),
        _manifest_row("a1", "d1", "A1"),
        _manifest_row("a2", "d2", "A1"),
        _manifest_row("h1", "d1", "A3/A1", fmt="docx", carrier="vanish"),
    ]
    scores = [  # (file, view, score)
        ("c1", "full", 0.1), ("c2", "full", 0.2), ("a1", "full", 0.9), ("a2", "full", 0.3),
        ("h1", "visible", 0.05), ("h1", "full", 0.8),  # flagged through the full view
    ]  # fmt: skip
    with (tmp_path / "m.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST)
        w.writeheader()
        w.writerows(manifest)
    with (tmp_path / "s.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "view", "detector", "score"])
        w.writerows((file, view, "pg2", s) for file, view, s in scores)

    by_det = load(tmp_path / "s.csv", tmp_path / "m.csv")
    assert {r["file"]: r["score"] for r in by_det["pg2"]}["h1"] == 0.8
    table = {(t["attack_id"], t["by"], t["value"]): t for t in detect_table(by_det, 0.5)}
    assert table[("clean", "all", "")]["k"] == 0
    a1 = table[("A1", "all", "")]
    assert (a1["n"], a1["k"], a1["rate"]) == (2, 1, 0.5)
    assert a1["auc"] == 0.75  # 0.9 beats both clean, 0.3 beats one
    assert table[("A3/A1", "carrier", "vanish")]["k"] == 1
    assert table[("A3/A1", "all", "")]["n_neg"] == 0  # no clean docx scored
