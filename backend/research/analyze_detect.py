"""Injection-detector (D4) metrics from research.detect scores.

    python -m research.analyze_detect research/results/wp5_detect/detector_scores.csv \
        --manifest research/results/attacks/manifest.csv --out research/results/wp5_analysis/detect

A file's score is the max over its scored views (the D4 gate in research.defend flags a file when
any view reaches the threshold). Negatives are the clean variants (every document in md/docx/pdf).
Per detector x attack (clean included) x breakdown:
- rate: share flagged at --threshold: detection rate for attacks, false-alarm rate for clean.
  Wilson 95% CI and a cluster bootstrap by source document (`*_lo_doc`, `*_hi_doc`).
- tpr_1fpr: share flagged at thr_1fpr, the lowest threshold that flags at most 1% of all clean
  files (one threshold per detector, as a deployed gate would use).
- auc: ROC AUC against the clean files of the same languages and formats as the group
  (probability that an attacked file outscores a clean one, ties count half).
Writes <out>/summary/detect.csv.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from research.analyze import _write, wilson
from research.analyze_attacks import doc_ci

Row = dict[str, Any]

BREAKDOWNS = ("lang", "format", "carrier", "payload_lang", "group")
CLEAN = "clean"


def load(scores: Path, manifest: Path) -> dict[str, list[Row]]:
    """Per detector: one row per file with the manifest columns and the max score over views."""
    with manifest.open(encoding="utf-8", newline="") as f:
        meta = {r["file"]: r for r in csv.DictReader(f)}
    best: dict[tuple[str, str], float] = {}
    with scores.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            key = (r["detector"], r["file"])
            best[key] = max(best.get(key, 0.0), float(r["score"]))
    out: dict[str, list[Row]] = defaultdict(list)
    for (det, file), score in best.items():
        m = meta[file]
        out[det].append(m | {"attack_id": m["attack_id"] or CLEAN, "score": score})
    return out


def threshold_at_fpr(neg: np.ndarray, fpr: float = 0.01) -> float:
    """Lowest threshold t with share(neg >= t) <= fpr (flag means score >= t)."""
    s = np.sort(neg)[::-1]
    k = int(np.floor(fpr * len(s)))  # at most k negatives may be flagged
    return float(np.nextafter(s[k], np.inf)) if k < len(s) else float(s[-1])


def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    if not len(pos) or not len(neg):
        return float("nan")
    gt = (pos[:, None] > neg[None, :]).mean()
    eq = (pos[:, None] == neg[None, :]).mean()
    return float(gt + eq / 2)


def metrics(rows: list[Row], clean: list[Row], thr: float, thr_1fpr: float,
            rng: np.random.Generator) -> dict[str, Any]:  # fmt: skip
    n = len(rows)
    k = sum(r["score"] >= thr for r in rows)
    lo, hi = wilson(k, n)
    lo_doc, hi_doc = doc_ci(rows, lambda r: r["score"] >= thr, rng)
    k1 = sum(r["score"] >= thr_1fpr for r in rows)
    langs, fmts = {r["lang"] for r in rows}, {r["format"] for r in rows}
    neg = np.array([c["score"] for c in clean if c["lang"] in langs and c["format"] in fmts])
    out: dict[str, Any] = {"n": n, "k": k, "rate": k / n if n else 0.0, "rate_lo": lo,
                           "rate_hi": hi, "rate_lo_doc": lo_doc, "rate_hi_doc": hi_doc,
                           "thr_1fpr": thr_1fpr, "k_1fpr": k1, "tpr_1fpr": k1 / n if n else 0.0}  # fmt: skip
    is_clean = rows[0]["attack_id"] == CLEAN
    out["auc"] = float("nan") if is_clean else auc(np.array([r["score"] for r in rows]), neg)
    out["n_neg"] = 0 if is_clean else len(neg)
    return out


def detect_table(by_det: dict[str, list[Row]], thr: float) -> list[dict[str, Any]]:
    table = []
    rng = np.random.default_rng(0)  # one seeded stream in a fixed key order: reproducible CIs
    for det in sorted(by_det):
        rows = by_det[det]
        clean = [r for r in rows if r["attack_id"] == CLEAN]
        if not clean:
            raise SystemExit(f"no clean files scored for {det}")
        thr_1fpr = threshold_at_fpr(np.array([r["score"] for r in clean]))
        groups: dict[tuple[str, str, str], list[Row]] = defaultdict(list)
        for r in rows:
            groups[(r["attack_id"], "all", "")].append(r)
            for dim in BREAKDOWNS:
                if r[dim]:
                    groups[(r["attack_id"], dim, r[dim])].append(r)
        order = sorted(groups, key=lambda k: (k[0] != CLEAN, k[0], k[1] != "all", k[1], k[2]))
        for a, dim, v in order:
            table.append({"detector": det, "attack_id": a, "by": dim, "value": v}
                         | metrics(groups[(a, dim, v)], clean, thr, thr_1fpr, rng))  # fmt: skip
    return table


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("scores", type=Path, help="detector_scores.csv (research.detect)")
    p.add_argument("--manifest", type=Path, required=True, help="attack variant manifest.csv")
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    table = detect_table(load(args.scores, args.manifest), args.threshold)
    out = args.out / "summary"
    out.mkdir(parents=True, exist_ok=True)
    _write(out / "detect.csv", table)
    print(f"flag rate at {args.threshold} / TPR at 1% FPR / AUC -> {out / 'detect.csv'}")
    for t in table:
        if t["by"] == "all":
            print(f"{t['detector']:10} {t['attack_id']:6} n={t['n']:5} rate={t['rate']:6.1%} "
                  f"tpr1={t['tpr_1fpr']:6.1%} auc={t['auc']:.3f}")  # fmt: skip


if __name__ == "__main__":
    main()
