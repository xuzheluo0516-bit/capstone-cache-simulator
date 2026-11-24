"""Ablation of RW-CSF: remove one ingredient at a time at a FIXED half-life H.

Variants (all differ from the full policy in exactly one place):
  CUSTOM          full policy                 P = F * dT / s
  ABL_NO_LATENCY  dT replaced by 1            P = F / s
  ABL_NO_SIZE     s replaced by 1             P = F * dT
  ABL_NO_DECAY    H = infinity                P = (cumulative count) * dT / s

H is given with --half-life and must be the value chosen by run_h_tuning.py
(never tuned here). Output: ablation_table.csv (percent change of average
response time relative to the full policy, mean over capacities and seeds, one
column per workload) and ablation_by_capacity.csv. Positive = the variant is
slower than the full policy, i.e. the removed ingredient helps.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    WORKLOADS, build_registry, mean, mean_response_by, percent_change,
    run_seeds, validate_formal_seeds, validate_half_life, write_csv,
)

VARIANTS = ("ABL_NO_LATENCY", "ABL_NO_SIZE", "ABL_NO_DECAY")
FULL = "CUSTOM"


def build_tables(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (main table rows, per-capacity rows) from summary rows."""
    by_cap = mean_response_by(rows, ("policy", "workload", "capacity_KiB"))
    capacities = sorted({float(key[2]) for key in by_cap})
    detail: list[dict] = []
    main: list[dict] = []
    for variant in VARIANTS:
        line = {"variant": variant}
        for workload in WORKLOADS:
            changes = []
            for capacity in capacities:
                full = _lookup(by_cap, FULL, workload, capacity)
                value = _lookup(by_cap, variant, workload, capacity)
                change = percent_change(value, full)
                changes.append(change)
                detail.append({
                    "variant": variant, "workload": workload,
                    "capacity_KiB": capacity, "full_ms": full,
                    "variant_ms": value, "percent_change": change,
                })
            full_mean = mean([_lookup(by_cap, FULL, workload, c) for c in capacities])
            var_mean = mean([_lookup(by_cap, variant, workload, c) for c in capacities])
            line[workload] = percent_change(var_mean, full_mean)
        main.append(line)
    return main, detail


def _lookup(table: dict, policy: str, workload: str, capacity: float) -> float:
    for (p, w, c), value in table.items():
        if p == policy and w == workload and float(c) == capacity:
            return value
    raise KeyError((policy, workload, capacity))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--half-life", type=float, required=True,
                        help="the H chosen by run_h_tuning.py")
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    parser.add_argument("--scale", default="large", choices=("small", "medium", "large"))
    args = parser.parse_args()
    validate_formal_seeds(parser, args.seeds)
    validate_half_life(parser, args.half_life)

    registry, parameters = build_registry(args.half_life)
    rows = run_seeds(
        args.output_dir, args.seeds, [FULL, *VARIANTS], registry, parameters, args.scale
    )
    main_rows, detail_rows = build_tables(rows)
    write_csv(args.output_dir / "ablation_table.csv", ("variant", *WORKLOADS), main_rows)
    write_csv(
        args.output_dir / "ablation_by_capacity.csv",
        ("variant", "workload", "capacity_KiB", "full_ms", "variant_ms", "percent_change"),
        detail_rows,
    )
    print(f"H={args.half_life}  seeds={list(args.seeds)}  scale={args.scale}")
    print("percent change of avg response time vs full policy (positive = worse):")
    print(f"{'variant':<16}" + "".join(f"{w:>12}" for w in WORKLOADS))
    for line in main_rows:
        print(f"{line['variant']:<16}" + "".join(f"{line[w]:>11.2f}%" for w in WORKLOADS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
