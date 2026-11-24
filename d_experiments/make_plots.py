"""Figures for the report, drawn from the CSV tables (the tables are the data).

Inputs (in --results-dir): main_table.csv (run_main.py); per_client.csv
(analyze_fairness.py, optional); --tuning-dir with summary.csv (run_h_tuning.py,
optional). Colors are the validated categorical slots 1-5 in a fixed order, one
per policy, and every policy also has its own marker shape, so identity never
relies on color alone. Shaded bands / error bars are +-1 sample std over seeds.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

POLICIES = ("FIFO", "LRU", "LFU", "GDSF", "CUSTOM")
LABELS = {"FIFO": "FIFO", "LRU": "LRU", "LFU": "LFU", "GDSF": "GDSF",
          "CUSTOM": "RW-CSF (custom)"}
COLORS = {"FIFO": "#2a78d6", "LRU": "#eb6834", "LFU": "#1baf7a",
          "GDSF": "#eda100", "CUSTOM": "#e87ba4"}
MARKERS = {"FIFO": "o", "LRU": "s", "LFU": "^", "GDSF": "D", "CUSTOM": "P"}
WORKLOAD_ORDER = ("repeated", "sequential", "mixed")
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e3e2de"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "text.color": INK, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.edgecolor": GRID, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "legend.frameon": False,
})


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def workloads_in(rows: list[dict]) -> list[str]:
    found = {r["workload"] for r in rows}
    return [w for w in WORKLOAD_ORDER if w in found] + sorted(found - set(WORKLOAD_ORDER))


def policies_in(rows: list[dict]) -> list[str]:
    found = {r["policy"] for r in rows}
    return [p for p in POLICIES if p in found]


def single_workload(rows: list[dict], context: str = "per-client data") -> str:
    """Return the one workload in rows; refuse to mislabel mixed inputs."""
    found = sorted({r["workload"] for r in rows})
    if len(found) != 1:
        raise ValueError(f"{context} must contain exactly one workload, found {found}")
    return found[0]


def _legend(fig, policies: list[str]) -> None:
    handles = [
        plt.Line2D([0], [0], color=COLORS[p], marker=MARKERS[p], lw=2, markersize=7,
                   markeredgecolor=SURFACE, label=LABELS[p])
        for p in policies
    ]
    fig.legend(handles=handles, loc="lower center", ncol=len(handles), fontsize=9)


def metric_vs_capacity(rows, metric, ylabel, path, factor=1.0, title=None) -> None:
    workloads, policies = workloads_in(rows), policies_in(rows)
    fig, axes = plt.subplots(1, len(workloads), figsize=(4.2 * len(workloads), 4.0),
                             squeeze=False, sharey=False)
    for ax, workload in zip(axes[0], workloads):
        for policy in policies:
            pts = sorted(
                (float(r["capacity_KiB"]), float(r[f"{metric}_mean"]) * factor,
                 float(r[f"{metric}_std"]) * factor)
                for r in rows if r["workload"] == workload and r["policy"] == policy)
            xs, ys, sd = zip(*pts)
            ax.plot(xs, ys, color=COLORS[policy], marker=MARKERS[policy], markersize=6,
                    markeredgecolor=SURFACE, markeredgewidth=1,
                    lw=2.4 if policy == "CUSTOM" else 1.8, zorder=3)
            ax.fill_between(xs, [y - s for y, s in zip(ys, sd)],
                            [y + s for y, s in zip(ys, sd)],
                            color=COLORS[policy], alpha=0.12, lw=0)
        caps = sorted({float(r["capacity_KiB"]) for r in rows})
        ax.set_xscale("log", base=2)
        ax.set_xticks(caps)
        ax.set_xticklabels([f"{c:g}" for c in caps])
        ax.minorticks_off()
        ax.set_xlabel("Cache capacity (KiB, log scale)")
        ax.set_title(workload)
    axes[0][0].set_ylabel(ylabel)
    if title:
        fig.suptitle(title, x=0.01, ha="left", fontweight="bold")
    _legend(fig, policies)
    fig.tight_layout(rect=(0, 0.07, 1, 0.95 if title else 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)


def grouped_bars(categories, series, ylabel, path, title, fmt_pct=False) -> None:
    """series: {policy: [(mean, std) per category]}"""
    policies = [p for p in POLICIES if p in series]
    fig, ax = plt.subplots(figsize=(max(5.5, 1.9 * len(categories) + 2), 4.0))
    width = 0.8 / len(policies)
    for i, policy in enumerate(policies):
        xs = [c + (i - (len(policies) - 1) / 2) * width for c in range(len(categories))]
        ax.bar(xs, [m for m, _ in series[policy]], width=width * 0.92,
               yerr=[s for _, s in series[policy]], color=COLORS[policy],
               edgecolor=SURFACE, linewidth=1, error_kw={"lw": 1, "ecolor": INK2,
                                                         "capsize": 2}, zorder=3)
    ax.set_xticks(range(len(categories)))
    ax.set_xticklabels(categories)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(axis="x", visible=False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLORS[p], label=LABELS[p]) for p in policies]
    fig.legend(handles=handles, loc="lower center", ncol=len(handles), fontsize=9)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)


def byte_hit_bars(rows, capacity, path) -> None:
    workloads = workloads_in(rows)
    series = {}
    for policy in policies_in(rows):
        vals = []
        for workload in workloads:
            match = [r for r in rows if r["workload"] == workload and r["policy"] == policy
                     and float(r["capacity_KiB"]) == capacity]
            if len(match) != 1:
                raise ValueError(f"need one row for {workload}/{policy}/{capacity} KiB")
            vals.append((100 * float(match[0]["byte_hit_rate_mean"]),
                         100 * float(match[0]["byte_hit_rate_std"])))
        series[policy] = vals
    grouped_bars(workloads, series, "Byte hit rate (%)", path,
                 f"Byte hit rate at {capacity:g} KiB")


def per_client_figure_path(per_client, figures_dir) -> Path:
    return Path(figures_dir) / f"per_client_{single_workload(per_client)}.png"


def per_client_bars(per_client, capacity, path) -> Path:
    rows = [r for r in per_client if float(r["capacity_KiB"]) == capacity]
    if not rows:
        raise ValueError(f"no per-client rows at {capacity} KiB")
    workload = single_workload(rows)
    clients = sorted({r["client_id"] for r in rows})
    policies = policies_in(rows)
    fig, axes = plt.subplots(1, 2, figsize=(max(8.5, 2.6 * len(clients) + 3), 4.0))
    for ax, key, label, factor in (
        (axes[0], "hit_rate_mean", "Request hit rate (%)", 100),
        (axes[1], "avg_response_ms_mean", "Average response time (ms)", 1),
    ):
        width = 0.8 / len(policies)
        for i, policy in enumerate(policies):
            vals = []
            for client in clients:
                match = [r for r in rows if r["policy"] == policy and r["client_id"] == client]
                vals.append(float(match[0][key]) * factor if match else 0.0)
            xs = [c + (i - (len(policies) - 1) / 2) * width for c in range(len(clients))]
            ax.bar(xs, vals, width=width * 0.92, color=COLORS[policy],
                   edgecolor=SURFACE, linewidth=1, zorder=3)
        ax.set_xticks(range(len(clients)))
        ax.set_xticklabels(clients)
        ax.set_ylabel(label)
        ax.grid(axis="x", visible=False)
    axes[0].set_title(f"Per-client results, {workload} workload, {capacity:g} KiB")
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLORS[p], label=LABELS[p]) for p in policies]
    fig.legend(handles=handles, loc="lower center", ncol=len(handles), fontsize=9)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return Path(path)


def h_sensitivity(tuning_dir: Path, path: Path) -> None:
    rows = read_csv(tuning_dir / "summary.csv")
    workloads = workloads_in(rows)
    per: dict[tuple, list[float]] = defaultdict(list)
    for r in rows:
        per[(r["policy"], r["workload"])].append(float(r["average_response_ms"]))
    h_values = sorted(int(p[len("RWCSF_H"):]) for p in {r["policy"] for r in rows}
                      if p.startswith("RWCSF_H"))
    fig, axes = plt.subplots(1, len(workloads), figsize=(4.2 * len(workloads), 4.0),
                             squeeze=False)
    for ax, workload in zip(axes[0], workloads):
        ys = [sum(per[(f"RWCSF_H{h}", workload)]) / len(per[(f"RWCSF_H{h}", workload)])
              for h in h_values]
        ax.plot(h_values, ys, color=COLORS["CUSTOM"], marker=MARKERS["CUSTOM"], lw=2.4,
                markersize=7, markeredgecolor=SURFACE, zorder=3)
        for policy in ("LRU", "LFU", "GDSF"):
            if (policy, workload) in per:
                v = per[(policy, workload)]
                ax.axhline(sum(v) / len(v), color=COLORS[policy], lw=1.6, ls="--", zorder=2)
        ax.set_xscale("log")
        ax.set_xticks(h_values)
        ax.set_xticklabels([str(h) for h in h_values])
        ax.minorticks_off()
        ax.set_xlabel("Half-life H (requests, log scale)")
        ax.set_title(workload)
        # The y-axis does not start at zero, so state the real size of the effect.
        spread = (max(ys) - min(ys)) / min(ys) * 100 if min(ys) > 0 else float("nan")
        ax.text(1.0, 1.02, f"spread across H: {spread:.1f}%  (y-axis not from 0)",
                transform=ax.transAxes, ha="right", va="bottom", fontsize=8, color=INK2)
    axes[0][0].set_ylabel("Average response time (ms)\nmean over capacities")
    handles = [plt.Line2D([0], [0], color=COLORS["CUSTOM"], marker="P", lw=2,
                          label="RW-CSF (by H)")]
    handles += [plt.Line2D([0], [0], color=COLORS[p], lw=1.6, ls="--", label=LABELS[p])
                for p in ("LRU", "LFU", "GDSF")]
    fig.legend(handles=handles, loc="lower center", ncol=4, fontsize=9)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--figures-dir", type=Path, required=True)
    parser.add_argument("--bar-capacity", type=float, default=128.0,
                        help="capacity (KiB) for the bar charts")
    parser.add_argument("--tuning-dir", type=Path, default=None)
    args = parser.parse_args()
    args.figures_dir.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []

    main_rows = read_csv(args.results_dir / "main_table.csv")
    for metric, ylabel, name, factor in (
        ("request_hit_rate", "Request hit rate (%)", "hit_rate_vs_capacity.png", 100),
        ("average_response_ms", "Average response time (ms)", "response_time_vs_capacity.png", 1),
        ("origin_bytes", "Origin traffic (MiB)", "origin_traffic_vs_capacity.png", 1 / 2**20),
    ):
        metric_vs_capacity(main_rows, metric, ylabel, args.figures_dir / name, factor)
        made.append(args.figures_dir / name)
    byte_hit_bars(main_rows, args.bar_capacity, args.figures_dir / "byte_hit_rate_bars.png")
    made.append(args.figures_dir / "byte_hit_rate_bars.png")

    per_client_path = args.results_dir / "per_client.csv"
    if per_client_path.exists():
        per_client = read_csv(per_client_path)
        made.append(per_client_bars(
            per_client, args.bar_capacity, per_client_figure_path(per_client, args.figures_dir)))
    else:
        print("skipped per-client figure (run analyze_fairness.py first)")
    if args.tuning_dir is not None:
        h_sensitivity(args.tuning_dir, args.figures_dir / "h_sensitivity.png")
        made.append(args.figures_dir / "h_sensitivity.png")
    for path in made:
        print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
