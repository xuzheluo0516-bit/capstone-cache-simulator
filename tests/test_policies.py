from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from cache_simulator.engine import SharedCacheEngine
from cache_simulator.models import Request, Resource, ResourceKey
from cache_simulator.policies import FIFOPolicy, LRUPolicy


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


if __name__ == "__main__":
    unittest.main()
