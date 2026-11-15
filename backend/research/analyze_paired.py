"""Paired tests on attacked variants: defense on/off, EN vs UK, hybrid vs semantic, think vs not.

    python -m research.analyze_paired research/results/wp5_defended/*.csv \
        --manifest research/results/attacks/manifest.csv \
        --think 'research/results/wp5_sample/wp5s_qwen35-9b-think1k/predictions.csv' \
        --think-files research/results/wp5/sample_think.txt \
        --out research/results/wp5_analysis/paired

Outcome per attacked variant with true tier above PUBLIC: robust = final tier >= true tier (no
clean-twin condition, so the same variant pairs across defense sets, languages and configs).
b = robust only in A, c = robust only in B. Variants of one source document are not independent,
so `p_cluster` is the cluster-adjusted McNemar test of Durkalski et al. (2003) with documents
(`pair_id`) as clusters: X2 = (sum_k (b_k - c_k))^2 / sum_k (b_k - c_k)^2, 1 df. `p_exact` is the
exact McNemar test on variants, for reference only. Holm on p_cluster within each family; the
confirmatory families were fixed before the results were seen, the rest are exploratory.
Writes <out>/summary/paired.csv.
"""

from __future__ import annotations

import argparse
import csv
import glob
import math
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.classifier_core.tiers import tier_rank
from research.analyze import _write, holm, mcnemar_exact
from research.analyze_defenses import HYBRID, load_defended

Row = dict[str, Any]
PUBLIC = tier_rank("public")
ATTACKS = ["A1", "A2", "A3/A1", "A3/A2", "A4", "A5", "A6", "A7"]
CONFIRMATORY = ["nli_en", "nli_ml", "llm:gemma4-12b", "llm:qwen35-9b", "llm:gemma4-e4b"]
D1_CONFIGS = ["llm:gemma4-12b", "llm:qwen35-9b", "llm:gemma4-e4b"]
D2_ATTACKS = ["A3/A1", "A3/A2", "A7"]  # the only classes where the visible view differs


def robust(r: Row) -> bool:
    return bool(r["final_tier"]) and tier_rank(r["final_tier"]) >= tier_rank(r["true_tier"])


def durkalski(per_doc: Iterable[tuple[int, int]]) -> float:
    """Cluster-adjusted McNemar p-value from per-cluster discordant counts (b_k, c_k)."""
    d = [b - c for b, c in per_doc]
    den = sum(x * x for x in d)
    if den == 0:
        return 1.0
    x2 = sum(d) ** 2 / den
    return math.erfc(math.sqrt(x2 / 2))  # chi-square survival function, 1 df


def compare(pairs: list[tuple[Row, Row]]) -> dict[str, Any]:
    per_doc: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    b = c = 0
    for x, y in pairs:
        rx, ry = robust(x), robust(y)
        if rx != ry:
            per_doc[x["pair_id"]][0 if rx else 1] += 1
            b, c = b + rx, c + ry
    n = len(pairs)
    return {"n_pairs": n, "n_docs": len({x["pair_id"] for x, _ in pairs}),
            "robust_a": sum(robust(x) for x, _ in pairs) / n if n else 0.0,
            "robust_b": sum(robust(y) for _, y in pairs) / n if n else 0.0,
            "b": b, "c": c, "p_exact": mcnemar_exact(b, c),
            "p_cluster": durkalski((bk, ck) for bk, ck in per_doc.values())}  # fmt: skip


def _twin_key(r: Row) -> tuple[str, ...]:
    """Same variant in the other language: payload in the document's language or the other one."""
    own = r["payload_lang"] in ("", r["lang"])
    return (r["pair_id"], r["attack_id"], r["carrier"], r["placement"], r["format"], str(own))


def paired_tests(rows: list[Row], think: list[Row]) -> list[dict[str, Any]]:
    attacked = [r for r in rows if r["attack_id"] and tier_rank(r["true_tier"]) > PUBLIC]
    by: dict[tuple[str, str], dict[str, Row]] = defaultdict(dict)  # (config, attack) -> file -> row
    for r in attacked:
        by[(r["config_id"], r["attack_id"])][r["file"]] = r
    configs = list(dict.fromkeys(r["config_id"] for r in attacked))
    out: list[dict[str, Any]] = []

    def add(family: str, comparison: str, config: str, attack: str,
            pairs: list[tuple[Row, Row]]) -> None:  # fmt: skip
        if pairs:
            out.append({"family": family, "comparison": comparison, "config": config,
                        "attack_id": attack} | compare(pairs))  # fmt: skip

    def paired(a: str, b: str, attack: str) -> list[tuple[Row, Row]]:
        xa, xb = by.get((a, attack), {}), by.get((b, attack), {})
        return [(xa[f], xb[f]) for f in sorted(xa.keys() & xb.keys())]

    # Defense on (A) vs off (B), same variant.
    for cfg in configs:
        base, hyb = cfg.split("@")[0], cfg.endswith(HYBRID)
        dset = cfg.split("@")[1].removesuffix(HYBRID)
        off = f"{base}@none" + (HYBRID if hyb else "")
        if dset == "none" or off not in configs:
            continue
        family = ("defense:confirmatory"
                  if not hyb and ((dset == "D2" and base in CONFIRMATORY)
                                  or (dset == "D1" and base in D1_CONFIGS))
                  else "defense:exploratory")  # fmt: skip
        attacks = D2_ATTACKS if dset == "D2" and family.endswith("confirmatory") else ATTACKS
        for a in attacks:
            add(family, f"{dset} vs none", base + (HYBRID if hyb else ""), a, paired(cfg, off, a))

    # EN (A) vs UK (B) twins, no defense.
    for cfg in (c for c in configs if c.split("@")[1].removesuffix(HYBRID) == "none"):
        base = cfg.split("@")[0]
        family = "en_vs_uk:" + ("hybrid" if cfg.endswith(HYBRID)
                                else "confirmatory" if base in CONFIRMATORY else "exploratory")  # fmt: skip
        base += HYBRID if cfg.endswith(HYBRID) else ""
        for a in ATTACKS:
            rs = by.get((cfg, a), {}).values()
            uk = {_twin_key(r): r for r in rs if r["lang"] == "uk"}
            pairs = [(r, uk[_twin_key(r)]) for r in rs if r["lang"] == "en" and _twin_key(r) in uk]
            add(family, "en vs uk", base, a, pairs)

    # Hybrid (A) vs semantic only (B), no defense, by document group, all attacks pooled (H3).
    for cfg in (c for c in configs if c.endswith(f"@none{HYBRID}")):
        sem = cfg.removesuffix(HYBRID)
        base = sem.split("@")[0]
        family = "hybrid:" + ("confirmatory" if base in CONFIRMATORY else "exploratory")
        for group in ("id", "semantic"):
            pairs = [p for a in ATTACKS for p in paired(cfg, sem, a) if p[0]["group"] == group]
            add(family, f"+presidio vs semantic ({group})", base, "all", pairs)

    # Thinking (A) vs not (B), same files.
    if think:
        tk = {(r["attack_id"], r["file"]): r for r in think
              if r["attack_id"] and not r["config_id"].endswith(HYBRID)}  # fmt: skip
        for a in ATTACKS:
            nothink = by.get(("llm:qwen35-9b@none", a), {})
            pairs = [(tk[(a, f)], nothink[f]) for f in sorted(nothink) if (a, f) in tk]
            add("think:exploratory", "think1k vs no think", "llm:qwen35-9b", a, pairs)

    for fam in dict.fromkeys(t["family"] for t in out):
        idx = [i for i, t in enumerate(out) if t["family"] == fam]
        for i, p in zip(idx, holm([out[i]["p_cluster"] for i in idx]), strict=True):
            out[i] |= {"m_family": len(idx), "p_holm": p, "significant": int(p < 0.05)}
    return out


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("defended", nargs="+", type=Path, help="research.defend output CSVs")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--think", help="predictions.csv (pattern) of the thinking config")
    p.add_argument("--think-files", type=Path, help="variant files run by the thinking config")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    rows = load_defended(args.defended, args.manifest)
    think: list[Row] = []
    if args.think:
        files = (
            set(args.think_files.read_text(encoding="utf-8").split()) if args.think_files else None
        )
        for path in sorted(glob.glob(args.think)) or [args.think]:
            with open(path, encoding="utf-8", newline="") as f:
                think += [r for r in csv.DictReader(f) if files is None or r["file"] in files]
    table = paired_tests(rows, think)
    out = args.out / "summary"
    out.mkdir(parents=True, exist_ok=True)
    _write(out / "paired.csv", table)
    sig = [t for t in table if t["significant"]]
    print(f"{len(table)} tests, {len(sig)} significant after Holm -> {out / 'paired.csv'}")


if __name__ == "__main__":
    main()
