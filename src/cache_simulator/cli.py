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
from .policies import FIFOPolicy, LFUPolicy, LRUPolicy

# Maps the public --policy name to a zero-argument policy constructor.
POLICY_REGISTRY: dict[str, Callable[[], EvictionPolicy]] = {
    "FIFO": FIFOPolicy,
    "LRU": LRUPolicy,
    "LFU": LFUPolicy,
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


def render_events(results: Sequence[RequestResult]) -> str:
    """Return a minimal, per-event human-readable view.

    This is the hand-off point for B's Output/Metrics modules. It only echoes
    facts already present on each event and computes no aggregate statistics.
    B's formatter is expected to replace this once the output module is ready.
    """
    columns = (
        "step",
        "client_id",
        "result",
        "response_ms",
        "origin_bytes",
        "cache_used_bytes",
    )
    lines = ["\t".join(columns)]
    for event in results:
        values = (
            event.step,
            event.client_id,
            event.result,
            event.response_ms,
            event.origin_bytes,
            event.cache_used_bytes,
        )
        lines.append("\t".join(str(value) for value in values))
    return "\n".join(lines)


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

    print(render_events(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
