"""Read-only CSV serialization of engine events and metric snapshots."""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from decimal import Decimal

from .engine import RequestResult
from .metrics import MetricsSnapshot
from .models import ResourceKey

OUTPUT_FIELDS = (
    "step",
    "resource_id",
    "client_id",
    "result",
    "evicted",
    "cache_contents_oldest_first",
    "cache_used_KiB",
    "response_ms",
    "cumulative_origin_bytes",
    "cumulative_hits",
)


def _excel_label(index: int) -> str:
    """Convert a zero-based index to A..Z, AA..AZ, BA..."""
    if index < 0:
        raise ValueError("label index must be non-negative")
    result = ""
    number = index + 1
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _number(value: int | float | Decimal) -> str:
    """Format numeric CSV fields without needless trailing zeroes."""
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    text = format(decimal_value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


class ResourceLabels:
    """Assign stable resource IDs by first appearance in the request trace."""

    def __init__(self) -> None:
        self._labels: dict[ResourceKey, str] = {}

    def label(self, key: ResourceKey) -> str:
        if key not in self._labels:
            self._labels[key] = _excel_label(len(self._labels))
        return self._labels[key]


def render_events(
    events: Sequence[RequestResult],
    snapshots: Sequence[MetricsSnapshot],
) -> str:
    """Serialize events to the exact ten-column reference CSV schema.

    This function is intentionally read-only: cumulative counters are supplied
    by MetricsAccumulator snapshots and are never recalculated here.
    """
    if len(events) != len(snapshots):
        raise ValueError("each event must have exactly one metrics snapshot")

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(OUTPUT_FIELDS)
    labels = ResourceLabels()

    for event, snapshot in zip(events, snapshots):
        if event.step != snapshot.step:
            raise ValueError(
                f"snapshot step {snapshot.step} does not match event step {event.step}"
            )
        resource_id = labels.label(event.resource_key)
        evicted = ",".join(labels.label(key) for key in event.evicted) or "-"
        contents = (
            ",".join(labels.label(key) for key in event.cache_contents_oldest_first)
            or "-"
        )
        cache_used_kib = Decimal(event.cache_used_bytes) / Decimal(1024)
        writer.writerow(
            (
                event.step,
                resource_id,
                event.client_id,
                event.result,
                evicted,
                contents,
                _number(cache_used_kib),
                _number(event.response_ms),
                snapshot.cumulative_origin_bytes,
                snapshot.cumulative_hits,
            )
        )
    return output.getvalue()
