"""Prompt-injection detector scores for every attack variant text (CPU).

    python -m research.detect research/results/attacks/manifest.csv \
        --folders research/results/attacks/md research/results/attacks/docx research/results/attacks/pdf \
        --detectors pg2,protectai --out research/results/wp5_detect

The text is split into windows of at most 512 tokens (with overlap) and the highest malicious
score of any window is the score of the text. One row per file x view (full, visible) x detector;
the visible view only where it differs. Scores are cached per (text, detector), so a rerun
continues where it stopped. The flag (score >= --threshold) is the D4 gate: a flagged file goes
to RESTRICTED + needs review; the raw score allows TPR at a fixed FPR and ROC AUC later.
"""

from __future__ import annotations

import argparse
import csv
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.classifier_core.detector import DETECTORS, OVERLAP, WINDOW, Detector
from research.cache import Cache, cache_key
from research.manifest import now, write_manifest

FIELDS = ["file", "variant_id", "attack_id", "lang", "format", "view", "detector", "score",
          "flag", "n_windows", "chars", "latency_ms"]  # fmt: skip


def cached_score(cache: Cache, model_id: str, score: Callable[[str], tuple[float, int]],
                 text: str) -> dict[str, Any]:  # fmt: skip
    key = cache_key(text, "detector", model_id)
    hit = cache.get(key)
    if hit is not None:
        return hit
    t0 = time.perf_counter()
    s, n = score(text)
    value = {"score": s, "n_windows": n, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
    cache.put(key, value)
    return value


def main(argv: list[str] | None = None) -> None:
    from app.classifier_core.extract import get_views

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path, help="attack variant manifest.csv")
    p.add_argument("--folders", type=Path, nargs="+", required=True)
    p.add_argument("--detectors", default="pg2,protectai")
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--files", type=Path, help="text file with file names to run (a subset)")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    names = [d.strip() for d in args.detectors.split(",") if d.strip()]
    if unknown := set(names) - DETECTORS.keys():
        p.error(f"unknown detectors: {sorted(unknown)}; known: {sorted(DETECTORS)}")
    with args.manifest.open(encoding="utf-8", newline="") as f:
        variants = list(csv.DictReader(f))
    if args.files:
        wanted = set(args.files.read_text(encoding="utf-8").split())
        variants = [v for v in variants if v["file"] in wanted]
    where = {f.name: f for d in args.folders for f in d.iterdir()}
    missing = [v["file"] for v in variants if v["file"] not in where]
    if missing:
        raise SystemExit(f"{len(missing)} manifest files not in --folders, e.g. {missing[0]}")

    args.out.mkdir(parents=True, exist_ok=True)
    cache = Cache(args.out / "cache")
    manifest = dict(started=now(), detectors={n: DETECTORS[n][0] for n in names},
                    window=WINDOW, overlap=OVERLAP, threshold=args.threshold,
                    n_files=len(variants), manifest=str(args.manifest))  # fmt: skip
    write_manifest(args.out, status="running", **manifest)
    dets = {name: Detector(name) for name in names}
    rows = []
    for i, v in enumerate(variants, 1):
        views = get_views(where[v["file"]])
        texts = [("full", views.full)] + ([("visible", views.visible)]
                                          if views.visible != views.full else [])  # fmt: skip
        for (view, text), (name, det) in ((t, d) for t in texts for d in dets.items()):
            val = cached_score(cache, det.model_id, det.score, text)
            rows.append({k: v[k] for k in ("file", "variant_id", "attack_id", "lang", "format")}
                        | {"view": view, "detector": name, "score": round(val["score"], 6),
                           "flag": int(val["score"] >= args.threshold),
                           "n_windows": val["n_windows"], "chars": len(text),
                           "latency_ms": val["latency_ms"]})  # fmt: skip
        if i % 200 == 0:
            print(f"[{i}/{len(variants)}]", flush=True)
    with (args.out / "detector_scores.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    write_manifest(args.out, status="done", finished=now(), **manifest)
    print(f"wrote {args.out / 'detector_scores.csv'} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
