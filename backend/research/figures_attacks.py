"""Thesis figures 3-5 and table 6 from the attack, detector and defense summaries (Ukrainian labels).

    python -m research.figures_attacks --analysis research/results/wp5_analysis \
        --results research/results --fig-dir research/figures

Reads <analysis>/full/summary/asr.csv (fig. 3, 4), <analysis>/detect/summary/detect.csv (fig. 5),
<analysis>/defenses/summary/{clean_cost,d4_clean}.csv and the run CSVs under <results> (table 6).
"""

from __future__ import annotations

import argparse
import csv
import glob
import statistics
from pathlib import Path
from typing import Any

from research.analyze import wilson

ATTACKS = ["A1", "A2", "A3/A1", "A3/A2", "A4", "A5", "A6", "A7"]
ATTACK_LABELS = {
    "clean": "чисті\n(хибні\nтривоги)",
    "A1": "A1\nдиректива",
    "A2": "A2\nгриф",
    "A3/A1": "A3/A1\nприхована\nдиректива",
    "A3/A2": "A3/A2\nприхований\nгриф",
    "A4": "A4\nіншою\nмовою",
    "A5": "A5\nзаповнення",
    "A6": "A6\nобфускація\nID",
    "A7": "A7\nприхований\nвміст",
}
INJECTIONS = ["A1", "A2", "A3/A1", "A3/A2", "A4", "A5"]  # pooled for the hybrid figure (H3)
CONFIGS = ["nli_en", "nli_ml", "llm:gemma4-12b", "llm:qwen35-9b", "llm:gemma4-e4b",
           "llm:gemma3-12b", "llm:mamaylm-12b", "llm:lapa-12b"]  # fmt: skip
SERIES = ["#2a78d6", "#eb6834"]  # categorical slots 1-2 (validated pair)
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
BLUES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def _name(cfg: str) -> str:
    return cfg.removeprefix("llm:")


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _plt() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
                         "xtick.color": MUTED, "ytick.color": MUTED, "svg.fonttype": "none"})  # fmt: skip
    return plt


def _save(fig: Any, fig_dir: Path, name: str) -> None:
    fig_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(fig_dir / f"{name}.{ext}", dpi=200, bbox_inches="tight")


def _bars(ax: Any, groups: list[str], series: list[tuple[str, list[float], list[float],
          list[float]]]) -> None:  # fmt: skip
    """Grouped bars with error bars; series = (label, values, lo, hi)."""
    width = 0.8 / len(series)
    for j, (label, vals, lo, hi) in enumerate(series):
        xs = [i + (j - (len(series) - 1) / 2) * width for i in range(len(groups))]
        err = [[v - a for v, a in zip(vals, lo, strict=True)],
               [b - v for v, b in zip(vals, hi, strict=True)]]  # fmt: skip
        ax.bar(xs, vals, width * 0.92, color=SERIES[j], label=label, yerr=err,
               error_kw={"elinewidth": 0.8, "capsize": 2, "ecolor": MUTED})  # fmt: skip
    ax.set_xticks(range(len(groups)), groups)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def fig3_heatmap(asr: list[dict[str, str]], fig_dir: Path) -> None:
    plt = _plt()
    from matplotlib.colors import BoundaryNorm, ListedColormap

    cell = {(r["config"], r["attack_id"]): r for r in asr if r["by"] == "all"}
    grid = [[float(cell[(c, a)]["asr"]) for a in ATTACKS] for c in CONFIGS]
    bounds = [0, 0.05, 0.1, 0.2, 0.3, 0.45, 0.6, 1.0]
    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    ax.imshow(grid, cmap=ListedColormap(BLUES), norm=BoundaryNorm(bounds, len(BLUES)),
              aspect="auto")  # fmt: skip
    for i in range(len(CONFIGS)):
        for j in range(len(ATTACKS)):
            v = grid[i][j]
            ax.text(j, i, f"{v * 100:.0f}", ha="center", va="center", fontsize=8,
                    color="white" if v >= 0.3 else INK)  # fmt: skip
    ax.set_xticks(range(len(ATTACKS)), [ATTACK_LABELS[a] for a in ATTACKS], fontsize=7.5)
    ax.set_yticks(range(len(CONFIGS)), [_name(c) for c in CONFIGS])
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title("Успішність атак (ASR, %), без захисту, семантичний шар без Presidio",
                 loc="left", fontsize=9.5, color=INK)  # fmt: skip
    _save(fig, fig_dir, "fig3_asr_heatmap")
    plt.close(fig)


def fig4_hybrid(asr: list[dict[str, str]], fig_dir: Path) -> None:
    plt = _plt()
    by = {(r["config"], r["attack_id"], r["value"]): r for r in asr if r["by"] == "group"}
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
    for ax, group, title in ((axes[0], "id", "Документи з ідентифікаторами (id)"),
                             (axes[1], "semantic", "Документи, чутливі за змістом")):  # fmt: skip
        series = []
        for label, suffix in (("лише семантичний шар", ""), ("гібрид з Presidio", "+presidio")):
            vals, lo, hi = [], [], []
            for c in CONFIGS:
                rows = [
                    by[(c + suffix, a, group)] for a in INJECTIONS if (c + suffix, a, group) in by
                ]
                k, n = sum(int(r["k_asr"]) for r in rows), sum(int(r["n"]) for r in rows)
                v = k / n if n else 0.0
                a, b = wilson(k, n)
                vals, lo, hi = vals + [v], lo + [a], hi + [b]
            series.append((label, vals, lo, hi))
        _bars(ax, [_name(c) for c in CONFIGS], series)
        ax.set_title(title, loc="left", fontsize=9.5, color=INK)
        ax.tick_params(axis="x", rotation=35)
        for t in ax.get_xticklabels():
            t.set_ha("right")
    axes[0].set_ylabel("ASR, атаки A1–A5 разом (95% ДІ Вілсона)")
    axes[0].set_ylim(0, 1)
    axes[0].legend(frameon=False, loc="upper left")
    _save(fig, fig_dir, "fig4_hybrid_by_group")
    plt.close(fig)


def fig5_detectors(detect: list[dict[str, str]], fig_dir: Path) -> None:
    plt = _plt()
    cell = {(r["detector"], r["attack_id"]): r for r in detect if r["by"] == "all"}
    groups = ["clean"] + ATTACKS
    series = []
    for det, label in (("pg2", "Prompt Guard 2 86M"), ("protectai", "ProtectAI DeBERTa v2")):
        rows = [cell[(det, g)] for g in groups]
        series.append((label, [float(r["rate"]) for r in rows],
                       [float(r["rate_lo_doc"]) for r in rows],
                       [float(r["rate_hi_doc"]) for r in rows]))  # fmt: skip
    fig, ax = plt.subplots(figsize=(10, 3.8))
    _bars(ax, [ATTACK_LABELS[g] for g in groups], series)
    for j, (_, vals, _, hi) in enumerate(series):  # value labels: the zero bars are the finding
        for i, (v, h) in enumerate(zip(vals, hi, strict=True)):
            ax.text(i + (j - 0.5) * 0.4, h + 0.015, f"{v * 100:.0f}", ha="center", va="bottom",
                    fontsize=7, color=MUTED)  # fmt: skip
    ax.tick_params(axis="x", labelsize=7.5)
    ax.set_ylim(0, 1)
    ax.set_ylabel("частка позначених файлів, поріг 0,5\n(95% ДІ, бутстреп за документами)")
    ax.legend(frameon=False, loc="upper left")
    ax.set_title("Детектори ін'єкцій (D4): частка позначених файлів за класом атаки",
                 loc="left", fontsize=9.5, color=INK)  # fmt: skip
    _save(fig, fig_dir, "fig5_detectors")
    plt.close(fig)


def _latency(results: Path, pattern: str, config: str) -> tuple[float, float]:
    vals = [float(r["latency_ms"]) for p in glob.glob(str(results / pattern))
            for r in _read(Path(p)) if r["config_id"] == config and r["latency_ms"]]  # fmt: skip
    q = statistics.quantiles(vals, n=100, method="inclusive")
    return q[49] / 1000, q[94] / 1000


def table6(analysis: Path, results: Path, out: Path) -> None:
    cost = {r["config"]: r for r in _read(analysis / "defenses/summary/clean_cost.csv")}
    d4 = _read(analysis / "defenses/summary/d4_clean.csv")
    gated = {(r["config"], r["detector"], r["gate"]): r for r in d4
             if r["config"] and r.get("value") == "wp2"}  # fmt: skip
    alarms = {r["detector"]: r for r in d4 if not r["config"] and r["by"] == "all"}
    pct = lambda x: f"{float(x) * 100:.1f}"  # noqa: E731
    lines = [
        "# Таблиця 6. Ціна захистів",
        "",
        "Точність на чистих варіантах набору атак (n = 294, грифи вище PUBLIC) і на базовому "
        "чистому корпусі з D4 ProtectAI (n = 96); затримка на файл, p50 / p95, с "
        "(без захисту → D2 → D1+D2; кешовані рядки зберігають затримку першого виклику).",
        "",
        "| конфігурація | точність: без / D1 / D2 / D1+D2, % | база: без / з D4 ProtectAI, % "
        "| затримка без | з D2 | з D1+D2 |",
        "|---|---|---|---|---|---|",
    ]
    for c in ["nli_en", "nli_ml", "llm:gemma4-12b", "llm:qwen35-9b", "llm:gemma4-e4b"]:
        acc = [cost.get(f"{c}@{d}", {}).get("acc") for d in ("none", "D1", "D2", "D1,D2")]
        lat = [_latency(results, p, c) if c.startswith("llm") or "d1" not in p else None
               for p in ("wp5/wp5_*/predictions.csv", "wp5_d2/*/predictions.csv",
                         "wp5_d1/*/predictions.csv")]  # fmt: skip
        g0, g1 = gated[(c, "", "none")], gated[(c, "protectai", "D4")]
        lines.append(
            f"| {_name(c)} | {' / '.join(pct(a) if a else '—' for a in acc)} "
            f"| {pct(g0['acc'])} / {pct(g1['acc'])} | "
            + " | ".join(f"{x[0]:.1f} / {x[1]:.1f}" if x else "—" for x in lat)
            + " |"
        )
    lines += ["", "Хибні тривоги D4 на 130 чистих документах (усі грифи): "
              + "; ".join(f"{d} {r['false_alarms']}/{r['n']} ({pct(r['rate'])}%)"
                          for d, r in sorted(alarms.items())) + "."]  # fmt: skip
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--analysis", type=Path, required=True)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--fig-dir", type=Path, required=True)
    args = p.parse_args(argv)
    asr = _read(args.analysis / "full/summary/asr.csv")
    fig3_heatmap(asr, args.fig_dir)
    fig4_hybrid(asr, args.fig_dir)
    fig5_detectors(_read(args.analysis / "detect/summary/detect.csv"), args.fig_dir)
    table6(args.analysis, args.results, args.fig_dir / "table6_defense_cost.md")
    print(f"wrote figures 3-5 and table 6 to {args.fig_dir}")


if __name__ == "__main__":
    main()
