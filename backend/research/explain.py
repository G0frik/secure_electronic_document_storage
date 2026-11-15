"""Explained reruns for the case table: the model states a short reason after its tier.

    python -m research.explain --llm-url http://host.docker.internal:18080 --llm-label qwen35-9b \
        --files cases.txt --folders research/results/attacks/md ... \
        --original 'research/results/wp5/wp5_*/predictions.csv' --out research/results/wp5_explain

Illustration only, never a result: same prompt as classify_v1 except that the answer has a `reason`
string *after* `tier` (so the tier is generated before the reason, as in the real run), same
temperature 0 and seed. `same_tier` = the explained tier equals the original run's tier for that
file; only those examples may be shown. The reason is the model's stated reason, not necessarily
the cause of its answer. Writes <out>/explain_<label>.csv.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
from pathlib import Path

import requests

from app.classifier_core.extract import get_text
from app.classifier_core.llm import CATEGORY_NAMES, LLM_MAX_WORDS, PROMPTS_DIR, _truncate

PROMPT = PROMPTS_DIR / "classify_explain_v1.txt"
SCHEMA = {
    "type": "object",
    "properties": {  # order matters: llama.cpp generates the properties in this order
        "tier": {"type": "string", "enum": ["public", "internal", "confidential", "restricted"]},
        "reason": {"type": "string", "maxLength": 300},
        "categories": {"type": "array", "items": {"type": "string", "enum": CATEGORY_NAMES},
                       "maxItems": len(CATEGORY_NAMES)},
    },
    "required": ["tier", "reason", "categories"],
    "additionalProperties": False,
}  # fmt: skip


def explain(url: str, model: str, text: str, seed: int) -> dict[str, str]:
    doc, _ = _truncate(text, LLM_MAX_WORDS)
    body = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT.read_text(encoding="utf-8")
                      .replace("{document}", doc)}],
        "temperature": 0, "max_tokens": 256, "seed": seed,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "classification", "schema": SCHEMA}},
        "chat_template_kwargs": {"enable_thinking": False},
    }  # fmt: skip
    r = requests.post(f"{url.rstrip('/')}/v1/chat/completions", json=body, timeout=600)
    r.raise_for_status()
    out = json.loads(r.json()["choices"][0]["message"]["content"])
    return {"tier": out["tier"], "reason": out["reason"]}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--llm-url", required=True)
    p.add_argument("--llm-label", required=True, help="config label, e.g. qwen35-9b")
    p.add_argument("--files", type=Path, required=True, help="variant file names, one per line")
    p.add_argument("--folders", type=Path, nargs="+", required=True)
    p.add_argument("--original", required=True, help="predictions.csv pattern of the real runs")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    files = args.files.read_text(encoding="utf-8").split()
    where = {f.name: f for d in args.folders for f in d.iterdir()}
    original = {r["file"]: r["final_tier"] for path in glob.glob(args.original)
                for r in csv.DictReader(open(path, encoding="utf-8", newline=""))
                if r["config_id"] == f"llm:{args.llm_label}"}  # fmt: skip
    rows = []
    for name in files:
        got = explain(args.llm_url, args.llm_label, get_text(where[name]), args.seed)
        rows.append({"file": name, "config": f"llm:{args.llm_label}", "original_tier":
                     original.get(name, ""), "explained_tier": got["tier"],
                     "same_tier": int(got["tier"] == original.get(name)), "reason": got["reason"]})  # fmt: skip
        print(f"{name}: {original.get(name)} -> {got['tier']} | {got['reason']}", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / f"explain_{args.llm_label}.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
