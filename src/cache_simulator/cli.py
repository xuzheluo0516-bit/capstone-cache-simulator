"""Command-line entry point for a single shared-cache simulation run."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from .engine import (
    DEFAULT_CAPACITY_BYTES,
    DEFAULT_HIT_LATENCY_MS,
    EvictionPolicy,
    PolicyContractError,
    RequestResult,
    SharedCacheEngine,
)
from .input_parser import InputValidationError, load_inputs
from .metrics import MetricsAccumulator
from .output import render_events
from .policies import FIFOPolicy, LFUPolicy, LRUPolicy
from .gdsf import GDSFPolicy
from .rwcsf import RWCSFPolicy

# Maps the public --policy name to a zero-argument policy constructor.
POLICY_REGISTRY: dict[str, Callable[[], EvictionPolicy]] = {
    "FIFO": FIFOPolicy,
    "LRU": LRUPolicy,
    "LFU": LFUPolicy,
    "CUSTOM": RWCSFPolicy,
    "GDSF": GDSFPolicy,
}

DEFAULT_POLICY_NAME = "LRU"


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for one simulation run."""
    parser = argparse.ArgumentParser(
        prog="cache_simulator",
        description="Run one trace-driven shared web cache simulation.",
    )
    parser.add_argument(
        "--resources",
        type=Path,
        required=True,
        help="Path to the resources CSV file.",
    )
    parser.add_argument(
        "--requests",
        type=Path,
        required=True,
        help="Path to the requests CSV file.",
    )
    parser.add_argument(
        "--capacity",
        type=int,
        default=DEFAULT_CAPACITY_BYTES,
        help="Cache capacity in bytes (default: %(default)s). Must be >= 0.",
    )
    parser.add_argument(
        "--hit-latency",
        type=float,
        default=DEFAULT_HIT_LATENCY_MS,
        help="Cache hit latency in milliseconds (default: %(default)s). "
        "Must be >= 0.",
    )
    parser.add_argument(
        "--policy",
        choices=sorted(POLICY_REGISTRY),
        default=DEFAULT_POLICY_NAME,
        help="Replacement policy to use (default: %(default)s).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one simulation and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.capacity < 0:
        parser.error("--capacity must be non-negative")
    if args.hit_latency < 0:
        parser.error("--hit-latency must be non-negative")
    if not args.resources.is_file():
        parser.error(f"resources file not found: {args.resources}")
    if not args.requests.is_file():
        parser.error(f"requests file not found: {args.requests}")

    try:
        simulation = load_inputs(args.resources, args.requests)
    except InputValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    policy = POLICY_REGISTRY[args.policy]()
    try:
        engine = SharedCacheEngine(
            simulation.resources,
            policy,
            capacity_bytes=args.capacity,
            hit_latency_ms=args.hit_latency,
        )
        results = engine.process_all(simulation.requests)
    except (PolicyContractError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    metrics = MetricsAccumulator(simulation.resources, capacity_bytes=args.capacity)
    snapshots = metrics.consume_all(results)
    print(render_events(results, snapshots), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
