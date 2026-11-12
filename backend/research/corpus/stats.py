"""Print the corpus distribution from labels.csv: tier × group × lang, sources, lengths, review status.

python -m research.corpus.stats research/corpus/data/labels.csv
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

TIERS = ["public", "internal", "confidential", "restricted"]


def main() -> None:
    rows = list(csv.DictReader(Path(sys.argv[1]).open(encoding="utf-8")))
    pairs = {r["pair_id"] for r in rows}
    print(f"{len(pairs)} pairs, {len(rows)} documents\n")

    cells = Counter((r["tier"], r["group"], r["lang"]) for r in rows)
    print(f"{'tier':13} {'group':9} {'en':>3} {'uk':>3}")
    for t in TIERS:
        for g in ("id", "semantic"):
            if cells[(t, g, "en")] or cells[(t, g, "uk")]:
                print(f"{t:13} {g:9} {cells[(t, g, 'en')]:3} {cells[(t, g, 'uk')]:3}")

    print("\nsource (pairs)")
    for src, n in Counter(r["source"] for r in rows if r["lang"] == "en").most_common():
        print(f"  {n:3}  {src}")
    native = Counter(r["lang"] for r in rows if r["translation"] == "native")
    both = sum(
        1
        for p in pairs
        if sum(r["pair_id"] == p and r["translation"] == "native" for r in rows) == 2
    )
    print(
        f"\noriginal language: en {native['en'] - both}, uk {native['uk'] - both}, both native {both}"
    )
    print("folder (pairs):", dict(Counter(r["folder"] for r in rows if r["lang"] == "en")))

    words = [int(r["words"]) for r in rows]
    over = sum(w > 400 for w in words)
    print(
        f"\nwords: min {min(words)}, max {max(words)}, >400: {over}/{len(words)} ({over / len(words):.0%})"
    )
    reviewed = sum(r["reviewed"] == "1" for r in rows)
    print(f"reviewed: {reviewed}/{len(rows)}")


if __name__ == "__main__":
    main()
