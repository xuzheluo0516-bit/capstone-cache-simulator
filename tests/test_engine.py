from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from cache_simulator.engine import (
    PolicyContractError,
    SharedCacheEngine,
)
from cache_simulator.models import Request, Resource, ResourceKey


class FrontQueuePolicy:
    """Minimal test policy that evicts the first resident key."""

    def __init__(self) -> None:
        self.residents: list[ResourceKey] = []
        self.hits: list[tuple[ResourceKey, int]] = []
        self.insertions: list[tuple[ResourceKey, int]] = []
        self.evictions: list[tuple[ResourceKey, int]] = []

    def on_hit(self, key: ResourceKey, *, step: int) -> None:
        self.hits.append((key, step))

    def on_insert(self, key: ResourceKey, *, step: int) -> None:
        self.residents.append(key)
        self.insertions.append((key, step))

    def select_victim(
        self,
        resident_keys: tuple[ResourceKey, ...],
        *,
        step: int,
    ) -> ResourceKey:
        del step
        if not resident_keys:
            raise AssertionError("no resident key to evict")
        return resident_keys[0]

    def on_evict(self, key: ResourceKey, *, step: int) -> None:
        self.residents.remove(key)
        self.evictions.append((key, step))

    def reset(self) -> None:
        self.residents.clear()
        self.hits.clear()
        self.insertions.clear()
        self.evictions.clear()


def key(path: str) -> ResourceKey:
    return ResourceKey("https", "example.com", path)


def resource(path: str, size: int, latency: float = 10) -> Resource:
    return Resource(
        key=key(path),
        status_code=200,
        content_type="text/plain",
        size_bytes=size,
        origin_latency_ms=latency,
        cache_control="public",
    )


def request(path: str, step: int, client: str = "client") -> Request:
    return Request(
        timestamp=datetime(2026, 10, 26, tzinfo=timezone.utc),
        client_id=client,
        method="GET",
        key=key(path),
        sequence=step,
        source_line=step + 1,
    )


class SharedCacheEngineTests(unittest.TestCase):
    def test_miss_and_cross_client_hit_use_one_shared_copy(self) -> None:
        item = resource("/a", 10, latency=23)
        engine = SharedCacheEngine(
            {item.key: item},
            FrontQueuePolicy(),
            capacity_bytes=20,
            hit_latency_ms=7,
        )

        miss = engine.process(request("/a", 1, "client-a"))
        hit = engine.process(request("/a", 2, "client-b"))

        self.assertEqual(miss.result, "MISS")
        self.assertEqual(miss.response_ms, 23)
        self.assertEqual(miss.origin_bytes, 10)
        self.assertEqual(miss.cache_contents_oldest_first, (item.key,))
        self.assertEqual(hit.result, "HIT")
        self.assertEqual(hit.response_ms, 7)
        self.assertEqual(hit.origin_bytes, 0)
        self.assertEqual(hit.cache_contents_oldest_first, (item.key,))

    def test_resource_exactly_at_capacity_is_cached(self) -> None:
        item = resource("/exact", 20)
        policy = FrontQueuePolicy()
        engine = SharedCacheEngine(
            {item.key: item},
            policy,
            capacity_bytes=20,
        )

        result = engine.process(request("/exact", 1))

        self.assertFalse(result.hit)
        self.assertEqual(engine.used_bytes, 20)
        self.assertEqual(policy.residents, [item.key])
        self.assertTrue(engine.process(request("/exact", 2)).hit)

    def test_oversized_miss_bypasses_without_eviction(self) -> None:
        small = resource("/small", 30)
        huge = resource("/huge", 101)
        policy = FrontQueuePolicy()
        engine = SharedCacheEngine(
            {small.key: small, huge.key: huge},
            policy,
            capacity_bytes=100,
        )
        engine.process(request("/small", 1))
        before_policy = (list(policy.hits), list(policy.insertions), list(policy.evictions))

        result = engine.process(request("/huge", 2))

        self.assertEqual(result.result, "MISS")
        self.assertEqual(result.evicted, ())
        self.assertEqual(engine.cache_contents_oldest_first, (small.key,))
        self.assertEqual(engine.used_bytes, 30)
        self.assertEqual(policy.residents, [small.key])
        self.assertEqual(result.origin_bytes, 101)
        self.assertEqual(result.response_ms, huge.origin_latency_ms)
        self.assertEqual(
            (policy.hits, policy.insertions, policy.evictions), before_policy
        )
        self.assertTrue(engine.process(request("/small", 3)).hit)

    def test_evicts_repeatedly_until_new_resource_fits(self) -> None:
        first = resource("/first", 4)
        second = resource("/second", 4)
        third = resource("/third", 9)
        policy = FrontQueuePolicy()
        engine = SharedCacheEngine(
            {item.key: item for item in (first, second, third)},
            policy,
            capacity_bytes=10,
        )
        engine.process(request("/first", 1))
        engine.process(request("/second", 2))

        result = engine.process(request("/third", 3))

        self.assertEqual(result.evicted, (first.key, second.key))
        self.assertEqual(result.cache_contents_oldest_first, (third.key,))
        self.assertEqual(engine.used_bytes, 9)
        self.assertEqual(
            policy.evictions,
            [(first.key, 3), (second.key, 3)],
        )

    def test_non_default_hit_latency_and_reset(self) -> None:
        item = resource("/a", 4, latency=31)
        policy = FrontQueuePolicy()
        engine = SharedCacheEngine(
            {item.key: item},
            policy,
            capacity_bytes=10,
            hit_latency_ms=2.5,
        )
        engine.process(request("/a", 1))
        hit = engine.process(request("/a", 2))
        self.assertEqual(hit.response_ms, 2.5)

        engine.reset()

        self.assertEqual(engine.used_bytes, 0)
        self.assertEqual(engine.cache_contents_oldest_first, ())
        self.assertEqual(policy.residents, [])
        self.assertEqual(policy.hits, [])
        self.assertEqual(policy.insertions, [])
        self.assertEqual(policy.evictions, [])
        self.assertEqual(
            engine.process(request("/a", 1)).response_ms,
            31,
        )

    def test_default_configuration_is_100_kib_and_5_ms(self) -> None:
        item = resource("/a", 1)
        engine = SharedCacheEngine({item.key: item}, FrontQueuePolicy())

        self.assertEqual(engine.capacity_bytes, 102400)
        self.assertEqual(engine.hit_latency_ms, 5)

    def test_duplicate_step_is_rejected(self) -> None:
        item = resource("/a", 1)
        engine = SharedCacheEngine({item.key: item}, FrontQueuePolicy())
        item_request = request("/a", 1)
        engine.process(item_request)

        with self.assertRaisesRegex(ValueError, "already processed"):
            engine.process(item_request)

    def test_invalid_victim_is_rejected(self) -> None:
        first = resource("/first", 6)
        second = resource("/second", 6)
        third = resource("/third", 6)

        class BadPolicy(FrontQueuePolicy):
            def select_victim(
                self,
                resident_keys: tuple[ResourceKey, ...],
                *,
                step: int,
            ) -> ResourceKey:
                del resident_keys, step
                return key("/missing")

        engine = SharedCacheEngine(
            {item.key: item for item in (first, second, third)},
            BadPolicy(),
            capacity_bytes=10,
        )
        engine.process(request("/first", 1))

        with self.assertRaises(PolicyContractError):
            engine.process(request("/second", 2))

    def test_independent_runs_produce_identical_unique_events(self) -> None:
        items = [resource("/a", 6), resource("/b", 6)]
        engine = SharedCacheEngine(
            {item.key: item for item in items}, FrontQueuePolicy(), capacity_bytes=10
        )
        requests = (request("/a", 1), request("/a", 2), request("/b", 3))
        first_run = engine.process_all(requests)
        self.assertEqual(len(first_run), len(requests))
        self.assertEqual([event.step for event in first_run], [1, 2, 3])
        engine.reset()
        self.assertEqual(engine.process_all(requests), first_run)
        self.assertEqual(engine.process_all(()), ())

    def test_cache_control_and_expiry_are_ignored(self) -> None:
        item = replace(resource("/a", 6), cache_control="private, no-store, max-age=0")
        engine = SharedCacheEngine({item.key: item}, FrontQueuePolicy())
        miss = engine.process(request("/a", 1))
        later = replace(request("/a", 2), timestamp=datetime(2027, 1, 1, tzinfo=timezone.utc))
        self.assertFalse(miss.hit)
        self.assertTrue(engine.process(later).hit)

    def test_zero_capacity_can_cache_only_zero_byte_resources(self) -> None:
        empty, nonempty = resource("/empty", 0), resource("/a", 1)
        engine = SharedCacheEngine(
            {item.key: item for item in (empty, nonempty)},
            FrontQueuePolicy(), capacity_bytes=0,
        )
        engine.process(request("/empty", 1))
        self.assertEqual(engine.process(request("/a", 2)).evicted, ())
        self.assertTrue(engine.process(request("/empty", 3)).hit)
        self.assertEqual(engine.used_bytes, 0)


if __name__ == "__main__":
    unittest.main()
