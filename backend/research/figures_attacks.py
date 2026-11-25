"""Attack, defense and detector figures (Ukrainian labels for the thesis, English for the repo).

    python -m research.figures_attacks --analysis research/results/wp5_analysis \
        --results research/results --fig-dir research/figures [--lang en] \
        [--pooled research/results/pooled]

Reads <analysis>/full/summary/asr.csv (heatmap, hybrid), <analysis>/defenses/summary/asr.csv
(defense effect), <analysis>/detect/summary/detect.csv (detectors), <results>/wp2_summary/summary/
metrics.csv (clean accuracy) and, for the Ukrainian table 6, the defense cost CSVs and run CSVs.
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
INJECTIONS = ["A1", "A2", "A3/A1", "A3/A2", "A4", "A5"]  # pooled for the hybrid figure (H3)
# A3 is A1/A2 through a hidden carrier: whether it works is set by the extractor, not the model
HEATMAP_ATTACKS = ["A1", "A2", "A4", "A5", "A6", "A7"]
CONFIGS = ["nli_en", "nli_ml", "llm:gemma4-12b", "llm:qwen35-9b", "llm:gemma4-e4b",
           "llm:gemma3-12b", "llm:mamaylm-12b", "llm:lapa-12b"]  # fmt: skip
D1_CONFIGS = ["llm:gemma4-12b", "llm:qwen35-9b", "llm:gemma4-e4b"]
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]  # categorical slots 1-3 (validated)
BASELINE = "#b4b2ab"  # no defense: neutral gray, so the defenses carry the colour
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
BLUES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

TEXT: dict[str, dict[str, Any]] = {
    "uk": {
        "attacks": {
            "clean": "чисті\n(хибні\nтривоги)", "A1": "A1\nвказівка\nкласу",
            "A2": "A2\nімітація\nслужбових\nметаданих",
            "A3/A1": "A3/A1\nприхований\nносій з A1", "A3/A2": "A3/A2\nприхований\nносій з A2",
            "A4": "A4\nнавантаження\nіншою мовою", "A5": "A5\nрозбавлення",
            "A6": "A6\nобфускація\nідентифікаторів", "A7": "A7\nприховування\nчутливого\nвмісту",
        },
        "hybrid_panels": ("Документи з ідентифікаторами (id)", "Документи, чутливі за змістом"),
        "hybrid_series": ("лише семантичний шар", "гібрид з Presidio"),
        "hybrid_y": "ASR, атаки A1–A5 разом (95% ДІ Вілсона)",
        "det_title": "Детектори ін'єкцій (D4): частка позначених файлів за класом атаки",
        "det_y": "частка позначених файлів, поріг 0,5\n(95% ДІ, бутстреп за документами)",
        "clean_title": "Точність на чистих документах (базовий набір, 48 пар)",
        "clean_series": ("англ.", "укр."),
        "clean_y": "точність (95% ДІ Вілсона)",
        "def_panels": ("Приховані носії (A3/A1 + A3/A2)", "Видимий текст (A1 + A2)"),
        "def_series": ("без захисту", "D1 посилений промпт", "D2 два подання",
                       "D1 + D2"),
        "def_y": "ASR (95% ДІ Вілсона)",
        "hybrid_y_doc": "ASR, атаки A1–A5 разом\n(95% ДІ, бутстреп за документами)",
        "def_y_doc": "ASR (95% ДІ, бутстреп за документами)",
    },
    "en": {
        "attacks": {
            "clean": "clean\n(false\nalarms)", "A1": "A1\ndirective", "A2": "A2\nstamp",
            "A3/A1": "A3/A1\nhidden\ndirective", "A3/A2": "A3/A2\nhidden\nstamp",
            "A4": "A4\nother\nlanguage", "A5": "A5\npadding", "A6": "A6\nobfuscated\nIDs",
            "A7": "A7\nhidden\ncontent",
        },
        "hybrid_panels": ("Documents with identifiers (id)", "Documents sensitive by meaning"),
        "hybrid_series": ("semantic layer only", "hybrid with Presidio"),
        "hybrid_y": "ASR, attacks A1–A5 pooled (95% Wilson CI)",
        "det_title": "Injection detectors (D4): share of files flagged, by attack class",
        "det_y": "share flagged at threshold 0.5\n(95% CI, bootstrap by document)",
        "clean_title": "Accuracy on clean documents (base set, 48 pairs)",
        "clean_series": ("English", "Ukrainian"),
        "clean_y": "accuracy (95% Wilson CI)",
        "def_panels": ("Hidden carriers (A3/A1 + A3/A2)", "Visible text (A1 + A2)"),
        "def_series": ("no defense", "D1 hardened prompt", "D2 two views", "D1 + D2"),
        "def_y": "ASR (95% Wilson CI)",
        "hybrid_y_doc": "ASR, attacks A1–A5 pooled\n(95% CI, bootstrap by document)",
        "def_y_doc": "ASR (95% CI, bootstrap by document)",
    },
}  # fmt: skip


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
          list[float]]], colors: list[str] | None = None, labels: bool = False) -> None:  # fmt: skip
    """Grouped bars with error bars; series = (label, values, lo, hi); optional value labels."""
    colors = colors or SERIES
    width = 0.8 / len(series)
    for j, (label, vals, lo, hi) in enumerate(series):
        xs = [i + (j - (len(series) - 1) / 2) * width for i in range(len(groups))]
        err = [[v - a for v, a in zip(vals, lo, strict=True)],
               [b - v for v, b in zip(vals, hi, strict=True)]]  # fmt: skip
        ax.bar(xs, vals, width * 0.92, color=colors[j], label=label, yerr=err,
               error_kw={"elinewidth": 0.8, "capsize": 2, "ecolor": MUTED})  # fmt: skip
        if labels:
            for x, v, h in zip(xs, vals, hi, strict=True):
                ax.text(x, h + 0.015, f"{v * 100:.0f}", ha="center", va="bottom", fontsize=7,
                        color=MUTED)  # fmt: skip
    ax.set_xticks(range(len(groups)), groups)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


Doc = dict[tuple[str, str, str], dict[str, str]]  # (config, pool, group or "") -> pooled.csv row


def _read_doc(path: Path | None) -> Doc | None:
    """research.analyze_pooled output, or None (then the bars get Wilson CIs)."""
    if path is None:
        return None
    return {(r["config"], r["pool"], r["value"]): r for r in _read(path)}


def _pooled(cell: dict[tuple[str, str], dict[str, str]], cfg: str, attacks: list[str],
            doc: Doc | None = None, group: str = "") -> tuple[float, float, float]:  # fmt: skip
    rows = [cell[(cfg, a)] for a in attacks if (cfg, a) in cell]
    k, n = sum(int(r["k_asr"]) for r in rows), sum(int(r["n"]) for r in rows)
    lo, hi = wilson(k, n)
    if doc is not None:  # CI by source document; same rate, checked against the per-class table
        d = doc[(cfg, "+".join(attacks), group)]
        if (int(d["k_asr"]), int(d["n"])) != (k, n):
            raise SystemExit(f"pooled.csv does not match asr.csv: {cfg} {attacks} {group}")
        lo, hi = float(d["asr_lo_doc"]), float(d["asr_hi_doc"])
    return (k / n if n else 0.0), lo, hi


def fig_heatmap(asr: list[dict[str, str]], fig_dir: Path, t: dict[str, Any], name: str) -> None:
    plt = _plt()
    from matplotlib.colors import BoundaryNorm, ListedColormap

    cell = {(r["config"], r["attack_id"]): r for r in asr if r["by"] == "all"}
    grid = [[float(cell[(c, a)]["asr"]) for a in HEATMAP_ATTACKS] for c in CONFIGS]
    bounds = [0, 0.05, 0.1, 0.2, 0.3, 0.45, 0.6, 1.0]
    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    ax.imshow(grid, cmap=ListedColormap(BLUES), norm=BoundaryNorm(bounds, len(BLUES)),
              aspect="auto")  # fmt: skip
    for i in range(len(CONFIGS)):
        for j in range(len(HEATMAP_ATTACKS)):
            v = grid[i][j]
            pct = int(v * 100 + 0.5)  # half up, as in the tables (f"{12.5:.0f}" gives 12)
            ax.text(j, i, str(pct), ha="center", va="center", fontsize=8,
                    color="white" if v >= 0.3 else INK)  # fmt: skip
    ax.set_xticks(range(len(HEATMAP_ATTACKS)), [t["attacks"][a] for a in HEATMAP_ATTACKS],
                  fontsize=7.5)  # fmt: skip
    ax.set_yticks(range(len(CONFIGS)), [_name(c) for c in CONFIGS])
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    _save(fig, fig_dir, name)  # no title: the caption in the text names the figure
    plt.close(fig)


def fig_hybrid(asr: list[dict[str, str]], fig_dir: Path, t: dict[str, Any], name: str,
               doc: Doc | None = None) -> None:  # fmt: skip
    plt = _plt()
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
    for ax, group, title in zip(axes, ("id", "semantic"), t["hybrid_panels"], strict=True):
        cell = {(r["config"], r["attack_id"]): r for r in asr
                if r["by"] == "group" and r["value"] == group}  # fmt: skip
        series = []
        for label, suffix in zip(t["hybrid_series"], ("", "+presidio"), strict=True):
            vals, lo, hi = zip(*(_pooled(cell, c + suffix, INJECTIONS, doc, group)
                                 for c in CONFIGS), strict=True)  # fmt: skip
            series.append((label, list(vals), list(lo), list(hi)))
        _bars(ax, [_name(c) for c in CONFIGS], series)
        ax.set_title(title, loc="left", fontsize=9.5, color=INK)
        ax.tick_params(axis="x", rotation=35)
        for tick in ax.get_xticklabels():
            tick.set_ha("right")
    axes[0].set_ylabel(t["hybrid_y_doc" if doc else "hybrid_y"])
    axes[0].set_ylim(0, 1)
    axes[0].legend(frameon=False, loc="upper left")
    _save(fig, fig_dir, name)
    plt.close(fig)


def fig_detectors(detect: list[dict[str, str]], fig_dir: Path, t: dict[str, Any],
                  name: str) -> None:  # fmt: skip
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
    _bars(ax, [t["attacks"][g] for g in groups], series, labels=True)  # zeros are the finding
    ax.tick_params(axis="x", labelsize=7.5)
    ax.set_ylim(0, 1)
    ax.set_ylabel(t["det_y"])
    ax.legend(frameon=False, loc="upper left")
    ax.set_title(t["det_title"], loc="left", fontsize=9.5, color=INK)
    _save(fig, fig_dir, name)
    plt.close(fig)


def fig_clean(metrics: list[dict[str, str]], fig_dir: Path, t: dict[str, Any], name: str) -> None:
    plt = _plt()
    cell = {(r["config"], r["lang"]): r for r in metrics if r["subset"] == "all"}
    series = []
    for label, lang in zip(t["clean_series"], ("en", "uk"), strict=True):
        rows = [cell[(c, lang)] for c in CONFIGS]
        series.append((label, [float(r["acc"]) for r in rows], [float(r["acc_lo"]) for r in rows],
                       [float(r["acc_hi"]) for r in rows]))  # fmt: skip
    fig, ax = plt.subplots(figsize=(9, 3.4))
    _bars(ax, [_name(c) for c in CONFIGS], series, labels=True)
    ax.tick_params(axis="x", rotation=25)
    for tick in ax.get_xticklabels():
        tick.set_ha("right")
    ax.set_ylim(0, 1.08)
    ax.set_ylabel(t["clean_y"])
    ax.legend(frameon=False, loc="lower left", ncols=2)
    ax.set_title(t["clean_title"], loc="left", fontsize=9.5, color=INK)
    _save(fig, fig_dir, name)
    plt.close(fig)


def fig_defenses(asr: list[dict[str, str]], fig_dir: Path, t: dict[str, Any], name: str,
                 doc: Doc | None = None) -> None:  # fmt: skip
    plt = _plt()
    cell = {(r["config"], r["attack_id"]): r for r in asr if r["by"] == "all"}
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
    for ax, attacks, title in zip(axes, (["A3/A1", "A3/A2"], ["A1", "A2"]), t["def_panels"],
                                  strict=True):  # fmt: skip
        series = []
        for label, dset in zip(t["def_series"], ("none", "D1", "D2", "D1,D2"), strict=True):
            vals, lo, hi = zip(*(_pooled(cell, f"{c}@{dset}", attacks, doc)
                                 for c in D1_CONFIGS), strict=True)  # fmt: skip
            series.append((label, list(vals), list(lo), list(hi)))
        _bars(ax, [_name(c) for c in D1_CONFIGS], series, colors=[BASELINE, *SERIES],
              labels=True)  # fmt: skip
        ax.set_title(title, loc="left", fontsize=9.5, color=INK)
    axes[0].set_ylabel(t["def_y_doc" if doc else "def_y"])
    axes[0].set_ylim(0, 0.65 if doc else 0.6)  # document CIs reach higher
    fig.legend(*axes[0].get_legend_handles_labels(), frameon=False, loc="lower center",
               ncols=4, bbox_to_anchor=(0.5, -0.06))  # fmt: skip
    _save(fig, fig_dir, name)
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
    p.add_argument("--lang", choices=sorted(TEXT), default="uk")
    p.add_argument("--pooled", type=Path, help="research.analyze_pooled outputs (<dir>/full, "
                   "<dir>/defenses): bars get CIs by source document instead of Wilson")  # fmt: skip
    args = p.parse_args(argv)
    t, d = TEXT[args.lang], args.fig_dir
    uk = args.lang == "uk"  # thesis numbering only for the Ukrainian set
    asr = _read(args.analysis / "full/summary/asr.csv")
    fig_heatmap(asr, d, t, "fig3_asr_heatmap" if uk else "asr_heatmap")
    pool = args.pooled
    fig_hybrid(asr, d, t, "fig4_hybrid_by_group" if uk else "hybrid_by_group",
               _read_doc(pool / "full/summary/pooled.csv" if pool else None))  # fmt: skip
    fig_detectors(_read(args.analysis / "detect/summary/detect.csv"), d, t,
                  "fig5_detectors" if uk else "detectors")  # fmt: skip
    fig_clean(_read(args.results / "wp2_summary/summary/metrics.csv"), d, t,
              "fig_clean_accuracy" if uk else "clean_accuracy")  # fmt: skip
    fig_defenses(_read(args.analysis / "defenses/summary/asr.csv"), d, t,
                 "fig_defense_effect" if uk else "defense_effect",
                 _read_doc(pool / "defenses/summary/pooled.csv" if pool else None))  # fmt: skip
    if uk:
        table6(args.analysis, args.results, d / "table6_defense_cost.md")
    print(f"wrote {args.lang} figures to {d}")


if __name__ == "__main__":
    main()
