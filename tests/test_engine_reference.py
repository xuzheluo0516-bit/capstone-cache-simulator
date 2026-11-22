"""Exercise the engine contract with test-only policies, without a CLI or metrics module."""

from __future__ import annotations

import csv
import unittest
from pathlib import Path
from typing import Sequence

from cache_simulator.engine import SharedCacheEngine
from cache_simulator.input_parser import load_inputs
from cache_simulator.models import ResourceKey
from tests.test_engine import request, resource

REFERENCE_DIR = Path(__file__).resolve().parents[1] / "data" / "reference"


class ReferencePolicy:
    """Small independent oracle for exercising replacement callbacks in tests."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.reset()

    def reset(self) -> None:
        self.counts: dict[ResourceKey, int] = {}
        self.last_access: dict[ResourceKey, int] = {}

    def on_insert(self, key: ResourceKey, *, step: int) -> None:
        self.counts[key] = 1
        self.last_access[key] = step

    def on_hit(self, key: ResourceKey, *, step: int) -> None:
        self.counts[key] += 1
        self.last_access[key] = step

    def on_evict(self, key: ResourceKey, *, step: int) -> None:
        del self.counts[key]
        del self.last_access[key]

    def select_victim(
        self, resident_keys: Sequence[ResourceKey], *, step: int
    ) -> ResourceKey:
        if self.mode == "fifo":
            return resident_keys[0]
        if self.mode == "lru":
            return min(resident_keys, key=self.last_access.__getitem__)
        if self.mode == "lfu":
            return min(resident_keys, key=lambda key: (
                self.counts[key], self.last_access[key]
            ))
        if self.mode == "newest":
            return resident_keys[-1]
        raise AssertionError(f"unknown test policy {self.mode}")


class EngineReferenceTests(unittest.TestCase):
    def test_three_policy_adapters_match_every_reference_field(self) -> None:
        inputs = load_inputs(
            REFERENCE_DIR / "resources.csv", REFERENCE_DIR / "requests_reference.csv"
        )
        # IDs belong to the reference output only, never to the engine itself.
        legend = {
            ResourceKey("https", "learn.university.edu", "/courses/ics/index.html"): "A",
            ResourceKey("https", "learn.university.edu", "/static/main.css"): "B",
            ResourceKey("https", "learn.university.edu", "/static/logo.svg"): "C",
            ResourceKey("https", "cdn.university.edu", "/images/avatar-default.png"): "D",
            ResourceKey("https", "pypi.org", "/static/css/warehouse.css"): "E",
        }

        def labels(keys: Sequence[ResourceKey]) -> str:
            return ",".join(legend[key] for key in keys) or "-"

        for mode in ("fifo", "lru", "lfu"):
            with self.subTest(policy=mode):
                engine = SharedCacheEngine(inputs.resources, ReferencePolicy(mode))
                events = engine.process_all(inputs.requests)
                with (REFERENCE_DIR / f"expected_{mode}.csv").open(newline="") as handle:
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
                        "cache_contents_oldest_first": labels(event.cache_contents_oldest_first),
                        "cache_used_KiB": event.cache_used_bytes / 1024,
                        "response_ms": event.response_ms,
                        "cumulative_origin_bytes": origin_bytes,
                        "cumulative_hits": hits,
                    }
                    for field, value in actual.items():
                        with self.subTest(policy=mode, step=event.step, field=field):
                            expected_value = (
                                float(row[field]) if isinstance(value, (int, float))
                                else row[field]
                            )
                            self.assertEqual(value, expected_value)
                    self.assertLessEqual(event.cache_used_bytes, engine.capacity_bytes)

    def test_fourth_policy_can_choose_a_different_victim(self) -> None:
        items = [resource(path, 4) for path in ("/a", "/b", "/c")]
        engine = SharedCacheEngine(
            {item.key: item for item in items},
            ReferencePolicy("newest"), capacity_bytes=8,
        )
        events = engine.process_all(tuple(
            request(path, step) for step, path in enumerate(("/a", "/b", "/c"), 1)
        ))
        self.assertEqual(events[-1].evicted, (items[1].key,))
        self.assertEqual(
            events[-1].cache_contents_oldest_first, (items[0].key, items[2].key)
        )


if __name__ == "__main__":
    unittest.main()
