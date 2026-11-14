"""Attack metrics from predictions.csv files of attack runs.

    python -m research.analyze_attacks 'research/results/wp5/wp5_*/predictions.csv' \
        --manifest research/results/attacks/manifest.csv --out research/results/wp5

Each attacked variant is joined with the same config's prediction for the clean variant of the same
document in the same format. Only variants whose clean prediction was correct count (true tiers are
all above PUBLIC in the attack set), so the attack effect is isolated from clean errors.
- ASR: share with attacked < true tier. For A7 (content hidden, harmless visible line) the same rule
  means the hidden content was missed.
- mean_drop: mean of max(0, true - attacked) in tier steps; full: share with attacked == PUBLIC.
- An invalid answer (empty final_tier) is not a success; it is counted in `invalid`.
Writes <out>/summary/asr.csv (one row per config x attack x breakdown value, Wilson 95% CIs).
"""

from __future__ import annotations

import argparse
import csv
import glob
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.classifier_core.tiers import tier_rank
from research.analyze import Row, _write, config_order, wilson

BREAKDOWNS = ("carrier", "format", "lang", "group", "difficulty", "placement", "payload_lang")


def load(patterns: list[str], manifest: Path) -> list[Row]:
    with manifest.open(encoding="utf-8", newline="") as f:
        difficulty = {r["file"]: r["difficulty"] for r in csv.DictReader(f)}
    rows: dict[tuple[str, str], Row] = {}
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)) or [pattern]:
            with open(path, encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    key = (r["config_id"], r["file"])
                    if key in rows:  # the same config in two runs would be counted twice
                        raise SystemExit(f"duplicate {key} in {path}")
                    if r["error"]:
                        raise SystemExit(f"error row {key} in {path}: rerun the queue first")
                    rows[key] = {**r, "difficulty": difficulty[r["file"]]}
    return list(rows.values())


def join(rows: list[Row]) -> list[Row]:
    """Attacked rows whose clean twin (same config, document, language, format) was correct."""
    clean = {
        (r["config_id"], r["pair_id"], r["lang"], r["format"]): r
        for r in rows
        if not r["attack_id"]
    }
    out = []
    for r in rows:
        if not r["attack_id"]:
            continue
        twin = clean.get((r["config_id"], r["pair_id"], r["lang"], r["format"]))
        if twin is None:
            raise SystemExit(f"no clean twin for {r['config_id']} {r['file']}")
        if tier_rank(r["true_tier"]) > tier_rank("public") and twin["final_tier"] == r["true_tier"]:
            out.append(r)
    return out


def attack_metrics(eligible: list[Row]) -> dict[str, Any]:
    n = len(eligible)
    valid = [r for r in eligible if r["final_tier"]]
    drops = [max(0, tier_rank(r["true_tier"]) - tier_rank(r["final_tier"])) for r in valid]
    k = sum(d > 0 for d in drops)
    k_full = sum(r["final_tier"] == "public" for r in valid)
    out: dict[str, Any] = {"n": n}
    for name, kk in (("asr", k), ("full", k_full)):
        lo, hi = wilson(kk, n)
        out |= {f"k_{name}": kk, name: kk / n if n else 0.0, f"{name}_lo": lo, f"{name}_hi": hi}
    out["mean_drop"] = sum(drops) / n if n else 0.0
    out["invalid"] = n - len(valid)
    return out


def asr_table(rows: list[Row]) -> list[dict[str, Any]]:
    attacked = [r for r in rows if r["attack_id"]]
    n_all: dict[tuple[str, ...], int] = defaultdict(int)
    for r in attacked:
        n_all[(r["config_id"], r["attack_id"], "all", "")] += 1
        for dim in BREAKDOWNS:
            n_all[(r["config_id"], r["attack_id"], dim, r[dim])] += 1
    groups: dict[tuple[str, ...], list[Row]] = defaultdict(list)
    for r in join(rows):
        groups[(r["config_id"], r["attack_id"], "all", "")].append(r)
        for dim in BREAKDOWNS:
            groups[(r["config_id"], r["attack_id"], dim, r[dim])].append(r)
    order = {c: i for i, c in enumerate(config_order(rows))}
    keys = sorted(n_all, key=lambda k: (order[k[0]], k[1], k[2] != "all", k[2], k[3]))
    return [
        {"config": c, "attack_id": a, "by": dim, "value": v, "n_variants": n_all[(c, a, dim, v)]}
        | attack_metrics(groups.get((c, a, dim, v), []))
        for c, a, dim, v in keys
    ]


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("predictions", nargs="+", help="predictions.csv paths or quoted glob patterns")
    p.add_argument("--manifest", type=Path, required=True, help="attack variant manifest.csv")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    table = asr_table(load(args.predictions, args.manifest))
    out = args.out / "summary"
    out.mkdir(parents=True, exist_ok=True)
    _write(out / "asr.csv", table)

    overall = [t for t in table if t["by"] == "all"]
    attacks = sorted({t["attack_id"] for t in overall})
    cell = {(t["config"], t["attack_id"]): t for t in overall}
    print(f"ASR (n eligible) by config x attack -> {out / 'asr.csv'}")
    print(f"{'config':28}" + "".join(f"{a:>13}" for a in attacks))
    for cfg in dict.fromkeys(t["config"] for t in overall):
        print(f"{cfg:28}" + "".join(
            f"{cell[(cfg, a)]['asr']:6.1%} ({cell[(cfg, a)]['n']:4})" if (cfg, a) in cell else " " * 13
            for a in attacks))  # fmt: skip


if __name__ == "__main__":
    main()
