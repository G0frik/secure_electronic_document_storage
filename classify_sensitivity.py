#!/usr/bin/env python3
"""Document Sensitivity Classifier v6 — CLI wrapper.

The actual pipeline lives in `backend/app/classifier_core/`. This file is
a thin CLI front-end that drives the library on individual files or
directories — useful for checking how a document would be tiered without
running the whole stack.

USAGE
-----
    python classify_sensitivity.py path/to/file_or_dir
    python classify_sensitivity.py path/ --multilingual
    python classify_sensitivity.py path/ --no-presidio
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the backend library importable when running from the repo root.
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from app.classifier_core import EXTRACTORS, get_text  # noqa: E402
from app.classifier_core import pipeline as _pipeline  # noqa: E402
from app.classifier_core import presidio_layer as _pl  # noqa: E402
from app.classifier_core import zero_shot as _zs  # noqa: E402
from app.classifier_core.extract import UnsupportedExtensionError  # noqa: E402
from app.classifier_core.tiers import TIER_RANK, Tier  # noqa: E402


def _print_result(path: Path, text: str, result) -> None:  # type: ignore[no-untyped-def]
    print(f"\n=== {path.name} ===")
    if not text.strip():
        print("  (no text extracted)")
        return

    print(f"  FINAL TIER: {result.final_tier.value.upper()}")
    print(f"    zero-shot tier  : {result.zero_shot_tier.value}")
    print(f"    presidio tier   : {result.presidio_tier.value}")

    if result.presidio_entities:
        print("\n  Presidio findings:")
        items = sorted(
            result.presidio_entities.items(),
            key=lambda kv: (
                TIER_RANK.get(_pl.ENTITY_TO_TIER.get(kv[0], Tier.PUBLIC), 0),
                kv[1]["count"],
            ),
            reverse=True,
        )
        for ent, info in items:
            implied = _pl.ENTITY_TO_TIER.get(ent, Tier.PUBLIC)
            samples = ", ".join(info.get("samples", []))
            print(
                f"    [{implied.value:12s}] {ent:18s} x{info['count']:<3d}"
                f"  (max conf {info['max_score']:.0%})  e.g. {samples}"
            )

    print("\n  Zero-shot categories triggered:")
    if result.categories_triggered:
        for cat in result.categories_triggered:
            print(f"    - {cat}")
    else:
        print("    (none triggered)")

    print("\n  All zero-shot scores:")
    for cat, score in sorted(result.raw_scores.items(), key=lambda x: -x[1]):
        bar = "#" * int(score * 30)
        print(f"    {score:6.1%}  {cat:55s} {bar}")

    print(f"\n  Snippet: {' '.join(text.split()[:25])}...")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="File or directory to classify")
    parser.add_argument(
        "--large",
        action="store_true",
        help="Use deberta-v3-large (English-only). Mutually exclusive with --multilingual.",
    )
    parser.add_argument(
        "--multilingual",
        action="store_true",
        help="Use bge-m3 (XLM-RoBERTa, 8k context) instead of DeBERTa-v3 base.",
    )
    parser.add_argument(
        "--no-presidio",
        action="store_true",
        help="Skip the Presidio layer (zero-shot only).",
    )
    args = parser.parse_args()

    if args.large and args.multilingual:
        parser.error("--large and --multilingual are mutually exclusive; pick one.")

    from app.config import settings

    if args.large:
        settings.classifier_model = "large"
    elif args.multilingual:
        settings.classifier_model = "multilingual"
    else:
        settings.classifier_model = "base"

    settings.classifier_disable_presidio = args.no_presidio
    _pipeline.reset_classifier_cache()

    target = Path(args.path)
    if not target.exists():
        print(f"path not found: {target}", file=sys.stderr)
        return 1

    files = (
        [target]
        if target.is_file()
        else sorted(
            p for p in target.rglob("*") if p.is_file() and p.suffix.lower() in EXTRACTORS
        )
    )
    if not files:
        print(f"no supported files in {target}", file=sys.stderr)
        return 1

    model_id, max_words = _zs.select_model(settings.classifier_model)
    print(f"Loading zero-shot model: {model_id}  (MAX_WORDS={max_words})")
    if not args.no_presidio:
        print("Loading Presidio analyzer (with custom recognizers)...")

    for f in files:
        try:
            text = get_text(f)
            result = _pipeline.classify(text)
            _print_result(f, text, result)
        except (UnsupportedExtensionError, Exception) as e:  # noqa: BLE001
            print(f"\n=== {f.name} ===\n  ERROR: {e}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
