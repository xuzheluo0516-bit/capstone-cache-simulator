"""Figures for the course-trace experiment, drawn from run_course.py's CSV tables."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from make_plots import COLORS, GRID, INK2, LABELS, MARKERS, SURFACE  # noqa: E402  (also sets the style)

WORKLOADS = ("sequential", "repetitive", "mixed")
POLICIES = ("FIFO", "LRU", "LFU", "GDSF", "CUSTOM")
STANDARD_KIB = 5120
TICKS = {100: "100K", 500: "500K", 1024: "1M", 2048: "2M", 5120: "5M", 10240: "10M"}


def read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _legend(fig, policies=POLICIES) -> None:
    handles = [plt.Line2D([0], [0], color=COLORS[p], marker=MARKERS[p], lw=2, markersize=7,
                          markeredgecolor=SURFACE, label=LABELS[p]) for p in policies]
    fig.legend(handles=handles, loc="lower center", ncol=len(handles), fontsize=9)


def metric_vs_capacity(rows, metric, ylabel, path, factor=1.0, title=None) -> Path:
    fig, axes = plt.subplots(1, 3, figsize=(12.6, 4.0))
    for ax, workload in zip(axes, WORKLOADS):
        for policy in POLICIES:
            pts = sorted((int(r["capacity_KiB"]), float(r[metric]) * factor) for r in rows
                         if r["workload"] == workload and r["policy"] == policy)
            xs, ys = zip(*pts)
            ax.plot(xs, ys, color=COLORS[policy], marker=MARKERS[policy], markersize=6,
                    markeredgecolor=SURFACE, markeredgewidth=1,
                    lw=2.4 if policy == "CUSTOM" else 1.8, zorder=3)
        ax.set_xscale("log", base=2)
        ax.set_xticks(list(TICKS))
        ax.set_xticklabels(list(TICKS.values()))
        ax.minorticks_off()
        ax.set_xlabel("Cache capacity (K = KiB, M = MiB; log scale)")
        ax.set_title(workload)
    axes[0].set_ylabel(ylabel)
    if title:
        fig.suptitle(title, x=0.01, ha="left", fontweight="bold")
    _legend(fig)
    fig.tight_layout(rect=(0, 0.07, 1, 0.95 if title else 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def workload_distribution(dist, summary, path) -> Path:
    fig, axes = plt.subplots(1, 3, figsize=(12.6, 4.2))
    for ax, workload in zip(axes, WORKLOADS):
        rows = [r for r in dist if r["workload"] == workload]
        ys = [int(r["requests"]) for r in rows]
        big = [int(r["size_bytes"]) > STANDARD_KIB * 1024 for r in rows]
        ax.bar(range(len(ys)), ys, color=[INK2 if b else COLORS["FIFO"] for b in big],
               edgecolor=SURFACE, linewidth=1, zorder=3)
        ax.set_xlabel("Resources, most requested first")
        ax.set_xticks([])
        row = next(r for r in summary if r["workload"] == workload)
        ax.set_title(f"{workload}: {int(row['distinct_resources'])} resources, "
                     f"{int(row['distinct_clients'])} clients")
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("Requests (out of 3000)")
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLORS["FIFO"], label="fits in 5 MiB"),
               plt.Rectangle((0, 0), 1, 1, color=INK2, label="larger than 5 MiB (never cached)")]
    fig.legend(handles=handles, loc="lower center", ncol=2, fontsize=9)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def policy_comparison(rows, path, capacity=STANDARD_KIB) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.0))
    for ax, (metric, label, factor) in zip(
            axes, (("average_response_ms", "Average response time (ms)", 1.0),
                   ("request_hit_rate", "Request hit rate (%)", 100.0))):
        width = 0.8 / len(POLICIES)
        for i, policy in enumerate(POLICIES):
            vals = [float(next(r for r in rows if r["workload"] == w and r["policy"] == policy
                               and int(r["capacity_KiB"]) == capacity)[metric]) * factor
                    for w in WORKLOADS]
            xs = [k + (i - (len(POLICIES) - 1) / 2) * width for k in range(len(WORKLOADS))]
            ax.bar(xs, vals, width=width * 0.92, color=COLORS[policy], edgecolor=SURFACE,
                   linewidth=1, zorder=3)
        ax.set_xticks(range(len(WORKLOADS)))
        ax.set_xticklabels(WORKLOADS)
        ax.set_ylabel(label)
        ax.grid(axis="x", visible=False)
    axes[0].set_title(f"Policy comparison at {capacity // 1024} MiB")
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLORS[p], label=LABELS[p]) for p in POLICIES]
    fig.legend(handles=handles, loc="lower center", ncol=len(handles), fontsize=9)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def per_client(clients, path, capacity=STANDARD_KIB, workload="mixed") -> Path:
    rows = [r for r in clients if r["workload"] == workload and int(r["capacity_KiB"]) == capacity]
    ids = sorted({r["client_id"] for r in rows})
    fig, axes = plt.subplots(1, 2, figsize=(max(9.0, 1.9 * len(ids) + 4), 4.0))
    for ax, (metric, label, factor) in zip(
            axes, (("request_hit_rate", "Request hit rate (%)", 100.0),
                   ("average_response_ms", "Average response time (ms)", 1.0))):
        width = 0.8 / len(POLICIES)
        for i, policy in enumerate(POLICIES):
            vals = [float(next(r for r in rows if r["client_id"] == c and r["policy"] == policy)[metric])
                    * factor for c in ids]
            xs = [k + (i - (len(POLICIES) - 1) / 2) * width for k in range(len(ids))]
            ax.bar(xs, vals, width=width * 0.92, color=COLORS[policy], edgecolor=SURFACE,
                   linewidth=1, zorder=3)
        ax.set_xticks(range(len(ids)))
        ax.set_xticklabels(ids, rotation=30, ha="right")
        ax.set_ylabel(label)
        ax.grid(axis="x", visible=False)
    axes[0].set_title(f"Per-client results, {workload} workload, {capacity // 1024} MiB")
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLORS[p], label=LABELS[p]) for p in POLICIES]
    fig.legend(handles=handles, loc="lower center", ncol=len(handles), fontsize=9)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--figures-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    args.figures_dir.mkdir(parents=True, exist_ok=True)
    runs = read(args.results_dir / "course_runs.csv")
    made = [
        workload_distribution(read(args.results_dir / "workload_distribution.csv"),
                              read(args.results_dir / "workload_summary.csv"),
                              args.figures_dir / "course_workload_distribution.png"),
        policy_comparison(runs, args.figures_dir / "course_policy_comparison_5MiB.png"),
        metric_vs_capacity(runs, "average_response_ms", "Average response time (ms)",
                           args.figures_dir / "course_response_time_vs_capacity.png"),
        metric_vs_capacity(runs, "request_hit_rate", "Request hit rate (%)",
                           args.figures_dir / "course_hit_rate_vs_capacity.png", factor=100.0),
        metric_vs_capacity(runs, "evictions", "Cache evictions (count)",
                           args.figures_dir / "course_evictions_vs_capacity.png"),
        per_client(read(args.results_dir / "course_clients.csv"),
                   args.figures_dir / "course_per_client_mixed_5MiB.png"),
    ]
    for path in made:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
