"""Main comparison: FIFO, LRU, LFU, GDSF and CUSTOM (RW-CSF) on every workload.

Runs run_suite once per seed (sub-directory seed_<N>), then writes
main_table.csv: mean and sample standard deviation over seeds of average
response time, request hit rate, byte hit rate and origin traffic for every
(workload, capacity, policy). H must be the value chosen by run_h_tuning.py.
Formal seeds must differ from the tuning seed.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    aggregate_fields, aggregate_summary, build_registry, run_seeds,
    validate_formal_seeds, validate_half_life, write_csv,
)

POLICIES = ("FIFO", "LRU", "LFU", "GDSF", "CUSTOM")
DEFAULT_SEEDS = (20261111, 20261112, 20261113, 20261114, 20261115)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--half-life", type=float, required=True,
                        help="the H chosen by run_h_tuning.py")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS))
    parser.add_argument("--scale", default="large", choices=("small", "medium", "large"))
    args = parser.parse_args()
    validate_formal_seeds(parser, args.seeds)
    validate_half_life(parser, args.half_life)

    registry, parameters = build_registry(args.half_life)
    rows = run_seeds(args.output_dir, args.seeds, POLICIES, registry, parameters, args.scale)
    table = aggregate_summary(rows)
    write_csv(args.output_dir / "main_table.csv", aggregate_fields(), table)
    print(f"H={args.half_life}  seeds={list(args.seeds)}  scale={args.scale}  "
          f"cells={len(table)}  -> {args.output_dir / 'main_table.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
