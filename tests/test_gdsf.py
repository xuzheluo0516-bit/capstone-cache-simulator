from __future__ import annotations

import math
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cache_simulator.engine import SharedCacheEngine
from cache_simulator.gdsf import GDSFPolicy
from cache_simulator.input_parser import load_inputs
from cache_simulator.models import Request, Resource, ResourceKey
from cache_simulator.policies import LFUPolicy, LRUPolicy

KIB = 1024
SIZE = 30 * KIB
REFERENCE_DIR = Path(__file__).resolve().parents[1] / "data" / "reference"


def key(path: str) -> ResourceKey:
    return ResourceKey("https", "example.com", path)


def resource(path: str, size: int = SIZE, latency: float = 105.0) -> Resource:
    return Resource(
        key=key(path),
        status_code=200,
        content_type="text/plain",
        size_bytes=size,
        origin_latency_ms=latency,
        cache_control="public",
    )


def request(path: str, step: int) -> Request:
    return Request(
        timestamp=datetime(2026, 11, 15, tzinfo=timezone.utc),
        client_id="client",
        method="GET",
        key=key(path),
        sequence=step,
        source_line=step + 1,
    )


def run(policy, items, paths, capacity, hit_latency=5.0):
    engine = SharedCacheEngine(
        {item.key: item for item in items},
        policy,
        capacity_bytes=capacity,
        hit_latency_ms=hit_latency,
    )
    return engine.process_all(
        tuple(request(path, step) for step, path in enumerate(paths, start=1))
    )


class ConstructorTests(unittest.TestCase):
    def test_invalid_hit_latency_is_rejected(self) -> None:
        for value in (-1, math.inf, math.nan, True, "5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                GDSFPolicy(hit_latency_ms=value)

    def test_zero_hit_latency_is_allowed(self) -> None:
        GDSFPolicy(hit_latency_ms=0)


class HandCalculationTests(unittest.TestCase):
    """Hand-computed keys. All resources are 30 KiB; gain = latency - 5 ms."""

    def test_keys_and_first_eviction(self) -> None:
        # a a a b b c d  (a, c, d: 105 ms -> gain 100; b: 35 ms -> gain 30)
        items = [
            resource("/a"),
            resource("/b", latency=35.0),
            resource("/c"),
            resource("/d"),
        ]
        policy = GDSFPolicy()
        events = run(policy, items, ["/a", "/a", "/a", "/b", "/b", "/c"], 100 * KIB)
        self.assertEqual(policy.inflation, 0.0)
        for path, expected in (("/a", 300), ("/b", 60), ("/c", 100)):
            with self.subTest(path=path):
                self.assertTrue(
                    math.isclose(policy.key_value(key(path)), expected / SIZE)
                )
        self.assertEqual([e.hit for e in events], [False, True, True, False, True, False])

        policy = GDSFPolicy()
        events = run(
            policy, items, ["/a", "/a", "/a", "/b", "/b", "/c", "/d"], 100 * KIB
        )
        self.assertEqual(events[-1].evicted, (key("/b"),))
        # L jumps to the victim's K, and the new resource gets L + 1 * 100 / s.
        self.assertTrue(math.isclose(policy.inflation, 60 / SIZE))
        self.assertTrue(math.isclose(policy.key_value(key("/d")), 160 / SIZE))

    def test_inflation_ages_out_an_old_frequent_resource(self) -> None:
        # Capacity holds two 30 KiB resources. x is hit twice (F=3, K=300/s).
        # Each later eviction raises L, so by the last request a once-used
        # newcomer (K = L + 100/s = 330/s) outranks x and x is evicted.
        items = [
            resource("/x"),
            resource("/y", latency=35.0),
            resource("/z"),
            resource("/w"),
            resource("/v"),
            resource("/u"),
        ]
        paths = ["/x", "/x", "/x", "/y", "/z", "/w", "/v", "/u"]
        policy = GDSFPolicy()
        events = run(policy, items, paths, 60 * KIB)
        evicted = [e.evicted for e in events]
        self.assertEqual(
            evicted,
            [(), (), (), (), (key("/y"),), (key("/z"),), (key("/w"),), (key("/x"),)],
        )
        self.assertTrue(math.isclose(policy.inflation, 300 / SIZE))
        # LFU never evicts x here, and LRU evicts it much earlier.
        lfu = run(LFUPolicy(), items, paths, 60 * KIB)
        lru = run(LRUPolicy(), items, paths, 60 * KIB)
        self.assertNotEqual(lfu[-1].evicted, (key("/x"),))
        self.assertEqual(lru[4].evicted, (key("/x"),))

    def test_larger_resource_has_lower_key_and_is_evicted(self) -> None:
        items = [resource("/small", size=10 * KIB), resource("/big", size=50 * KIB),
                 resource("/new", size=20 * KIB)]
        events = run(GDSFPolicy(), items, ["/small", "/big", "/new"], 60 * KIB)
        self.assertEqual(events[-1].evicted, (key("/big"),))

    def test_lower_latency_gain_is_evicted(self) -> None:
        items = [resource("/slow"), resource("/fast", latency=20.0), resource("/new")]
        events = run(GDSFPolicy(), items, ["/fast", "/slow", "/new"], 60 * KIB)
        self.assertEqual(events[-1].evicted, (key("/fast"),))

    def test_custom_hit_latency_changes_the_gain(self) -> None:
        # gain(/p) = 25 - 20 = 5, gain(/q) = 22 - 5 = 17 would flip the order
        # if the policy ignored its hit_latency_ms parameter.
        items = [resource("/p", latency=25.0), resource("/q", latency=22.0),
                 resource("/new", latency=25.0)]
        policy = GDSFPolicy(hit_latency_ms=20.0)
        events = run(policy, items, ["/p", "/q", "/new"], 60 * KIB, hit_latency=20.0)
        self.assertEqual(events[-1].evicted, (key("/q"),))  # gain 2 < gain 5

    def test_no_latency_gain_resource_is_first_victim(self) -> None:
        items = [resource("/a"), resource("/cheap", latency=5.0), resource("/new")]
        policy = GDSFPolicy()
        events = run(policy, items, ["/a", "/a", "/cheap", "/new"], 60 * KIB)
        self.assertEqual(events[-1].evicted, (key("/cheap"),))
        self.assertEqual(policy.inflation, 0.0)


class TieAndHistoryTests(unittest.TestCase):
    def test_tie_evicts_least_recently_accessed(self) -> None:
        items = [resource("/a"), resource("/b"), resource("/c")]
        for paths, victim in ((["/a", "/b", "/c"], "/a"), (["/b", "/a", "/c"], "/b")):
            with self.subTest(paths=paths):
                events = run(GDSFPolicy(), items, paths, 60 * KIB)
                self.assertEqual(events[-1].evicted, (key(victim),))

    def test_equal_keys_and_steps_fall_back_to_resource_key(self) -> None:
        policy = GDSFPolicy()
        for path in ("/b", "/a"):
            policy.should_admit(resource(path), step=1)
            policy.on_insert(key(path), step=1)
        self.assertEqual(
            policy.select_victim([key("/b"), key("/a")], step=2), key("/a")
        )

    def test_history_is_reset_on_eviction(self) -> None:
        # /a is hit twice (F=3), evicted, then re-inserted: F must restart at 1.
        policy = GDSFPolicy()
        # gain(/b) = gain(/c) = 500, so K_b = 500/s > K_a = 300/s (F = 3).
        items = [resource("/a"), resource("/b", latency=505.0), resource("/c", latency=505.0)]
        paths = ["/a", "/a", "/a", "/b", "/c", "/a"]
        events = run(policy, items, paths, 60 * KIB)
        self.assertEqual(events[4].evicted, (key("/a"),))  # a has the lower K
        self.assertEqual(events[5].evicted, (key("/b"),))
        # After evicting b (K = 500/s), L = 500/s. A re-inserted a has F = 1,
        # so K = 500/s + 100/s. An inherited F = 3 would give 800/s instead.
        self.assertTrue(math.isclose(policy.inflation, 500 / SIZE))
        self.assertTrue(math.isclose(policy.key_value(key("/a")), 600 / SIZE))

    def test_zero_byte_resource_never_poisons_inflation(self) -> None:
        policy = GDSFPolicy()
        policy.should_admit(resource("/zero", size=0), step=1)
        policy.on_insert(key("/zero"), step=1)
        policy.should_admit(resource("/a"), step=2)
        policy.on_insert(key("/a"), step=2)
        self.assertEqual(
            policy.select_victim([key("/zero"), key("/a")], step=3), key("/a")
        )
        policy.on_evict(key("/zero"), step=3)
        self.assertEqual(policy.inflation, 0.0)


class StateAndContractTests(unittest.TestCase):
    def test_always_admits(self) -> None:
        self.assertTrue(GDSFPolicy().should_admit(resource("/a"), step=1))

    def test_unknown_size_and_latency_raises_clear_error(self) -> None:
        policy = GDSFPolicy()
        with self.assertRaisesRegex(ValueError, "no size/latency"):
            policy.on_insert(key("/a"), step=1)

    def test_constructor_resources_replace_should_admit(self) -> None:
        policy = GDSFPolicy(resources={key("/a"): resource("/a")})
        policy.on_insert(key("/a"), step=1)
        self.assertTrue(math.isclose(policy.key_value(key("/a")), 100 / SIZE))

    def test_double_insert_and_untracked_calls_are_rejected(self) -> None:
        policy = GDSFPolicy(resources={key("/a"): resource("/a")})
        policy.on_insert(key("/a"), step=1)
        with self.assertRaises(ValueError):
            policy.on_insert(key("/a"), step=2)
        for call in (
            lambda: policy.on_hit(key("/b"), step=2),
            lambda: policy.on_evict(key("/b"), step=2),
            lambda: policy.select_victim([key("/b")], step=2),
            lambda: policy.select_victim([], step=2),
            lambda: policy.key_value(key("/b")),
        ):
            with self.assertRaises(ValueError):
                call()

    def test_reset_makes_runs_independent(self) -> None:
        items = [resource("/a"), resource("/b"), resource("/c")]
        policy = GDSFPolicy()
        engine = SharedCacheEngine(
            {i.key: i for i in items}, policy, capacity_bytes=60 * KIB
        )
        requests = tuple(request(p, s) for s, p in enumerate(["/a", "/b", "/c", "/a"], 1))
        first = engine.process_all(requests)
        self.assertGreater(policy.inflation, 0.0)
        engine.reset()
        self.assertEqual(policy.inflation, 0.0)
        self.assertEqual(engine.process_all(requests), first)


class ReferenceTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = load_inputs(
            REFERENCE_DIR / "resources.csv", REFERENCE_DIR / "requests_reference.csv"
        )

    def test_reference_trace_invariants_at_100_kib(self) -> None:
        events = SharedCacheEngine(self.inputs.resources, GDSFPolicy()).process_all(
            self.inputs.requests
        )
        self.assertEqual(len(events), 15)
        self.assertTrue(all(e.cache_used_bytes <= 102400 for e in events))
        origin = sum(e.origin_bytes for e in events)
        self.assertEqual(
            origin,
            sum(
                self.inputs.resources[e.resource_key].size_bytes
                for e in events
                if not e.hit
            ),
        )

    def test_large_cache_matches_lru_because_nothing_is_evicted(self) -> None:
        big = 1024 * KIB
        gdsf = SharedCacheEngine(
            self.inputs.resources, GDSFPolicy(), capacity_bytes=big
        ).process_all(self.inputs.requests)
        lru = SharedCacheEngine(
            self.inputs.resources, LRUPolicy(), capacity_bytes=big
        ).process_all(self.inputs.requests)
        self.assertEqual([e.hit for e in gdsf], [e.hit for e in lru])
        self.assertTrue(all(e.evicted == () for e in gdsf))


if __name__ == "__main__":
    unittest.main()
