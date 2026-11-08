from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from cache_simulator.engine import SharedCacheEngine
from cache_simulator.input_parser import load_inputs
from cache_simulator.models import Request, Resource, ResourceKey
from cache_simulator.policies import FIFOPolicy, LFUPolicy, LRUPolicy


def key(path: str) -> ResourceKey:
    return ResourceKey("https", "example.com", path)


def resource(path: str, size: int = 1) -> Resource:
    return Resource(
        key=key(path),
        status_code=200,
        content_type="text/plain",
        size_bytes=size,
        origin_latency_ms=10.0,
        cache_control="public",
    )


def request(path: str, sequence: int, client: str = "client-a") -> Request:
    return Request(
        timestamp=datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc),
        client_id=client,
        method="GET",
        key=key(path),
        sequence=sequence,
        source_line=sequence + 1,
    )


class FIFOPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = [resource("/a"), resource("/b"), resource("/c")]
        self.engine = SharedCacheEngine(
            {item.key: item for item in self.items},
            FIFOPolicy(),
            capacity_bytes=2,
        )

    def test_hit_does_not_change_fifo_victim_or_insertion_order(self) -> None:
        self.engine.process(request("/a", 1))
        self.engine.process(request("/b", 2))
        hit = self.engine.process(request("/a", 3, "client-b"))

        self.assertTrue(hit.hit)
        self.assertEqual(hit.cache_contents_oldest_first, (key("/a"), key("/b")))
        result = self.engine.process(request("/c", 4))
        self.assertEqual(result.evicted, (key("/a"),))
        self.assertEqual(result.cache_contents_oldest_first, (key("/b"), key("/c")))

    def test_fifo_evicts_multiple_entries_until_resource_fits(self) -> None:
        large = resource("/large", 3)
        engine = SharedCacheEngine(
            {item.key: item for item in (*self.items[:2], large)},
            FIFOPolicy(),
            capacity_bytes=3,
        )
        engine.process(request("/a", 1))
        engine.process(request("/b", 2))
        result = engine.process(request("/large", 3))

        self.assertEqual(result.evicted, (key("/a"), key("/b")))
        self.assertEqual(result.cache_contents_oldest_first, (key("/large"),))

    def test_fifo_reinsertion_gets_a_new_insertion_position(self) -> None:
        engine = SharedCacheEngine(
            {item.key: item for item in self.items},
            FIFOPolicy(),
            capacity_bytes=2,
        )
        engine.process(request("/a", 1))
        engine.process(request("/b", 2))
        engine.process(request("/a", 3))  # FIFO hit does not refresh /a.
        engine.process(request("/c", 4))  # Evicts /a.
        reinserted = engine.process(request("/a", 5))

        self.assertEqual(reinserted.evicted, (key("/b"),))
        self.assertEqual(
            reinserted.cache_contents_oldest_first,
            (key("/c"), key("/a")),
        )

    def test_fifo_cross_client_hit_uses_shared_entry(self) -> None:
        self.engine.process(request("/a", 1, "client-a"))
        hit = self.engine.process(request("/a", 2, "client-b"))

        self.assertTrue(hit.hit)
        self.assertEqual(hit.cache_contents_oldest_first, (key("/a"),))


class LRUPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = [resource("/a"), resource("/b"), resource("/c")]
        self.engine = SharedCacheEngine(
            {item.key: item for item in self.items},
            LRUPolicy(),
            capacity_bytes=2,
        )

    def test_hit_refreshes_lru_priority_not_insertion_order(self) -> None:
        self.engine.process(request("/a", 1))
        self.engine.process(request("/b", 2))
        hit = self.engine.process(request("/a", 3, "client-b"))

        # The display order remains insertion order, despite /a being most recent.
        self.assertTrue(hit.hit)
        self.assertEqual(hit.cache_contents_oldest_first, (key("/a"), key("/b")))
        result = self.engine.process(request("/c", 4))
        self.assertEqual(result.evicted, (key("/b"),))
        self.assertEqual(result.cache_contents_oldest_first, (key("/a"), key("/c")))

    def test_lru_hit_changes_next_victim(self) -> None:
        self.engine.process(request("/a", 1))
        self.engine.process(request("/b", 2))
        self.engine.process(request("/a", 3))
        result = self.engine.process(request("/c", 4))

        self.assertEqual(result.evicted, (key("/b"),))

    def test_lru_evicts_multiple_entries_until_resource_fits(self) -> None:
        large = resource("/large", 3)
        engine = SharedCacheEngine(
            {item.key: item for item in (*self.items[:2], large)},
            LRUPolicy(),
            capacity_bytes=3,
        )
        engine.process(request("/a", 1))
        engine.process(request("/b", 2))
        engine.process(request("/a", 3))
        result = engine.process(request("/large", 4))

        self.assertEqual(result.evicted, (key("/b"), key("/a")))
        self.assertEqual(result.cache_contents_oldest_first, (key("/large"),))

    def test_lru_reinsertion_resets_access_history(self) -> None:
        engine = SharedCacheEngine(
            {item.key: item for item in self.items},
            LRUPolicy(),
            capacity_bytes=2,
        )
        engine.process(request("/a", 1))
        engine.process(request("/b", 2))
        engine.process(request("/a", 3))
        engine.process(request("/c", 4))  # Evicts /b.
        engine.process(request("/b", 5))  # Reinserts /b after /a and /c.
        result = engine.process(request("/a", 6))

        self.assertEqual(result.evicted, (key("/c"),))
        self.assertEqual(
            result.cache_contents_oldest_first,
            (key("/b"), key("/a")),
        )

    def test_lru_cross_client_hit_refreshes_the_shared_entry(self) -> None:
        self.engine.process(request("/a", 1, "client-a"))
        self.engine.process(request("/b", 2, "client-a"))
        hit = self.engine.process(request("/a", 3, "client-b"))

        self.assertTrue(hit.hit)
        self.assertEqual(hit.client_id, "client-b")
        result = self.engine.process(request("/c", 4, "client-c"))
        self.assertEqual(result.evicted, (key("/b"),))

    def test_equal_timestamps_use_stable_request_sequence(self) -> None:
        engine = SharedCacheEngine(
            {item.key: item for item in self.items},
            LRUPolicy(),
            capacity_bytes=2,
        )
        first = request("/a", 1)
        second = replace(request("/b", 2), timestamp=first.timestamp)
        engine.process(first)
        engine.process(second)
        engine.process(request("/a", 3))
        result = engine.process(request("/c", 4))

        self.assertEqual(result.evicted, (key("/b"),))


class LFUPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = [resource("/a"), resource("/b"), resource("/c")]
        self.engine = SharedCacheEngine(
            {item.key: item for item in self.items},
            LFUPolicy(),
            capacity_bytes=2,
        )

    def test_evicts_least_frequently_used(self) -> None:
        self.engine.process(request("/a", 1))
        self.engine.process(request("/b", 2))
        self.engine.process(request("/a", 3))  # /a now has frequency 2.
        result = self.engine.process(request("/c", 4))

        self.assertEqual(result.evicted, (key("/b"),))
        self.assertEqual(result.cache_contents_oldest_first, (key("/a"), key("/c")))

    def test_frequency_tie_breaks_by_least_recent_access(self) -> None:
        self.engine.process(request("/a", 1))
        self.engine.process(request("/b", 2))
        result = self.engine.process(request("/c", 3))

        # Both residents have frequency 1; evict the one accessed least recently.
        self.assertEqual(result.evicted, (key("/a"),))
        self.assertEqual(result.cache_contents_oldest_first, (key("/b"), key("/c")))

    def test_reinsertion_resets_frequency_to_one(self) -> None:
        big = resource("/big", 2)
        engine = SharedCacheEngine(
            {item.key: item for item in (*self.items, big)},
            LFUPolicy(),
            capacity_bytes=2,
        )
        engine.process(request("/a", 1))
        engine.process(request("/b", 2))
        engine.process(request("/a", 3))
        engine.process(request("/a", 4))  # /a reaches frequency 3 before eviction.
        cleared = engine.process(request("/big", 5))
        self.assertEqual(cleared.evicted, (key("/b"), key("/a")))

        engine.process(request("/a", 6))  # Reinsert /a; frequency must restart at 1.
        engine.process(request("/b", 7))
        result = engine.process(request("/c", 8))

        # If /a inherited its old frequency 3, /b would be evicted instead.
        self.assertEqual(result.evicted, (key("/a"),))
        self.assertEqual(result.cache_contents_oldest_first, (key("/b"), key("/c")))

    def test_cross_client_accesses_share_frequency(self) -> None:
        self.engine.process(request("/a", 1, "client-a"))
        self.engine.process(request("/a", 2, "client-b"))
        self.engine.process(request("/a", 3, "client-c"))  # Shared /a reaches 3.
        self.engine.process(request("/b", 4, "client-a"))
        result = self.engine.process(request("/c", 5, "client-b"))

        self.assertEqual(result.evicted, (key("/b"),))
        self.assertEqual(result.cache_contents_oldest_first, (key("/a"), key("/c")))

    def test_evicts_multiple_entries_until_resource_fits(self) -> None:
        large = resource("/large", 3)
        engine = SharedCacheEngine(
            {item.key: item for item in (*self.items, large)},
            LFUPolicy(),
            capacity_bytes=3,
        )
        engine.process(request("/a", 1))
        engine.process(request("/b", 2))
        engine.process(request("/c", 3))
        engine.process(request("/c", 4))  # /c has frequency 2.
        result = engine.process(request("/large", 5))

        self.assertEqual(result.evicted, (key("/a"), key("/b"), key("/c")))
        self.assertEqual(result.cache_contents_oldest_first, (key("/large"),))

    def test_hit_updates_frequency_and_access_but_keeps_insertion_order(self) -> None:
        self.engine.process(request("/a", 1))
        self.engine.process(request("/b", 2))
        self.engine.process(request("/b", 3))
        after_hits = self.engine.process(request("/a", 4))

        # Hits never change the displayed insertion order.
        self.assertEqual(
            after_hits.cache_contents_oldest_first, (key("/a"), key("/b"))
        )
        result = self.engine.process(request("/c", 5))
        # Tied at frequency 2; /b was accessed at step 3, /a at step 4.
        self.assertEqual(result.evicted, (key("/b"),))

    def test_equal_timestamps_use_stable_request_sequence(self) -> None:
        engine = SharedCacheEngine(
            {item.key: item for item in self.items},
            LFUPolicy(),
            capacity_bytes=2,
        )
        first = request("/a", 1)
        second = replace(request("/b", 2), timestamp=first.timestamp)
        engine.process(first)
        engine.process(second)
        engine.process(request("/a", 3))
        result = engine.process(request("/c", 4))

        self.assertEqual(result.evicted, (key("/b"),))

    def test_reset_clears_frequency_state(self) -> None:
        self.engine.process(request("/a", 1))
        self.engine.process(request("/b", 2))
        self.engine.process(request("/a", 3))

        self.engine.reset()

        restarted = self.engine.process(request("/a", 1))
        self.assertEqual(restarted.result, "MISS")
        self.assertEqual(restarted.cache_contents_oldest_first, (key("/a"),))

    def test_lfu_matches_reference_trace(self) -> None:
        import csv
        from pathlib import Path

        reference_dir = (
            Path(__file__).resolve().parents[1] / "data" / "reference"
        )
        inputs = load_inputs(
            reference_dir / "resources.csv",
            reference_dir / "requests_reference.csv",
        )
        legend = {
            ResourceKey("https", "learn.university.edu", "/courses/ics/index.html"): "A",
            ResourceKey("https", "learn.university.edu", "/static/main.css"): "B",
            ResourceKey("https", "learn.university.edu", "/static/logo.svg"): "C",
            ResourceKey("https", "cdn.university.edu", "/images/avatar-default.png"): "D",
            ResourceKey("https", "pypi.org", "/static/css/warehouse.css"): "E",
        }

        def labels(keys: Sequence[ResourceKey]) -> str:
            return ",".join(legend[item] for item in keys) or "-"

        engine = SharedCacheEngine(inputs.resources, LFUPolicy())
        events = engine.process_all(inputs.requests)
        with (reference_dir / "expected_lfu.csv").open(newline="") as handle:
            expected = list(csv.DictReader(handle, strict=True))

        self.assertEqual(len(events), len(expected))
        origin_bytes = hits = 0
        for event, row in zip(events, expected):
            origin_bytes += event.origin_bytes
            hits += event.hit
            actual = {
                "step": event.step,
                "resource_id": legend[event.resource_key],
                "client_id": event.client_id,
                "result": event.result,
                "evicted": labels(event.evicted),
                "cache_contents_oldest_first": labels(
                    event.cache_contents_oldest_first
                ),
                "cache_used_KiB": event.cache_used_bytes / 1024,
                "response_ms": event.response_ms,
                "cumulative_origin_bytes": origin_bytes,
                "cumulative_hits": hits,
            }
            for field, value in actual.items():
                with self.subTest(step=event.step, field=field):
                    expected_value = (
                        float(row[field])
                        if isinstance(value, (int, float))
                        else row[field]
                    )
                    self.assertEqual(value, expected_value)

        self.assertEqual(hits, 4)
        self.assertEqual(len(events) - hits, 11)
        self.assertEqual(origin_bytes, 370688)


if __name__ == "__main__":
    unittest.main()
