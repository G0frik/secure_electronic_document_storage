"""ASR pooled over several attack classes, with CIs by source document (for the bar figures).

    python -m research.analyze_pooled 'research/results/wp5/wp5_*/predictions.csv' \
        --manifest research/results/attacks/manifest.csv --out research/results/pooled/full
    python -m research.analyze_pooled research/results/wp5_defended/*.csv --defended \
        --manifest research/results/attacks/manifest.csv --out research/results/pooled/defenses

Same eligibility and success rule as research.analyze_attacks (clean twin correct, attacked tier
below the true tier). The pooled rate is sum(k) / sum(n) over the classes of a pool; `asr_lo_doc`
/ `asr_hi_doc` come from the cluster bootstrap by source document over the pooled variants, so
the many variants of one document are not counted as independent. Wilson CIs kept for reference.
`--defended` reads research.defend outputs (config ids become `<config>@<defense set>`).
Writes <out>/summary/pooled.csv (config x pool x {all, group}).
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from research.analyze import Row, _write, config_order, wilson
from research.analyze_attacks import _success, doc_ci, join, load
from research.analyze_defenses import load_defended

POOLS = [
    ["A1", "A2", "A3/A1", "A3/A2", "A4", "A5"],  # hybrid figure (H3)
    ["A3/A1", "A3/A2"],  # hidden carriers (defense figure)
    ["A1", "A2"],  # visible text (defense figure)
]


def pool_name(attacks: list[str]) -> str:
    return "+".join(attacks)


def pooled_table(rows: list[Row]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[Row]] = defaultdict(list)
    for r in join(rows):
        for attacks in POOLS:
            if r["attack_id"] in attacks:
                name = pool_name(attacks)
                groups[(r["config_id"], name, "all", "")].append(r)
                groups[(r["config_id"], name, "group", r["group"])].append(r)
    order = {c: i for i, c in enumerate(config_order(rows))}
    rng = np.random.default_rng(0)  # one seeded stream in a fixed key order: reproducible CIs
    out = []
    for key in sorted(groups, key=lambda k: (order[k[0]], k[1], k[2] != "all", k[3])):
        rs = groups[key]
        k, n = sum(map(_success, rs)), len(rs)
        lo, hi = wilson(k, n)
        lo_doc, hi_doc = doc_ci(rs, _success, rng)
        out.append({"config": key[0], "pool": key[1], "by": key[2], "value": key[3], "n": n,
                    "n_docs": len({r["pair_id"] for r in rs}), "k_asr": k, "asr": k / n,
                    "asr_lo": lo, "asr_hi": hi, "asr_lo_doc": lo_doc, "asr_hi_doc": hi_doc})  # fmt: skip
    return out


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("predictions", nargs="+", help="predictions.csv paths / globs, or defended CSVs")
    p.add_argument("--manifest", type=Path, required=True, help="attack variant manifest.csv")
    p.add_argument("--defended", action="store_true", help="inputs are research.defend outputs")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    if args.defended:
        rows = load_defended([Path(x) for x in args.predictions], args.manifest)
    else:
        rows = load(args.predictions, args.manifest)
    table = pooled_table(rows)
    out = args.out / "summary"
    out.mkdir(parents=True, exist_ok=True)
    _write(out / "pooled.csv", table)
    print(f"{len(table)} rows -> {out / 'pooled.csv'}")


if __name__ == "__main__":
    main()
