"""Defense effect and cost from research.defend outputs (CPU only).

    python -m research.analyze_defenses research/results/wp5_defended/*.csv \
        --manifest research/results/attacks/manifest.csv \
        --clean 'research/results/wp2/wp2_*/predictions.csv' 'research/results/wp2h/wp2h_*/predictions.csv' \
        --clean-scores research/results/wp5_detect_clean/detector_scores.csv \
        --out research/results/wp5_analysis/defenses

Defended files are named <detector>_<anything>.csv (research.defend writes one per detector). Each
row's config becomes `<config>@<defense set>` (`+presidio` stays last), with the detector named in
D4 sets, e.g. `llm:qwen35-9b@D2,D4(pg2)+presidio`; rows without D4 occur in every detector's
file and are kept once. Writes to <out>/summary/:
- asr.csv: research.analyze_attacks' table (ASR, robust accuracy, CIs) per config x defense set.
- clean_cost.csv: the attack set's clean variants (tiers above PUBLIC only) per config x defense
  set: research.analyze metrics (accuracy, under/over, macro-F1, latency p50/p95). A cached row
  keeps its first call's latency, so latency compares runs only roughly.
- d4_clean.csv: detector false-alarm rate on the clean corpus (all tiers, incl. PUBLIC) by tier and
  language, and every clean-run config's metrics without and with the D4 gate.
"""

from __future__ import annotations

import argparse
import csv
import glob
from collections import defaultdict
from pathlib import Path
from typing import Any

from research.analyze import _write, metrics, wilson
from research.analyze_attacks import asr_table

Row = dict[str, Any]
HYBRID = "+presidio"


def defense_label(defenses: str, detector: str) -> str:
    ds = [d for d in defenses.split(",") if d]
    return ",".join(f"D4({detector})" if d == "D4" else d for d in ds) or "none"


def keyed(config_id: str, label: str) -> str:
    base = config_id.removesuffix(HYBRID)
    return f"{base}@{label}" + (HYBRID if config_id.endswith(HYBRID) else "")


def load_defended(paths: list[Path], manifest: Path) -> list[Row]:
    with manifest.open(encoding="utf-8", newline="") as f:
        difficulty = {r["file"]: r["difficulty"] for r in csv.DictReader(f)}
    rows: dict[tuple[str, str], Row] = {}
    for path in paths:
        detector = path.stem.split("_")[0]
        with path.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                cid = keyed(r["config_id"], defense_label(r["defenses"], detector))
                rows.setdefault((cid, r["file"]), r | {"config_id": cid,
                                                       "difficulty": difficulty[r["file"]]})  # fmt: skip
    return list(rows.values())


def clean_cost(rows: list[Row]) -> list[dict[str, Any]]:
    by_cfg: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        if not r["attack_id"]:
            by_cfg[r["config_id"]].append(r)
    return [{"config": c} | metrics(rs) for c, rs in by_cfg.items()]


def _set(r: Row) -> str:
    """Corpus set of a clean run row: the run id's prefix (wp2 = base, wp2h = hard)."""
    return str(r["run_id"]).split("_")[0]


def d4_clean(clean_rows: list[Row], scores: Path, threshold: float) -> list[dict[str, Any]]:
    """False alarms on the clean corpus, and each config's clean metrics without / with D4."""
    flagged: dict[str, set[str]] = defaultdict(set)
    detectors: set[str] = set()
    with scores.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            detectors.add(r["detector"])
            if float(r["score"]) >= threshold:
                flagged[r["detector"]].add(r["file"])
    docs = {r["file"]: r for r in clean_rows}
    out: list[dict[str, Any]] = []
    for det in sorted(detectors):
        groups: dict[tuple[str, str], list[Row]] = defaultdict(list)
        for d in docs.values():
            groups[("all", "")].append(d)
            groups[("tier", d["true_tier"])].append(d)
            groups[("lang", d["lang"])].append(d)
            groups[("set", _set(d))].append(d)
        for (by, value), ds in sorted(groups.items()):
            k = sum(d["file"] in flagged[det] for d in ds)
            lo, hi = wilson(k, len(ds))
            out.append({"detector": det, "config": "", "gate": "", "by": by, "value": value,
                        "n": len(ds), "false_alarms": k, "rate": k / len(ds), "rate_lo": lo,
                        "rate_hi": hi})  # fmt: skip
    by_cfg: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for r in clean_rows:
        by_cfg[(_set(r), r["config_id"])].append(r)
    for (set_, cfg), rs in by_cfg.items():
        base = {"config": cfg, "by": "set", "value": set_}
        out.append({"detector": "", "gate": "none"} | base | metrics(rs))
        for det in sorted(detectors):
            gated = [r | {"final_tier": "restricted"} if r["file"] in flagged[det] else r
                     for r in rs]  # fmt: skip
            out.append({"detector": det, "gate": "D4"} | base | metrics(gated))
    return out


def _write_any(path: Path, rows: list[dict[str, Any]]) -> None:
    """_write with the union of keys as header (rows of different shapes in one file)."""
    keys = list(dict.fromkeys(k for r in rows for k in r))
    _write(path, [dict.fromkeys(keys, "") | r for r in rows])


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("defended", nargs="+", type=Path, help="research.defend output CSVs")
    p.add_argument("--manifest", type=Path, required=True, help="attack variant manifest.csv")
    p.add_argument("--clean", nargs="*", default=[], help="clean-run predictions.csv patterns")
    p.add_argument("--clean-scores", type=Path, help="detector_scores.csv of the clean corpus")
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    out = args.out / "summary"
    out.mkdir(parents=True, exist_ok=True)
    rows = load_defended(args.defended, args.manifest)
    _write(out / "asr.csv", asr_table(rows))
    _write(out / "clean_cost.csv", clean_cost(rows))
    if args.clean and args.clean_scores:
        clean_rows: list[Row] = []
        for pattern in args.clean:
            paths = sorted(glob.glob(pattern))
            if not paths:
                raise SystemExit(f"--clean pattern matches nothing: {pattern}")
            for path in paths:
                with open(path, encoding="utf-8", newline="") as f:
                    clean_rows += list(csv.DictReader(f))
        _write_any(out / "d4_clean.csv", d4_clean(clean_rows, args.clean_scores, args.threshold))
    print(f"wrote {out}/asr.csv, clean_cost.csv" + (", d4_clean.csv" if args.clean else ""))


if __name__ == "__main__":
    main()
