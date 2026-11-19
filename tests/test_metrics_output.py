from __future__ import annotations

import csv
import io
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from cache_simulator.engine import SharedCacheEngine
from cache_simulator.metrics import MetricsAccumulator
from cache_simulator.models import Request, Resource, ResourceKey
from cache_simulator.output import OUTPUT_FIELDS, ResourceLabels, render_events
from cache_simulator.policies import FIFOPolicy


def make_resource(path: str, size: int, latency: float = 10.0) -> Resource:
    key = ResourceKey("https", "metrics.example", path)
    return Resource(key, 200, "text/plain", size, latency, "public")


def make_request(resource: Resource, step: int, client: str) -> Request:
    return Request(
        datetime(2026, 11, 11, 9, 0, tzinfo=timezone.utc),
        client,
        "GET",
        resource.key,
        step,
        step + 1,
    )


class MetricsAndOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.small = make_resource("/small", 1500, 10)
        self.medium = make_resource("/medium", 700, 20)
        self.oversized = make_resource("/oversized", 3000, 30)
        self.resources = {
            item.key: item for item in (self.small, self.medium, self.oversized)
        }
        requests = (
            make_request(self.small, 1, "client-a"),
            make_request(self.small, 2, "client-b"),
            make_request(self.medium, 3, "client-a"),
            make_request(self.oversized, 4, "client-a"),
            make_request(self.medium, 5, "client-b"),
        )
        engine = SharedCacheEngine(
            self.resources, FIFOPolicy(), capacity_bytes=2000, hit_latency_ms=5
        )
        self.events = engine.process_all(requests)

    def test_global_and_uneven_per_client_metrics(self) -> None:
        metrics = MetricsAccumulator(self.resources, capacity_bytes=2000)
        snapshots = metrics.consume_all(self.events)
        summary = metrics.summary

        self.assertEqual((summary.requests, summary.hits, summary.misses), (5, 2, 3))
        self.assertEqual(summary.request_bytes, 7400)
        self.assertEqual(summary.hit_bytes, 2200)
        self.assertEqual(summary.origin_bytes, 5200)
        self.assertAlmostEqual(summary.request_hit_rate, 0.4)
        self.assertAlmostEqual(summary.byte_hit_rate, 2200 / 7400)
        self.assertAlmostEqual(summary.average_response_ms, 14.0)
        self.assertEqual(
            [(c.client_id, c.requests, c.hits) for c in summary.per_client],
            [("client-a", 3, 0), ("client-b", 2, 2)],
        )
        self.assertAlmostEqual(summary.per_client[0].average_response_ms, 20.0)
        self.assertAlmostEqual(summary.per_client[1].average_response_ms, 5.0)
        self.assertEqual(
            [(s.cumulative_origin_bytes, s.cumulative_hits) for s in snapshots],
            [(1500, 0), (1500, 1), (2200, 1), (5200, 1), (5200, 2)],
        )

        self.assertEqual(summary.hits + summary.misses, summary.requests)
        self.assertEqual(sum(c.requests for c in summary.per_client), summary.requests)
        self.assertEqual(sum(c.hits for c in summary.per_client), summary.hits)
        self.assertEqual(summary.hit_bytes + summary.origin_bytes, summary.request_bytes)
        self.assertTrue(all(e.cache_used_bytes <= 2000 for e in self.events))

    def test_metrics_reject_duplicate_event_consumption(self) -> None:
        metrics = MetricsAccumulator(self.resources, capacity_bytes=2000)
        metrics.consume(self.events[0])
        with self.assertRaisesRegex(ValueError, "already counted"):
            metrics.consume(self.events[0])
        self.assertEqual(metrics.summary.requests, 1)

    def test_metrics_reject_capacity_invariant_violation(self) -> None:
        metrics = MetricsAccumulator(self.resources, capacity_bytes=2000)
        invalid = replace(self.events[0], cache_used_bytes=2001)
        with self.assertRaisesRegex(ValueError, "exceeds capacity"):
            metrics.consume(invalid)

    def test_empty_trace_has_independent_undefined_metrics(self) -> None:
        metrics = MetricsAccumulator({}, capacity_bytes=1024)
        summary = metrics.summary
        self.assertEqual((summary.requests, summary.hits, summary.misses), (0, 0, 0))
        self.assertEqual(summary.origin_bytes, 0)
        self.assertIsNone(summary.request_hit_rate)
        self.assertIsNone(summary.byte_hit_rate)
        self.assertIsNone(summary.average_response_ms)
        self.assertEqual(summary.per_client, ())

    def test_zero_total_bytes_only_makes_byte_hit_rate_undefined(self) -> None:
        empty = make_resource("/zero", 0, 2)
        engine = SharedCacheEngine({empty.key: empty}, FIFOPolicy(), capacity_bytes=10)
        events = engine.process_all((make_request(empty, 1, "zero-client"),))
        metrics = MetricsAccumulator({empty.key: empty}, capacity_bytes=10)
        metrics.consume_all(events)
        summary = metrics.summary
        self.assertEqual(summary.requests, 1)
        self.assertEqual(summary.request_hit_rate, 0.0)
        self.assertIsNone(summary.byte_hit_rate)
        self.assertEqual(summary.average_response_ms, 2.0)
        self.assertEqual(summary.origin_bytes, 0)

    def test_output_has_exact_ten_columns_and_fractional_kib(self) -> None:
        metrics = MetricsAccumulator(self.resources, capacity_bytes=2000)
        snapshots = metrics.consume_all(self.events)
        rendered = render_events(self.events, snapshots)
        rows = list(csv.DictReader(io.StringIO(rendered, newline=""), strict=True))

        self.assertEqual(list(rows[0]), list(OUTPUT_FIELDS))
        self.assertEqual(len(OUTPUT_FIELDS), 10)
        self.assertEqual(rows[0]["resource_id"], "A")
        self.assertEqual(rows[0]["cache_used_KiB"], "1.46484375")
        self.assertEqual(rows[0]["evicted"], "-")
        self.assertEqual(rows[0]["cumulative_origin_bytes"], "1500")
        self.assertEqual(rows[1]["result"], "HIT")
        self.assertEqual(rows[2]["evicted"], "A")
        self.assertEqual(rows[2]["cache_contents_oldest_first"], "B")
        self.assertEqual(rows[3]["cache_contents_oldest_first"], "B")

    def test_serializer_requires_matching_read_only_snapshots(self) -> None:
        metrics = MetricsAccumulator(self.resources, capacity_bytes=2000)
        snapshots = metrics.consume_all(self.events)
        before = metrics.summary
        with self.assertRaisesRegex(ValueError, "exactly one"):
            render_events(self.events, snapshots[:-1])
        render_events(self.events, snapshots)
        self.assertEqual(metrics.summary, before)

    def test_resource_labels_expand_beyond_z(self) -> None:
        labels = ResourceLabels()
        values = [
            labels.label(ResourceKey("https", "example.com", f"/{i}"))
            for i in range(28)
        ]
        self.assertEqual(values[0], "A")
        self.assertEqual(values[25], "Z")
        self.assertEqual(values[26:], ["AA", "AB"])


if __name__ == "__main__":
    unittest.main()
