"""Clean-baseline metrics from one or more predictions.csv files.

    python -m research.analyze 'research/results/wp2/wp2_*/predictions.csv' \
        --labels research/corpus/data/labels.csv --out research/results/wp2_summary

Writes <out>/summary/{metrics,per_class,confusion,mcnemar}.csv and the clean-baseline figure
(PNG + SVG) to --fig-dir. Invalid answers (empty final_tier) count as wrong, never as under-
or over-classification. Stats use only the standard library.
"""

from __future__ import annotations

import argparse
import csv
import glob
import math
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from app.classifier_core.tiers import Tier, tier_rank

RESEARCH_DIR = Path(__file__).parent
TIERS = [t.value for t in Tier]
Z95 = 1.959964
SYNTHETIC_SOURCES = {"synthetic", "synthetic-template"}
LANGS = ["en", "uk"]

Row = dict[str, str]


# ---------- statistics ----------


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for k successes out of n."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z / denom * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, centre - half), min(1.0, centre + half)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant counts b and c."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(b, c) + 1)) / 2**n
    return min(1.0, 2 * tail)


def holm(pvalues: list[float]) -> list[float]:
    """Holm step-down adjusted p-values, in the input order."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted


# ---------- metrics ----------


def _correct(r: Row) -> bool:
    return r["final_tier"] == r["true_tier"]


def _direction(r: Row) -> int:
    """-1 under, 0 exact or invalid, +1 over."""
    if not r["final_tier"]:
        return 0
    d = tier_rank(r["final_tier"]) - tier_rank(r["true_tier"])
    return (d > 0) - (d < 0)


def per_class(rows: list[Row]) -> dict[str, dict[str, float]]:
    out = {}
    for t in TIERS:
        tp = sum(r["true_tier"] == t and r["final_tier"] == t for r in rows)
        pred = sum(r["final_tier"] == t for r in rows)
        support = sum(r["true_tier"] == t for r in rows)
        prec = tp / pred if pred else 0.0
        rec = tp / support if support else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        out[t] = {"precision": prec, "recall": rec, "f1": f1, "support": support, "predicted": pred}
    return out


def macro_f1(rows: list[Row]) -> float:
    """Mean F1 over tiers that occur in the truth or the predictions (sklearn's default)."""
    pc = per_class(rows)
    present = [t for t in TIERS if pc[t]["support"] or pc[t]["predicted"]]
    return sum(pc[t]["f1"] for t in present) / len(present) if present else 0.0


def _pct(values: list[float], q: float) -> float:
    if len(values) < 2:
        return values[0] if values else 0.0
    return statistics.quantiles(values, n=100, method="inclusive")[round(q * 100) - 1]


def metrics(rows: list[Row]) -> dict[str, Any]:
    n = len(rows)
    k_acc = sum(map(_correct, rows))
    k_under = sum(_direction(r) < 0 for r in rows)
    k_over = sum(_direction(r) > 0 for r in rows)
    valid = [r for r in rows if r["final_tier"]]
    lat = [float(r["latency_ms"]) for r in rows if r.get("latency_ms")]
    out: dict[str, Any] = {"n": n}
    for name, k in (("acc", k_acc), ("under", k_under), ("over", k_over)):
        lo, hi = wilson(k, n)
        out |= {name: k / n if n else 0.0, f"{name}_lo": lo, f"{name}_hi": hi}
    out["macro_f1"] = macro_f1(rows)
    out["mae"] = (
        statistics.mean(abs(tier_rank(r["final_tier"]) - tier_rank(r["true_tier"])) for r in valid)
        if valid
        else 0.0
    )
    out["invalid"] = n - len(valid)
    out["p50_ms"] = _pct(lat, 0.50)
    out["p95_ms"] = _pct(lat, 0.95)
    return out


SUBSETS: dict[str, Callable[[Row], bool]] = {
    "all": lambda r: True,
    "real": lambda r: r["source"] not in SYNTHETIC_SOURCES,
    # id / semantic are compared only inside confidential + restricted, where both groups exist
    "id": lambda r: r["group"] == "id",
    "semantic_cr": lambda r: (
        r["group"] == "semantic" and r["true_tier"] in ("confidential", "restricted")
    ),
}


# ---------- loading ----------


def load(patterns: Iterable[str], labels_path: Path) -> list[Row]:
    with labels_path.open(encoding="utf-8", newline="") as f:
        source = {f"{r['pair_id']}.{r['lang']}.md": r["source"] for r in csv.DictReader(f)}
    rows: dict[tuple[str, str], Row] = {}
    for pattern in patterns:
        paths = sorted(glob.glob(pattern)) or [pattern]
        for path in paths:
            with open(path, encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    if r["variant_id"] != "clean" or not r["true_tier"]:
                        continue
                    key = (r["config_id"], r["file"])
                    if key in rows:  # the same config in two runs would be counted twice
                        raise SystemExit(f"duplicate {key} in {path}")
                    rows[key] = {**r, "source": source.get(r["file"], "")}
    return list(rows.values())


def config_order(rows: list[Row]) -> list[str]:
    """NLI configs first, then LLMs in first-seen order; each hybrid right after its base."""
    bases = list(dict.fromkeys(r["config_id"].removesuffix("+presidio") for r in rows))
    bases.sort(key=lambda c: not c.startswith("nli"))
    seen = {r["config_id"] for r in rows}
    return [c for b in bases for c in (b, f"{b}+presidio") if c in seen]


# ---------- outputs ----------


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({k: round(v, 4) if isinstance(v, float) else v for k, v in r.items()})


def _paired(a: dict[Any, bool], b: dict[Any, bool]) -> dict[str, Any]:
    keys = a.keys() & b.keys()
    n01 = sum(a[k] and not b[k] for k in keys)
    n10 = sum(b[k] and not a[k] for k in keys)
    return {
        "n": len(keys),
        "acc_a": sum(a[k] for k in keys) / len(keys) if keys else 0.0,
        "acc_b": sum(b[k] for k in keys) / len(keys) if keys else 0.0,
        "b_only_a_right": n01,
        "c_only_b_right": n10,
        "p": mcnemar_exact(n01, n10),
    }


def mcnemar_table(rows: list[Row], configs: list[str]) -> list[dict[str, Any]]:
    by = defaultdict(dict)  # (config, lang) -> {pair_id: correct}
    for r in rows:
        by[(r["config_id"], r["lang"])][r["pair_id"]] = _correct(r)

    def per_lang(cfg: str) -> dict[Any, bool]:
        return {(lang, pid): v for lang in LANGS for pid, v in by[(cfg, lang)].items()}

    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    nlis = [c for c in configs if c.startswith("nli") and "+" not in c]
    llms = [c for c in configs if c.startswith("llm") and "+" not in c]
    for nli in nlis:
        for llm in llms:
            for lang in LANGS:
                families["nli_vs_llm"].append(
                    {"comparison": f"{nli} vs {llm}", "lang": lang}
                    | _paired(by[(nli, lang)], by[(llm, lang)])
                )
    for cfg in configs:
        families["en_vs_uk"].append(
            {"comparison": f"{cfg}: en vs uk", "lang": "paired"}
            | _paired(by[(cfg, "en")], by[(cfg, "uk")])
        )
    for cfg in configs:
        if f"{cfg}+presidio" in configs:
            families["semantic_vs_hybrid"].append(
                {"comparison": f"{cfg} vs {cfg}+presidio", "lang": "all"}
                | _paired(per_lang(cfg), per_lang(f"{cfg}+presidio"))
            )
    out = []
    for family, comps in families.items():
        for comp, p_holm in zip(comps, holm([c["p"] for c in comps]), strict=True):
            out.append({"family": family, **comp, "p_holm": p_holm})
    return out


def figure(metric_rows: list[dict[str, Any]], configs: list[str], fig_dir: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    semantic = [c for c in configs if "+" not in c]
    get = {(m["config"], m["lang"]): m for m in metric_rows if m["subset"] == "all"}
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    width = 0.38
    xs = range(len(semantic))
    for ax, key, title in (
        (axes[0], "macro_f1", "Макро-F1"),
        (axes[1], "under", "Частка заниження грифу"),
    ):
        for j, (lang, label, color) in enumerate(
            (("en", "англ.", "#4C72B0"), ("uk", "укр.", "#DD8452"))
        ):
            vals = [get[(c, lang)][key] for c in semantic]
            err = None
            if key == "under":
                err = [
                    [v - get[(c, lang)]["under_lo"] for c, v in zip(semantic, vals, strict=True)],
                    [get[(c, lang)]["under_hi"] - v for c, v in zip(semantic, vals, strict=True)],
                ]
            ax.bar([x + (j - 0.5) * width for x in xs], vals, width, yerr=err, capsize=3,
                   label=label, color=color)  # fmt: skip
        ax.set_title(title)
        ax.set_xticks(list(xs), semantic, rotation=30, ha="right")
        ax.set_ylim(0, 1)
        ax.grid(axis="y", alpha=0.3)
    axes[0].legend(title="Мова")
    axes[1].set_ylabel("частка документів (95% ДІ Вілсона)")
    fig.tight_layout()
    fig_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(fig_dir / f"fig1_clean_baseline.{ext}", dpi=200)
    plt.close(fig)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("predictions", nargs="+", help="predictions.csv paths or quoted glob patterns")
    p.add_argument("--labels", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--fig-dir", type=Path, default=RESEARCH_DIR / "figures")
    args = p.parse_args(argv)

    rows = load(args.predictions, args.labels)
    configs = config_order(rows)
    out = args.out / "summary"
    out.mkdir(parents=True, exist_ok=True)

    metric_rows, class_rows, conf_rows = [], [], []
    for cfg in configs:
        for lang in [*LANGS, "all"]:
            sel = [r for r in rows if r["config_id"] == cfg and lang in (r["lang"], "all")]
            for subset, keep in SUBSETS.items():
                sub = [r for r in sel if keep(r)]
                if sub:
                    metric_rows.append(
                        {"config": cfg, "lang": lang, "subset": subset} | metrics(sub)
                    )
            for t, v in per_class(sel).items():
                class_rows.append({"config": cfg, "lang": lang, "tier": t} | v)
            for t in TIERS:
                cells = {
                    p: sum(r["true_tier"] == t and r["final_tier"] == p for r in sel) for p in TIERS
                }
                invalid = sum(r["true_tier"] == t and not r["final_tier"] for r in sel)
                conf_rows.append(
                    {"config": cfg, "lang": lang, "true_tier": t} | cells | {"invalid": invalid}
                )

    _write(out / "metrics.csv", metric_rows)
    _write(out / "per_class.csv", class_rows)
    _write(out / "confusion.csv", conf_rows)
    _write(out / "mcnemar.csv", mcnemar_table(rows, configs))
    figure(metric_rows, configs, args.fig_dir)

    print(
        f"{'config':28} {'lang':4} {'n':>3} {'acc':>5} {'F1':>5} {'under':>5} {'inv':>3} {'p50':>6}"
    )
    for m in metric_rows:
        if m["subset"] == "all":
            print(f"{m['config']:28} {m['lang']:4} {m['n']:3} {m['acc']:5.0%} {m['macro_f1']:5.2f} "
                  f"{m['under']:5.0%} {m['invalid']:3} {m['p50_ms']:6.0f}")  # fmt: skip
    print(f"wrote {out} and {args.fig_dir}")


if __name__ == "__main__":
    main()
