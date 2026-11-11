"""Regression tests for reproducible workloads and fair batch conditions."""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from cache_simulator.engine import SharedCacheEngine
from cache_simulator.experiments import run_suite
from cache_simulator.input_parser import load_inputs
from cache_simulator.policies import FIFOPolicy, LFUPolicy, LRUPolicy
from cache_simulator.workloads import generate_suite


class WorkloadTests(unittest.TestCase):
    def test_all_kinds_parse_and_reproduce_with_same_seed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = generate_suite(root / "one", seed=7, counts={"small": 72, "medium": 96})
            second = generate_suite(root / "two", seed=7, counts={"small": 72, "medium": 96})
            self.assertEqual(len(first), 6)
            for a, b in zip(first, second):
                self.assertEqual(a.resources_path.read_bytes(), b.resources_path.read_bytes())
                self.assertEqual(a.requests_path.read_bytes(), b.requests_path.read_bytes())
                parsed = load_inputs(a.resources_path, a.requests_path)
                self.assertEqual(len(parsed.requests), a.count)
                self.assertEqual(len(parsed.resources), 13)
                metadata = json.loads(a.metadata_path.read_text())
                self.assertEqual(metadata["request_count"], a.count)
                self.assertGreater(metadata["active_resource_bytes"], 0)
            self.assertEqual({a.kind for a in first}, {"repeated", "sequential", "mixed"})

    def test_mixed_trace_has_fitting_eviction_and_oversized_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workload = next(w for w in generate_suite(Path(directory), seed=7, counts={"small": 72}) if w.kind == "mixed")
            parsed = load_inputs(workload.resources_path, workload.requests_path)
            engine = SharedCacheEngine(parsed.resources, FIFOPolicy(), capacity_bytes=512 * 1024)
            events = engine.process_all(parsed.requests)
            self.assertTrue(events[11].evicted)  # 384 KiB media object displaces small objects.
            self.assertLessEqual(events[11].cache_used_bytes, 512 * 1024)
            self.assertEqual(events[13].resource_key.path, "/video/oversized.mp4")
            self.assertFalse(events[13].hit)
            self.assertEqual(events[13].evicted, ())
            self.assertEqual(events[13].cache_contents_oldest_first, events[12].cache_contents_oldest_first)


class ExperimentTests(unittest.TestCase):
    def test_four_policy_runner_uses_same_inputs_and_writes_all_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Placeholder constructor tests orchestration only; this is not the
            # team's not-yet-implemented fourth algorithm.
            registry = {"FIFO": FIFOPolicy, "LRU": LRUPolicy, "LFU": LFUPolicy, "CUSTOM": LRUPolicy}
            manifest = run_suite(
                root, seed=17, counts={"tiny": 24},
                capacities_bytes=(32 * 1024, 512 * 1024, 1024 * 1024),
                policies=("FIFO", "LRU", "LFU", "CUSTOM"), registry=registry,
            )
            self.assertEqual(manifest["planned_runs"], 36)
            self.assertEqual(manifest["completed_runs"], 36)
            self.assertEqual(len(manifest["source_sha256"]), 64)
            self.assertTrue(all(run["status"] == "complete" for run in manifest["runs"]))
            with (root / "summary.csv").open(newline="") as handle:
                summaries = list(csv.DictReader(handle))
            with (root / "clients.csv").open(newline="") as handle:
                clients = list(csv.DictReader(handle))
            self.assertEqual(len(summaries), 36)
            self.assertTrue(clients)
            for row in summaries:
                self.assertEqual(int(row["requests"]), 24)
                self.assertEqual(int(row["hits"]) + int(row["misses"]), 24)
                self.assertEqual(int(row["hit_bytes"]) + int(row["origin_bytes"]), int(row["request_bytes"]))
                event_path = root / row["events_file"]
                self.assertTrue(event_path.is_file())
                with event_path.open(newline="") as handle:
                    self.assertEqual(len(list(csv.DictReader(handle))), 24)
            grouped = {}
            for run in manifest["runs"]:
                key = (run["workload"], run["scale"], run["capacity_bytes"])
                grouped.setdefault(key, set()).add((run["resources_sha256"], run["requests_sha256"]))
            self.assertTrue(all(len(hashes) == 1 for hashes in grouped.values()))

    def test_missing_custom_policy_fails_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "policy not registered: CUSTOM"):
                run_suite(Path(directory), counts={"tiny": 24})


if __name__ == "__main__":
    unittest.main()
