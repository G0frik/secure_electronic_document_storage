"""D6 offline: rescan the files of existing runs with Presidio on both views (CPU only, no GPU).

    python -m research.d6 'research/results/wp5/wp5_*/predictions.csv' \
        --folders research/results/attacks/md research/results/attacks/docx research/results/attacks/pdf \
        --out research/results/wp5_d6/attacks

For every `+presidio` row without defenses, the file is scanned once with
`presidio_layer.presidio_scan_folded` (look-alike characters and separators folded back, escalation
when obfuscation sits inside a PII span); the row is written again with the new presidio_tier,
final_tier = max(semantic_tier, new presidio tier) and defenses `D6`. The semantic layer is not
rerun: it reads the original text, as in the service. Writes <out>/predictions.csv (input for
research.analyze_attacks / research.analyze) and <out>/scans.csv (per file: Presidio tier without
and with D6, whether evasion was found), used to count false alarms on clean documents.
"""

from __future__ import annotations

import argparse
import csv
import glob
from pathlib import Path

from app.classifier_core import presidio_layer
from app.classifier_core.extract import get_text
from app.classifier_core.tiers import max_tier
from research.classify_dir import FIELDS


def d6_rows(rows: list[dict[str, str]], scan: dict[str, tuple[str, bool]]) -> list[dict[str, str]]:
    """The `+presidio` rows again with the D6 Presidio tier (scan: file -> (tier, evasion))."""
    out = []
    for r in rows:
        if not r["config_id"].endswith("+presidio") or r["defenses"] or r["file"] not in scan:
            continue
        p_tier = scan[r["file"]][0]
        final = max_tier(r["semantic_tier"], p_tier).value if r["semantic_tier"] else ""
        out.append(r | {"presidio_tier": p_tier, "final_tier": final, "defenses": "D6"})
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("predictions", nargs="+", help="predictions.csv paths or quoted glob patterns")
    p.add_argument("--folders", type=Path, nargs="+", required=True, help="where the run's files are")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    rows = [r for pat in args.predictions for f in sorted(glob.glob(pat))
            for r in csv.DictReader(open(f, encoding="utf-8"))]  # fmt: skip
    paths = {f.name: f for d in args.folders for f in d.rglob("*") if f.is_file()}
    names = sorted({r["file"] for r in rows if r["config_id"].endswith("+presidio")})
    missing = [n for n in names if n not in paths]
    if missing:
        raise SystemExit(f"{len(missing)} files not found under --folders, e.g. {missing[:3]}")

    args.out.mkdir(parents=True, exist_ok=True)
    scans_csv = args.out / "scans.csv"
    scan: dict[str, tuple[str, bool]] = {}
    if scans_csv.exists():  # a rerun (e.g. with one more run's predictions) reuses earlier scans
        scan = {r["file"]: (r["presidio_tier_d6"], r["evasion"] == "1")
                for r in csv.DictReader(open(scans_csv, encoding="utf-8"))}  # fmt: skip
    todo = [n for n in names if n not in scan]
    analyzer = presidio_layer.build_analyzer() if todo else None
    with scans_csv.open("a" if scan else "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not scan:
            w.writerow(["file", "presidio_tier", "presidio_tier_d6", "evasion"])
        for i, name in enumerate(todo, 1):
            text = get_text(paths[name])
            old = presidio_layer.presidio_tier(presidio_layer.presidio_scan(analyzer, text)).value
            _, tier, evasion = presidio_layer.presidio_scan_folded(analyzer, text)
            scan[name] = (tier.value, evasion)
            w.writerow([name, old, tier.value, int(evasion)])
            if i % 200 == 0:
                print(f"{i}/{len(todo)} files", flush=True)

    out_rows = d6_rows(rows, scan)
    with (args.out / "predictions.csv").open("w", newline="", encoding="utf-8") as f:
        w2 = csv.DictWriter(f, fieldnames=FIELDS)
        w2.writeheader()
        w2.writerows(out_rows)
    print(f"{len(todo)} files scanned ({len(names) - len(todo)} reused), {len(out_rows)} D6 rows -> {args.out}")


if __name__ == "__main__":
    main()
