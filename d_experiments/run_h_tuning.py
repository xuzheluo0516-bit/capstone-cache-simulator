"""H sensitivity experiment for RW-CSF (half-life of the recency weighting).

PRE-REGISTERED PROTOCOL (written before any tuning run; do not edit afterwards)
------------------------------------------------------------------------------
* Candidate half-lives (in requests), fixed in advance: H in {5, 20, 100, 500}.
  No value is added after seeing results.
* Tuning data: generated with TUNING_SEED, which differs from every seed used
  for the formal experiments. Scale: "large" (1440 requests per workload).
* All five default capacities (32/128/256/512/1024 KiB) and all three
  workloads (repeated, sequential, mixed) are used.
* Selection rule: for each H, take the mean average-response-time (ms) over
  the capacities within each workload, then the mean of those three workload
  means. The H with the smallest value wins; a tie goes to the smaller H. The
  chosen H is then fixed for all formal runs and is NOT tuned per workload.
* FIFO/LRU/LFU/GDSF run on the same data only as reference lines for the plot;
  they play no part in the selection.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from cache_simulator.cli import POLICY_REGISTRY
from cache_simulator.experiments import run_suite
from cache_simulator.gdsf import GDSFPolicy
from cache_simulator.rwcsf import RWCSFPolicy
from common import TUNING_SEED, write_manifest

H_VALUES = (5, 20, 100, 500)  # fixed in advance
TUNING_COUNTS = {"large": 1440}
REFERENCE_POLICIES = ("FIFO", "LRU", "LFU", "GDSF")
PROTOCOL = (
    "mean over capacities per workload, then mean over the three workloads "
    "of average_response_ms; smallest wins; tie -> smaller H"
)


def variant_name(half_life: int) -> str:
    return f"RWCSF_H{half_life}"


def select_half_life(rows: list[dict]) -> tuple[int, dict[int, float]]:
    """Apply the pre-registered selection rule to summary.csv rows."""
    per_workload: dict[tuple[int, str], list[float]] = defaultdict(list)
    for row in rows:
        for half_life in H_VALUES:
            if row["policy"] == variant_name(half_life):
                per_workload[(half_life, row["workload"])].append(
                    float(row["average_response_ms"])
                )
    scores: dict[int, float] = {}
    for half_life in H_VALUES:
        means = [
            sum(values) / len(values)
            for (h, _), values in per_workload.items()
            if h == half_life
        ]
        if len(means) != 3:
            raise RuntimeError(f"expected 3 workloads for H={half_life}, got {len(means)}")
        scores[half_life] = sum(means) / len(means)
    best = min(H_VALUES, key=lambda h: (scores[h], h))
    return best, scores


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=TUNING_SEED)
    args = parser.parse_args()
    if args.seed != TUNING_SEED:
        parser.error(
            f"--seed is fixed at {TUNING_SEED} by the tuning pre-registration; "
            "a seed used by formal experiments must not select H"
        )

    registry = {**POLICY_REGISTRY, "GDSF": GDSFPolicy}
    parameters = {}
    for half_life in H_VALUES:
        registry[variant_name(half_life)] = RWCSFPolicy
        parameters[variant_name(half_life)] = {"half_life": half_life}
    policies = list(REFERENCE_POLICIES) + [variant_name(h) for h in H_VALUES]
    registry["GDSF"] = GDSFPolicy

    manifest = run_suite(
        args.output_dir, seed=args.seed, counts=TUNING_COUNTS,
        policies=policies, registry=registry, policy_parameters=parameters,
    )
    write_manifest(args.output_dir / "manifest.json", manifest)
    with (args.output_dir / "summary.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    best, scores = select_half_life(rows)
    result = {
        "protocol": PROTOCOL, "candidates": list(H_VALUES), "seed": args.seed,
        "scores_ms": {str(h): scores[h] for h in H_VALUES}, "chosen_half_life": best,
        "source_sha256": manifest["source_sha256"],
    }
    (args.output_dir / "h_choice.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"seed={args.seed}  runs={manifest['completed_runs']}")
    for half_life in H_VALUES:
        print(f"  H={half_life:>4}: {scores[half_life]:.4f} ms")
    print(f"chosen H = {best}   (rule: {PROTOCOL})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
