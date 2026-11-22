from __future__ import annotations

import math
import random
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cache_simulator.engine import SharedCacheEngine
from cache_simulator.input_parser import load_inputs
from cache_simulator.models import Request, Resource, ResourceKey
from cache_simulator.policies import LFUPolicy, LRUPolicy
from cache_simulator.rwcsf import RWCSFPolicy

KIB = 1024
REFERENCE_DIR = Path(__file__).resolve().parents[1] / "data" / "reference"


def key(path: str) -> ResourceKey:
    return ResourceKey("https", "example.com", path)


def resource(path: str, size: int, latency: float = 105.0) -> Resource:
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
        timestamp=datetime(2026, 11, 14, tzinfo=timezone.utc),
        client_id=client,
        method="GET",
        key=key(path),
        sequence=step,
        source_line=step + 1,
    )


def run(policy, items, paths, capacity, hit_latency=5.0):
    """Run a path sequence through the real engine; return its events."""
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
    def test_invalid_parameters_are_rejected(self) -> None:
        for kwargs in (
            {"half_life": 0},
            {"half_life": -1},
            {"half_life": math.nan},
            {"half_life": True},
            {"hit_latency_ms": -1},
            {"hit_latency_ms": math.inf},
            {"forget_limit": -1},
            {"forget_limit": 1.5},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    RWCSFPolicy(**kwargs)

    def test_infinite_half_life_is_allowed(self) -> None:
        RWCSFPolicy(half_life=math.inf)


class ProposalSequenceTests(unittest.TestCase):
    """The hand-computed validation sequence from the proposal (H = 10)."""

    PATHS = ["/a", "/a", "/a", "/b", "/b", "/c", "/d"]

    def items(self):
        return [
            resource("/a", 30 * KIB, 105),
            resource("/b", 30 * KIB, 35),
            resource("/c", 30 * KIB, 105),
            resource("/d", 30 * KIB, 105),
        ]

    def test_priorities_match_hand_calculation(self) -> None:
        policy = RWCSFPolicy(half_life=10)
        run(policy, self.items(), self.PATHS[:6], 100 * KIB)

        f_a = 2 ** -0.6 + 2 ** -0.5 + 2 ** -0.4  # accesses at steps 1, 2, 3
        f_b = 2 ** -0.3 + 2 ** -0.2  # steps 4, 5
        f_c = 2 ** -0.1  # step 6
        expected = {
            "/a": f_a * 100 / (30 * KIB),
            "/b": f_b * 30 / (30 * KIB),
            "/c": f_c * 100 / (30 * KIB),
        }
        for path, value in expected.items():
            with self.subTest(path=path):
                self.assertTrue(
                    math.isclose(
                        policy.priority(key(path), step=7), value, rel_tol=1e-9
                    )
                )
        self.assertAlmostEqual(f_a, 2.1248, places=3)
        self.assertAlmostEqual(f_b, 1.6829, places=3)
        self.assertAlmostEqual(f_c, 0.9330, places=3)

    def test_three_policies_evict_three_different_victims(self) -> None:
        victims = {}
        for name, policy in (
            ("RWCSF", RWCSFPolicy(half_life=10)),
            ("LRU", LRUPolicy()),
            ("LFU", LFUPolicy()),
        ):
            events = run(policy, self.items(), self.PATHS, 100 * KIB)
            self.assertEqual(len(events[-1].evicted), 1)
            victims[name] = events[-1].evicted[0]

        self.assertEqual(victims["RWCSF"], key("/b"))
        self.assertEqual(victims["LRU"], key("/a"))
        self.assertEqual(victims["LFU"], key("/c"))


class DegenerateCaseTests(unittest.TestCase):
    """With size and latency switched off, RW-CSF must reduce to LFU / LRU."""

    @staticmethod
    def workload(seed: int):
        rng = random.Random(seed)
        items = [
            resource(f"/r{i}", rng.randint(1, 40), rng.choice([2, 20, 80, 200]))
            for i in range(10)
        ]
        picks = rng.choices(items, weights=range(10, 0, -1), k=250)
        return items, [item.key.path for item in picks]

    def compare(self, rw_policy_factory, reference_factory) -> None:
        for seed in range(25):
            with self.subTest(seed=seed):
                items, paths = self.workload(seed)
                got = run(rw_policy_factory(), items, paths, 100)
                want = run(reference_factory(), items, paths, 100)
                self.assertEqual(
                    [(e.hit, e.evicted) for e in got],
                    [(e.hit, e.evicted) for e in want],
                )

    def test_infinite_half_life_behaves_like_lfu(self) -> None:
        self.compare(
            lambda: RWCSFPolicy(
                half_life=math.inf, use_latency=False, use_size=False
            ),
            LFUPolicy,
        )

    def test_half_life_one_behaves_like_lru(self) -> None:
        self.compare(
            lambda: RWCSFPolicy(half_life=1, use_latency=False, use_size=False),
            LRUPolicy,
        )


class WeightingTests(unittest.TestCase):
    def test_lower_latency_gain_is_evicted(self) -> None:
        items = [
            resource("/a", 5, 205),  # a hit saves 200 ms
            resource("/b", 5, 35),  # a hit saves 30 ms
            resource("/c", 5, 105),
        ]
        events = run(RWCSFPolicy(), items, ["/a", "/b", "/c"], 10)
        self.assertEqual(events[-1].evicted, (key("/b"),))

    def test_larger_resource_is_evicted_despite_being_newer(self) -> None:
        items = [
            resource("/small", 2, 105),
            resource("/big", 8, 105),
            resource("/new", 2, 105),
        ]
        # LRU would evict /small (oldest); RW-CSF evicts the low-density /big.
        events = run(RWCSFPolicy(), items, ["/small", "/big", "/new"], 10)
        self.assertEqual(events[-1].evicted, (key("/big"),))

    def test_resource_with_no_latency_gain_is_evicted_first(self) -> None:
        items = [
            resource("/slow", 5, 105),
            resource("/fast", 5, 3),  # origin faster than a cache hit
            resource("/new", 5, 105),
        ]
        events = run(RWCSFPolicy(), items, ["/slow", "/fast", "/new"], 10)
        self.assertEqual(events[-1].evicted, (key("/fast"),))

    def test_zero_byte_resource_is_never_the_preferred_victim(self) -> None:
        items = [
            resource("/zero", 0, 105),
            resource("/a", 6, 105),
            resource("/c", 6, 105),
        ]
        events = run(RWCSFPolicy(), items, ["/zero", "/a", "/c"], 10)
        self.assertEqual(events[-1].evicted, (key("/a"),))

    def test_switches_replace_factors_with_one(self) -> None:
        items = [resource("/a", 8, 205), resource("/b", 2, 35)]
        no_size = RWCSFPolicy(use_size=False)
        no_latency = RWCSFPolicy(use_latency=False)
        run(no_size, items, ["/a", "/b"], 100)
        run(no_latency, items, ["/a", "/b"], 100)
        # Both fit; compare priorities at step 3.
        self.assertTrue(
            math.isclose(
                no_size.priority(key("/a"), step=3),
                2 ** (-2 / 20) * 200,
                rel_tol=1e-9,
            )
        )
        self.assertTrue(
            math.isclose(
                no_latency.priority(key("/a"), step=3),
                2 ** (-2 / 20) * 1 / 8,
                rel_tol=1e-9,
            )
        )


class InheritTests(unittest.TestCase):
    def setUp(self) -> None:
        self.a = resource("/a", 10, 105)
        self.b = resource("/b", 10, 105)
        self.resources = {self.a.key: self.a, self.b.key: self.b}

    def reinsert_a(self, **kwargs) -> RWCSFPolicy:
        policy = RWCSFPolicy(self.resources, half_life=10, **kwargs)
        policy.on_insert(self.a.key, step=1)
        policy.on_hit(self.a.key, step=2)
        policy.on_evict(self.a.key, step=3)
        policy.on_insert(self.a.key, step=5)
        return policy

    def test_default_resets_history_on_reinsertion(self) -> None:
        policy = self.reinsert_a()
        self.assertTrue(
            math.isclose(policy.priority(self.a.key, step=5), 1 * 100 / 10)
        )

    def test_inherit_decays_old_history_then_adds_one(self) -> None:
        policy = self.reinsert_a(inherit=True)
        f_old = 2 ** -0.1 + 1  # F at step 2
        f_new = 1 + f_old * 2 ** -0.3  # decayed over steps 2 -> 5, plus this access
        self.assertTrue(
            math.isclose(
                policy.priority(self.a.key, step=5), f_new * 100 / 10, rel_tol=1e-9
            )
        )

    def test_forget_limit_drops_oldest_memory(self) -> None:
        policy = RWCSFPolicy(
            self.resources, half_life=10, inherit=True, forget_limit=1
        )
        policy.on_insert(self.a.key, step=1)
        policy.on_evict(self.a.key, step=2)
        policy.on_insert(self.b.key, step=3)
        policy.on_evict(self.b.key, step=4)  # pushes /a out of the memory
        policy.on_insert(self.a.key, step=5)
        policy.on_insert(self.b.key, step=5)
        self.assertTrue(math.isclose(policy.priority(self.a.key, step=5), 10.0))
        self.assertGreater(policy.priority(self.b.key, step=5), 10.0)


class StateAndContractTests(unittest.TestCase):
    def test_always_admits(self) -> None:
        policy = RWCSFPolicy()
        self.assertIs(policy.should_admit(resource("/a", 1), step=1), True)

    def test_unknown_size_and_latency_raises_clear_error(self) -> None:
        policy = RWCSFPolicy()
        policy.on_insert(key("/a"), step=1)
        with self.assertRaisesRegex(ValueError, "no size/latency"):
            policy.select_victim([key("/a")], step=2)

    def test_constructor_resources_replace_should_admit(self) -> None:
        item = resource("/a", 10, 105)
        policy = RWCSFPolicy({item.key: item})
        policy.on_insert(item.key, step=1)
        self.assertEqual(policy.select_victim([item.key], step=2), item.key)

    def test_double_insert_and_untracked_calls_are_rejected(self) -> None:
        policy = RWCSFPolicy()
        policy.on_insert(key("/a"), step=1)
        with self.assertRaises(ValueError):
            policy.on_insert(key("/a"), step=2)
        for call in (
            lambda: policy.on_hit(key("/zz"), step=2),
            lambda: policy.on_evict(key("/zz"), step=2),
            lambda: policy.select_victim([], step=2),
        ):
            with self.assertRaises(ValueError):
                call()

    def test_reset_makes_runs_independent(self) -> None:
        items, paths = DegenerateCaseTests.workload(3)
        engine = SharedCacheEngine(
            {item.key: item for item in items}, RWCSFPolicy(), capacity_bytes=100
        )
        requests = tuple(request(p, s) for s, p in enumerate(paths, start=1))
        first = engine.process_all(requests)
        engine.reset()
        self.assertEqual(engine.process_all(requests), first)


class ReferenceTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = load_inputs(
            REFERENCE_DIR / "resources.csv", REFERENCE_DIR / "requests_reference.csv"
        )

    def test_reference_trace_invariants_at_100_kib(self) -> None:
        engine = SharedCacheEngine(self.inputs.resources, RWCSFPolicy())
        events = engine.process_all(self.inputs.requests)
        self.assertEqual(len(events), 15)
        self.assertTrue(all(e.cache_used_bytes <= 102400 for e in events))
        hits = sum(e.hit for e in events)
        origin = sum(e.origin_bytes for e in events)
        self.assertEqual(
            origin,
            sum(
                self.inputs.resources[e.resource_key].size_bytes
                for e in events
                if not e.hit
            ),
        )
        self.assertTrue(0 <= hits <= 15)

    def test_large_cache_matches_lru_because_nothing_is_evicted(self) -> None:
        big = 1024 * KIB
        rw = SharedCacheEngine(
            self.inputs.resources, RWCSFPolicy(), capacity_bytes=big
        ).process_all(self.inputs.requests)
        lru = SharedCacheEngine(
            self.inputs.resources, LRUPolicy(), capacity_bytes=big
        ).process_all(self.inputs.requests)
        self.assertTrue(all(e.evicted == () for e in rw))
        self.assertEqual([e.hit for e in rw], [e.hit for e in lru])


if __name__ == "__main__":
    unittest.main()
