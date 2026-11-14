"""Defense combinations built offline from stored predictions and detector scores (no GPU).

    python -m research.defend 'research/results/wp5_d2/*/predictions.csv' \
        --scores research/results/wp5_detect/detector_scores.csv --detector pg2 \
        --out research/results/wp5_defended/pg2.csv

For every input row it writes the row itself, the row without D2 (a D2 run stores the full-text
answer's cache entry, so "full only" needs no rerun) and each of those with D4: a detector flag on
any text the classifier saw sets final_tier to RESTRICTED and detector_flag to 1 (fail closed).
D3 is the `+presidio` config of each row. The `defenses` column names the set applied.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
from collections.abc import Callable, Iterable
from pathlib import Path

from app.classifier_core.tiers import max_tier
from research.classify_dir import FIELDS

Row = dict[str, str]


def _defenses(row: Row, add: str = "", drop: str = "") -> str:
    ds = {d for d in row["defenses"].split(",") if d} - {drop} | ({add} if add else set())
    return ",".join(sorted(ds))


def without_d2(row: Row, read_tier: Callable[[str], str]) -> Row:
    """The same row as if only the full text had been classified."""
    if not row["visible_ref"]:  # one view only: D2 changed nothing
        return row | {"defenses": _defenses(row, drop="D2")}
    tier = read_tier(row["raw_output_ref"])
    hybrid = row["config_id"].endswith("+presidio")
    final = max_tier(tier, row["presidio_tier"]).value if hybrid and tier else tier
    return row | {"defenses": _defenses(row, drop="D2"), "semantic_tier": tier,
                  "final_tier": final, "visible_ref": ""}  # fmt: skip


def with_d4(row: Row, flagged: set[str]) -> Row:
    flag = row["file"] in flagged
    final = "restricted" if flag else row["final_tier"]
    return row | {"defenses": _defenses(row, add="D4"), "final_tier": final,
                  "detector_flag": str(int(flag))}  # fmt: skip


def combine(rows: Iterable[Row], flagged: set[str], read_tier: Callable[[str], str]) -> list[Row]:
    out = []
    for r in rows:
        if r["error"]:
            raise SystemExit(f"error row {r['config_id']} {r['file']}: rerun the queue first")
        variants = [r] + ([without_d2(r, read_tier)] if "D2" in r["defenses"].split(",") else [])
        out += [x for v in variants for x in (v, with_d4(v, flagged))]
    return out


def flagged_files(scores: Path, detector: str, threshold: float) -> set[str]:
    """Files where any scored view reaches the threshold."""
    with scores.open(encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["detector"] == detector]
    if not rows:
        raise SystemExit(f"no scores for detector {detector} in {scores}")
    return {r["file"] for r in rows if float(r["score"]) >= threshold}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("predictions", nargs="+", help="predictions.csv paths or quoted glob patterns")
    p.add_argument(
        "--scores", type=Path, required=True, help="detector_scores.csv (research.detect)"
    )
    p.add_argument("--detector", default="pg2")
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--out", type=Path, required=True, help="output CSV")
    args = p.parse_args(argv)

    flagged = flagged_files(args.scores, args.detector, args.threshold)
    rows: list[Row] = []
    for pattern in args.predictions:
        for path in sorted(glob.glob(pattern)) or [pattern]:
            run_dir = Path(path).parent
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            # refs are relative to the cache folder's parent (classify_dir); older runs: run's parent
            base = Path(manifest["cache"]).parent if manifest.get("cache") else run_dir.parent

            def read_tier(ref: str, base: Path = base) -> str:
                return str(json.loads((base / ref).read_text(encoding="utf-8"))["tier"])

            with open(path, encoding="utf-8", newline="") as f:
                rows += combine(csv.DictReader(f), flagged, read_tier)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, restval="")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {args.out} ({len(rows)} rows, {len(flagged)} flagged files)")


if __name__ == "__main__":
    main()
