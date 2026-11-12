"""Classify every supported file in a folder → predictions.csv + manifest.json.

    python -m research.classify_dir <folder> --configs nli_en,nli_ml,llm \
        [--labels labels.csv] [--llm-label gemma4-12b --gguf <file>.gguf]

Each semantic config yields two rows per file: `<config>` (semantic layer only) and
`<config>+presidio` (hybrid via max_tier). Engine outputs are cached.
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.classifier_core.extract import EXTRACTORS, get_text
from app.classifier_core.tiers import max_tier, tier_rank
from research.cache import Cache, cache_key
from research.engines import (
    LLM_MAX_TOKENS,
    LLM_MAX_WORDS,
    NLI_MODELS,
    LlmEngine,
    NliEngine,
    PresidioEngine,
    SemanticResult,
)
from research.manifest import now, sha256_file, write_manifest

RESEARCH_DIR = Path(__file__).parent
FIELDS = [
    "run_id", "pair_id", "lang", "true_tier", "group", "variant_id", "attack_id", "carrier",
    "placement", "payload_lang", "format", "config_id", "semantic_engine", "defenses",
    "semantic_tier", "presidio_tier", "final_tier", "detector_flag", "latency_ms",
    "input_chars", "truncated", "raw_output_ref", "error", "file",
]  # fmt: skip


def _load_labels(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {row["file"]: row for row in csv.DictReader(f)}


def _cached(cache: Cache, key: str, fn: Any) -> tuple[dict[str, Any], bool]:
    """Return (cached-or-fresh value, was_cached). `fn` returns a JSON-able dict."""
    hit = cache.get(key)
    if hit is not None:
        return hit, True
    t0 = time.perf_counter()
    value = fn()
    value["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    cache.put(key, value)
    return value, False


def _presidio(engine: PresidioEngine, text: str) -> dict[str, Any]:
    tier, entities = engine.classify(text)
    return {"tier": tier.value, "entities": entities}


def _semantic_to_dict(r: SemanticResult) -> dict[str, Any]:
    return {
        "tier": r.tier.value if r.tier else "",
        "categories": r.categories,
        "raw": r.raw,
        "truncated": r.truncated,
        "error": r.error,
    }


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder", type=Path)
    p.add_argument("--configs", default="nli_en,nli_ml,llm")
    p.add_argument("--labels", type=Path, help="CSV with columns file,pair_id,lang,tier,group")
    p.add_argument("--llm-url", default=os.environ.get("LLM_BASE_URL", "http://host.docker.internal:8080"))
    p.add_argument("--llm-label", default="llm", help="short model name used in config_id")
    # A bare file name, not a path: Git Bash rewrites "/models/..." args into Windows paths.
    p.add_argument("--gguf", help="GGUF file name in $GGUF_DIR (default /models); hashed into the manifest")
    p.add_argument("--prompt", default="classify_v1")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--run-id")
    p.add_argument("--out", type=Path, default=RESEARCH_DIR / "results")
    args = p.parse_args(argv)

    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    unknown = [c for c in configs if c != "llm" and c not in NLI_MODELS]
    if unknown:
        p.error(f"unknown configs: {unknown}; known: llm, {', '.join(NLI_MODELS)}")

    started = now()
    run_id = args.run_id or f"{started[:19].replace(':', '').replace('-', '')}_{'-'.join(configs)}"
    run_dir = args.out / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    cache = Cache(args.out / "cache")
    labels = _load_labels(args.labels)

    engines: dict[str, tuple[str, Any]] = {}  # config_id -> (model id, engine)
    llm_info: dict[str, Any] = {}
    for c in configs:
        if c == "llm":
            gguf_dir = Path(os.environ.get("GGUF_DIR", "/models"))
            gguf_sha = sha256_file(gguf_dir / args.gguf) if args.gguf else ""
            model = f"{args.llm_label}@{gguf_sha[:12]}" if gguf_sha else args.llm_label
            eng = LlmEngine(args.llm_url, args.llm_label, args.prompt, args.seed)
            llm_info = {"label": args.llm_label, "gguf": str(args.gguf or ""),
                        "gguf_sha256": gguf_sha, "server": eng.server_info(),
                        "max_words": LLM_MAX_WORDS, "max_tokens": LLM_MAX_TOKENS,
                        "request_version": eng.request_version}  # fmt: skip
            engines[f"llm:{args.llm_label}"] = (model, eng)
        else:
            engines[c] = (NLI_MODELS[c][0], NliEngine(c))
    presidio = PresidioEngine()

    files = sorted(f for f in args.folder.iterdir() if f.suffix.lower() in EXTRACTORS)
    rows: list[dict[str, Any]] = []
    for i, path in enumerate(files, 1):
        text = get_text(path)
        lab = labels.get(path.name, {})
        p_val, _ = _cached(cache, cache_key(text, "presidio", "v6"), lambda t=text: _presidio(presidio, t))
        for config_id, (model, eng) in engines.items():
            prompt_v = f"{args.prompt}@{eng.request_version}" if config_id.startswith("llm") else ""
            key = cache_key(text, config_id.split(":")[0], model, prompt_v)
            s_val, _ = _cached(cache, key, lambda e=eng, t=text: _semantic_to_dict(e.classify(t)))
            base = {
                "run_id": run_id, "pair_id": lab.get("pair_id", ""), "lang": lab.get("lang", ""),
                "true_tier": lab.get("tier", ""), "group": lab.get("group", ""),
                "variant_id": "clean", "format": path.suffix.lstrip(".").lower(),
                "semantic_engine": model, "defenses": "", "semantic_tier": s_val["tier"],
                "presidio_tier": p_val["tier"], "detector_flag": "",
                "latency_ms": s_val["latency_ms"], "input_chars": len(text),
                "truncated": int(s_val["truncated"]),
                "raw_output_ref": str(cache.path(key).relative_to(args.out)),
                "error": s_val["error"], "file": path.name,
            }  # fmt: skip
            rows.append({**base, "config_id": config_id, "final_tier": s_val["tier"]})
            hybrid = max_tier(s_val["tier"], p_val["tier"]).value if s_val["tier"] else ""
            rows.append({**base, "config_id": f"{config_id}+presidio", "final_tier": hybrid})
        print(f"[{i}/{len(files)}] {path.name}", flush=True)

    with (run_dir / "predictions.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, restval="")
        w.writeheader()
        w.writerows(rows)
    write_manifest(
        run_dir, run_id=run_id, started=started, finished=now(), folder=str(args.folder),
        configs={c: m for c, (m, _) in engines.items()}, llm=llm_info, prompt_version=args.prompt,
        seed=args.seed, n_files=len(files), labels=str(args.labels or ""),
    )  # fmt: skip
    _print_summary(rows)
    print(f"wrote {run_dir}")


def _print_summary(rows: list[dict[str, Any]]) -> None:
    """Quick look for the smoke test: accuracy, under-classification, invalid answers, latency."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["true_tier"]:
            groups[(r["config_id"], r["lang"])].append(r)
    if not groups:
        return
    print(f"\n{'config':34} {'lang':4} {'n':>3} {'acc':>5} {'under':>5} {'invalid':>7} {'p50 ms':>8}")
    for (cfg, lang), rs in sorted(groups.items()):
        ok = [r for r in rs if r["final_tier"]]
        acc = sum(r["final_tier"] == r["true_tier"] for r in ok) / len(rs)
        under = sum(tier_rank(r["final_tier"]) < tier_rank(r["true_tier"]) for r in ok) / len(rs)
        p50 = statistics.median(r["latency_ms"] for r in rs)
        print(f"{cfg:34} {lang:4} {len(rs):3} {acc:5.0%} {under:5.0%} {len(rs) - len(ok):7} {p50:8.0f}")


if __name__ == "__main__":
    main()
