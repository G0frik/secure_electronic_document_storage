"""Stratified sample of attack variants → a file list for `classify_dir --files`.

    python -m research.sample research/results/attacks/manifest.csv --target 200 --out pilot.txt

Every cell (attack_id, carrier, placement, format, payload_lang, lang, difficulty) gets the same number of
variants (at least one), drawn with a fixed seed; the clean variants of the sampled documents in the same
format are always added, because attack success is measured against them.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from collections import defaultdict
from pathlib import Path

CELL = ("attack_id", "carrier", "placement", "format", "payload_lang", "lang", "difficulty")


def sample(rows: list[dict[str, str]], target: int, seed: int = 20261113) -> list[str]:
    attacked = [r for r in rows if r["attack_id"]]
    cells: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for r in attacked:
        cells[tuple(r[k] for k in CELL)].append(r)
    per_cell = max(1, math.ceil(target / max(1, len(cells))))
    rng = random.Random(seed)  # noqa: S311 — reproducible sampling, not crypto
    picked = [
        r for key in sorted(cells) for r in rng.sample(cells[key], min(per_cell, len(cells[key])))
    ]
    clean = {(r["pair_id"], r["lang"], r["format"]): r["file"] for r in rows if not r["attack_id"]}
    files = {r["file"] for r in picked} | {clean[(r["pair_id"], r["lang"], r["format"])] for r in picked
                                            if (r["pair_id"], r["lang"], r["format"]) in clean}  # fmt: skip
    return sorted(files)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path)
    p.add_argument(
        "--target", type=int, required=True, help="approximate number of attack variants"
    )
    p.add_argument("--seed", type=int, default=20261113)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    with args.manifest.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    files = sample(rows, args.target, args.seed)
    args.out.write_text("\n".join(files) + "\n", encoding="utf-8")
    print(f"{len(files)} files (attack variants + their clean twins) → {args.out}")


if __name__ == "__main__":
    main()
