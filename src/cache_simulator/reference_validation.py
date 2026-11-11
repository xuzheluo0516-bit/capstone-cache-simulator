"""Semantic comparison of generated reference traces against expected CSVs."""

from __future__ import annotations

import argparse
import csv
import io
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .engine import DEFAULT_CAPACITY_BYTES, DEFAULT_HIT_LATENCY_MS, SharedCacheEngine
from .input_parser import load_inputs
from .metrics import ClientMetrics, MetricsAccumulator
from .output import OUTPUT_FIELDS, render_events
from .policies import FIFOPolicy, LFUPolicy, LRUPolicy

POLICIES = {
    "FIFO": FIFOPolicy,
    "LRU": LRUPolicy,
    "LFU": LFUPolicy,
}
EXPECTED_FILES = {
    "FIFO": "expected_fifo.csv",
    "LRU": "expected_lru.csv",
    "LFU": "expected_lfu.csv",
}
INTEGER_FIELDS = {"step", "cumulative_origin_bytes", "cumulative_hits"}
NUMERIC_FIELDS = {"cache_used_KiB", "response_ms"}


@dataclass(frozen=True, slots=True)
class ReferenceReport:
    policy: str
    requests: int
    hits: int
    misses: int
    request_hit_rate: float | None
    byte_hit_rate: float | None
    origin_bytes: int
    average_response_ms: float | None
    per_client: tuple[ClientMetrics, ...]


class ReferenceMismatchError(AssertionError):
    """Raised when expected and actual CSV differ semantically."""


def _read_rows(text: str, *, label: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if reader.fieldnames is None:
            raise ReferenceMismatchError(f"{label}: missing CSV header")
        rows = list(reader)
    except csv.Error as exc:
        raise ReferenceMismatchError(f"{label}: invalid CSV: {exc}") from exc
    return list(reader.fieldnames), rows


def compare_csv_text(expected: str, actual: str, *, policy: str) -> None:
    """Compare decoded CSV values, ignoring quoting and newline conventions."""
    expected_header, expected_rows = _read_rows(expected, label=f"{policy} expected")
    actual_header, actual_rows = _read_rows(actual, label=f"{policy} actual")

    if expected_header != list(OUTPUT_FIELDS):
        raise ReferenceMismatchError(
            f"{policy}: expected file header/order is invalid: {expected_header!r}"
        )
    if actual_header != expected_header:
        raise ReferenceMismatchError(
            f"{policy}: header mismatch; expected {expected_header!r}, "
            f"actual {actual_header!r}"
        )
    if len(expected_rows) != len(actual_rows):
        raise ReferenceMismatchError(
            f"{policy}: row count mismatch; expected {len(expected_rows)}, "
            f"actual {len(actual_rows)}"
        )

    for row_number, (expected_row, actual_row) in enumerate(
        zip(expected_rows, actual_rows), start=1
    ):
        step = expected_row.get("step", str(row_number))
        for field in expected_header:
            expected_value = expected_row[field]
            actual_value = actual_row[field]
            try:
                if field in INTEGER_FIELDS:
                    matches = int(expected_value) == int(actual_value)
                elif field in NUMERIC_FIELDS:
                    matches = Decimal(expected_value) == Decimal(actual_value)
                else:
                    matches = expected_value == actual_value
            except (ValueError, InvalidOperation):
                matches = False
            if not matches:
                raise ReferenceMismatchError(
                    f"{policy} step {step} field {field}: "
                    f"expected {expected_value!r}, actual {actual_value!r}"
                )


def validate_reference_run(
    reference_dir: str | Path,
    policy_name: str,
    *,
    capacity_bytes: int = DEFAULT_CAPACITY_BYTES,
    hit_latency_ms: float = DEFAULT_HIT_LATENCY_MS,
) -> ReferenceReport:
    """Run one real policy and compare every output field to its expected CSV."""
    reference_dir = Path(reference_dir)
    inputs = load_inputs(
        reference_dir / "resources.csv",
        reference_dir / "requests_reference.csv",
    )
    engine = SharedCacheEngine(
        inputs.resources,
        POLICIES[policy_name](),
        capacity_bytes=capacity_bytes,
        hit_latency_ms=hit_latency_ms,
    )
    events = engine.process_all(inputs.requests)
    metrics = MetricsAccumulator(inputs.resources, capacity_bytes=capacity_bytes)
    snapshots = metrics.consume_all(events)
    actual_csv = render_events(events, snapshots)
    expected_csv = (reference_dir / EXPECTED_FILES[policy_name]).read_text(
        encoding="utf-8-sig"
    )
    compare_csv_text(expected_csv, actual_csv, policy=policy_name)

    summary = metrics.summary
    return ReferenceReport(
        policy=policy_name,
        requests=summary.requests,
        hits=summary.hits,
        misses=summary.misses,
        request_hit_rate=summary.request_hit_rate,
        byte_hit_rate=summary.byte_hit_rate,
        origin_bytes=summary.origin_bytes,
        average_response_ms=summary.average_response_ms,
        per_client=summary.per_client,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cache_simulator.reference_validation",
        description="Run FIFO/LRU/LFU against the instructor reference CSVs.",
    )
    parser.add_argument(
        "--reference-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data" / "reference",
    )
    parser.add_argument("--capacity", type=int, default=DEFAULT_CAPACITY_BYTES)
    parser.add_argument("--hit-latency", type=float, default=DEFAULT_HIT_LATENCY_MS)
    args = parser.parse_args(argv)

    try:
        for policy_name in ("FIFO", "LRU", "LFU"):
            report = validate_reference_run(
                args.reference_dir,
                policy_name,
                capacity_bytes=args.capacity,
                hit_latency_ms=args.hit_latency,
            )
            hit_rate = (
                "N/A"
                if report.request_hit_rate is None
                else f"{report.request_hit_rate * 100:.2f}%"
            )
            byte_rate = (
                "N/A"
                if report.byte_hit_rate is None
                else f"{report.byte_hit_rate * 100:.2f}%"
            )
            average = (
                "N/A"
                if report.average_response_ms is None
                else f"{report.average_response_ms:.2f} ms"
            )
            print(
                f"PASS {policy_name}: {report.requests} requests, "
                f"{report.hits} hits, {report.misses} misses, "
                f"request hit rate {hit_rate}, byte hit rate {byte_rate}, "
                f"origin {report.origin_bytes} B, average {average}"
            )
            for client in report.per_client:
                client_rate = (
                    "N/A" if client.request_hit_rate is None
                    else f"{client.request_hit_rate * 100:.2f}%"
                )
                client_average = (
                    "N/A" if client.average_response_ms is None
                    else f"{client.average_response_ms:.2f} ms"
                )
                print(
                    f"  {client.client_id}: {client.hits}/{client.requests} hits "
                    f"({client_rate}), average {client_average}"
                )
    except (OSError, ValueError, ReferenceMismatchError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
