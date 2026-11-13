"""Classify every supported file in one or more folders → predictions.csv + manifest.json.

    python -m research.classify_dir <folder> --configs nli_en,nli_ml,llm \
        [--labels labels.csv] [--llm-label gemma4-12b --gguf <file>.gguf]

Each semantic config yields two rows per file: `<config>` (semantic layer only) and
`<config>+presidio` (hybrid via max_tier). Engine outputs are cached.
"""

from __future__ import annotations

import argparse
import csv
import json
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
        # corpus labels have no `file` column: the file is <pair_id>.<lang>.md
        return {
            row.get("file") or f"{row['pair_id']}.{row['lang']}.md": row
            for row in csv.DictReader(f)
        }


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


MAX_ENGINE_FAILURES = 5  # in a row: the server is down, stop so the queue runner can restart it
ENGINE_ERROR = "engine exception: "  # rows with this error are redone on resume


def _resume_rows(pred_path: Path) -> list[dict[str, str]]:
    """Rows of files finished in an earlier attempt; files with an engine exception are dropped."""
    if not pred_path.exists():
        return []
    with pred_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    retry = {r["file"] for r in rows if r.get("error", "").startswith(ENGINE_ERROR)}
    return [r for r in rows if r["file"] not in retry]


def _classify_file(path, lab, engines, presidio, cache, args, run_id):  # type: ignore[no-untyped-def]
    """All config rows for one file, and whether an engine call raised (server problem)."""
    common = {
        "run_id": run_id, "pair_id": lab.get("pair_id", ""), "lang": lab.get("lang", ""),
        "true_tier": lab.get("tier", ""), "group": lab.get("group", ""),
        # attack manifests (research.attacks) double as labels files and fill these
        "variant_id": lab.get("variant_id") or "clean",
        **{k: lab.get(k, "") for k in ("attack_id", "carrier", "placement", "payload_lang")},
        "format": path.suffix.lstrip(".").lower(), "file": path.name,
    }  # fmt: skip
    try:
        text = get_text(path)
    except Exception as exc:  # noqa: BLE001 — a broken file is a result (not retried), not a crash
        err = f"extraction failed: {type(exc).__name__}: {exc}"[:300]
        names = [n for c in engines for n in (c, f"{c}+presidio")]
        return [{**common, "config_id": n, "error": err} for n in names], False
    p_val, _ = _cached(
        cache, cache_key(text, "presidio", "v6"), lambda t=text: _presidio(presidio, t)
    )
    rows, engine_failed = [], False
    for config_id, (model, eng) in engines.items():
        prompt_v = f"{args.prompt}@{eng.request_version}" if config_id.startswith("llm") else ""
        key = cache_key(text, config_id.split(":")[0], model, prompt_v)
        try:
            s_val, _ = _cached(cache, key, lambda e=eng, t=text: _semantic_to_dict(e.classify(t)))
            ref = str(cache.path(key).relative_to(args.out))
        except Exception as exc:  # noqa: BLE001 — an engine failure becomes an error row, not a crash
            engine_failed, ref = True, ""
            s_val = {"tier": "", "truncated": False, "latency_ms": "",
                     "error": f"{ENGINE_ERROR}{type(exc).__name__}: {exc}"[:300]}  # fmt: skip
        base = {
            **common, "semantic_engine": model, "defenses": "", "semantic_tier": s_val["tier"],
            "presidio_tier": p_val["tier"], "detector_flag": "", "latency_ms": s_val["latency_ms"],
            "input_chars": len(text), "truncated": int(s_val["truncated"]), "raw_output_ref": ref,
            "error": s_val["error"],
        }  # fmt: skip
        rows.append({**base, "config_id": config_id, "final_tier": s_val["tier"]})
        hybrid = max_tier(s_val["tier"], p_val["tier"]).value if s_val["tier"] else ""
        rows.append({**base, "config_id": f"{config_id}+presidio", "final_tier": hybrid})
    return rows, engine_failed


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
        **({"reasoning": r.reasoning} if r.reasoning else {}),
    }


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder", type=Path, nargs="+")
    p.add_argument("--configs", default="nli_en,nli_ml,llm")
    p.add_argument("--labels", type=Path, help="CSV with columns file,pair_id,lang,tier,group")
    p.add_argument(
        "--llm-url", default=os.environ.get("LLM_BASE_URL", "http://host.docker.internal:8080")
    )
    p.add_argument("--llm-label", default="llm", help="short model name used in config_id")
    p.add_argument(
        "--nli-url",
        default=os.environ.get("NLI_BASE_URL", ""),
        help="host NLI server (research/nli_server.py, ONNX+DirectML GPU); empty = CPU PyTorch here",
    )
    # A bare file name, not a path: Git Bash rewrites "/models/..." args into Windows paths.
    p.add_argument(
        "--gguf", help="GGUF file name in $GGUF_DIR (default /models); hashed into the manifest"
    )
    p.add_argument(
        "--template-kwargs",
        type=json.loads,
        help="""chat template kwargs as JSON, e.g. '{"enable_thinking": true}' (default: off)""",
    )
    p.add_argument("--max-tokens", type=int, default=LLM_MAX_TOKENS, help="raise for reasoning")
    p.add_argument("--prompt", default="classify_v1")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--run-id")
    p.add_argument(
        "--files", type=Path, help="text file with file names to run (a subset of the folders)"
    )
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
            eng = LlmEngine(args.llm_url, args.llm_label, args.prompt, args.seed,
                            template_kwargs=args.template_kwargs, max_tokens=args.max_tokens)  # fmt: skip
            llm_info = {"label": args.llm_label, "gguf": str(args.gguf or ""),
                        "gguf_sha256": gguf_sha, "server": eng.server_info(),
                        "max_words": LLM_MAX_WORDS, "max_tokens": eng.max_tokens,
                        "template_kwargs": eng.template_kwargs,
                        "request_version": eng.request_version}  # fmt: skip
            engines[f"llm:{args.llm_label}"] = (model, eng)
        else:
            # the backend is part of the model id, so GPU and CPU results never share a cache entry
            suffix = "@onnx-dml" if args.nli_url else ""
            engines[c] = (NLI_MODELS[c][0] + suffix, NliEngine(c, args.nli_url))
    presidio = PresidioEngine()
    nli_info = next((e.server_info() for _, e in engines.values() if isinstance(e, NliEngine)), {})

    files = sorted(
        (f for d in args.folder for f in d.iterdir() if f.suffix.lower() in EXTRACTORS),
        key=lambda f: f.name,
    )
    if args.files:
        wanted = set(args.files.read_text(encoding="utf-8").split())
        files = [f for f in files if f.name in wanted]

    # Results go to disk file by file, so a crash keeps everything finished so far. A rerun with the
    # same run id keeps the finished files and redoes the rest (engine results also sit in the cache).
    pred_path = run_dir / "predictions.csv"
    kept = _resume_rows(pred_path)
    done = {r["file"] for r in kept}
    manifest = dict(run_id=run_id, started=started, folder=[str(d) for d in args.folder],
                    configs={c: m for c, (m, _) in engines.items()}, llm=llm_info, nli_server=nli_info,
                    prompt_version=args.prompt, seed=args.seed, n_files=len(files),
                    labels=str(args.labels or ""), files=str(args.files or ""))  # fmt: skip
    write_manifest(run_dir, status="running", resumed_files=len(done), **manifest)
    out = pred_path.open("w", encoding="utf-8", newline="")
    w = csv.DictWriter(out, fieldnames=FIELDS, restval="")
    w.writeheader()
    w.writerows(kept)
    out.flush()
    failed_in_a_row = 0
    try:
        for i, path in enumerate(files, 1):
            if path.name in done:
                continue
            rows, engine_failed = _classify_file(path, labels.get(path.name, {}), engines, presidio,
                                                 cache, args, run_id)  # fmt: skip
            w.writerows(rows)
            out.flush()
            failed_in_a_row = failed_in_a_row + 1 if engine_failed else 0
            print(
                f"[{i}/{len(files)}] {path.name}" + (" ENGINE ERROR" if engine_failed else ""),
                flush=True,
            )
            if failed_in_a_row >= MAX_ENGINE_FAILURES:
                write_manifest(run_dir, status="aborted", finished=now(), **manifest)
                print(
                    f"aborted: {MAX_ENGINE_FAILURES} files in a row failed in an engine call",
                    flush=True,
                )
                raise SystemExit(3)
    finally:
        out.close()
    write_manifest(run_dir, status="done", finished=now(), **manifest)
    with pred_path.open(encoding="utf-8", newline="") as f:
        _print_summary(list(csv.DictReader(f)))
    print(f"wrote {run_dir}")


def _print_summary(rows: list[dict[str, Any]]) -> None:
    """Quick look for the smoke test: accuracy, under-classification, invalid answers, latency."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["true_tier"]:
            groups[(r["config_id"], r["lang"])].append(r)
    if not groups:
        return
    print(
        f"\n{'config':34} {'lang':4} {'n':>3} {'acc':>5} {'under':>5} {'invalid':>7} {'p50 ms':>8}"
    )
    for (cfg, lang), rs in sorted(groups.items()):
        ok = [r for r in rs if r["final_tier"]]
        acc = sum(r["final_tier"] == r["true_tier"] for r in ok) / len(rs)
        under = sum(tier_rank(r["final_tier"]) < tier_rank(r["true_tier"]) for r in ok) / len(rs)
        p50 = statistics.median(float(r["latency_ms"] or 0) for r in rs)
        print(
            f"{cfg:34} {lang:4} {len(rs):3} {acc:5.0%} {under:5.0%} {len(rs) - len(ok):7} {p50:8.0f}"
        )


if __name__ == "__main__":
    main()
