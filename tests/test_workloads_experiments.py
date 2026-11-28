"""Regression tests for reproducible workloads and fair batch conditions."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from cache_simulator.engine import SharedCacheEngine
from cache_simulator.experiments import DEFAULT_POLICIES, run_suite
from cache_simulator.input_parser import load_inputs
from cache_simulator.metrics import MetricsAccumulator
from cache_simulator.policies import FIFOPolicy, LFUPolicy, LRUPolicy
from cache_simulator.workloads import ALL_KINDS, CAPACITIES_BYTES, KINDS, generate_suite


def read_csv_rows(path: Path) -> list[list[str]]:
    """Compare CSV content by parsed fields, independent of line endings."""
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))


class WorkloadTests(unittest.TestCase):
    def test_committed_small_examples_match_current_generator(self) -> None:
        committed = Path(__file__).resolve().parents[1] / "data" / "generated"
        with tempfile.TemporaryDirectory() as directory:
            for workload in generate_suite(Path(directory), seed=20261111, counts={"small": 72}):
                self.assertEqual(
                    read_csv_rows(workload.resources_path),
                    read_csv_rows(committed / workload.resources_path.name),
                )
                self.assertEqual(
                    read_csv_rows(workload.requests_path),
                    read_csv_rows(committed / workload.requests_path.name),
                )

    def test_all_kinds_parse_and_reproduce_with_same_seed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            counts = {"small": 72, "medium": 360, "large": 1440}
            first = generate_suite(root / "one", seed=7, counts=counts)
            second = generate_suite(root / "two", seed=7, counts=counts)
            self.assertEqual(len(first), 9)
            for a, b in zip(first, second):
                self.assertEqual(a.resources_path.read_bytes(), b.resources_path.read_bytes())
                self.assertEqual(a.requests_path.read_bytes(), b.requests_path.read_bytes())
                parsed = load_inputs(a.resources_path, a.requests_path)
                self.assertEqual(len(parsed.requests), a.count)
                self.assertEqual(len(parsed.resources), 13 + a.count if a.kind == "sequential" else 13)
                if a.kind == "sequential":
                    unique = len({request.key for request in parsed.requests})
                    self.assertGreaterEqual((a.count - unique) / a.count, 0.10)
                    self.assertLessEqual((a.count - unique) / a.count, 0.15)
                metadata = json.loads(a.metadata_path.read_text())
                self.assertEqual(metadata["request_count"], a.count)
                self.assertGreater(metadata["active_resource_bytes"], 0)
            self.assertEqual({a.kind for a in first}, {"repeated", "sequential", "mixed"})
            self.assertEqual(KINDS, ("repeated", "sequential", "mixed"))

    def test_sequential_is_mostly_new_with_occasional_revisits_and_loop_is_optional(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workloads = generate_suite(root, seed=20261111, counts={"large": 1440}, kinds=ALL_KINDS)
            sequential = next(w for w in workloads if w.kind == "sequential")
            parsed = load_inputs(sequential.resources_path, sequential.requests_path)
            paths = [request.key.path for request in parsed.requests]
            repeats = len(paths) - len(set(paths))
            self.assertGreaterEqual(len(parsed.resources), 60)
            self.assertGreaterEqual(repeats / len(paths), 0.10)
            self.assertLessEqual(repeats / len(paths), 0.15)
            self.assertTrue(all(path.startswith("/sequential/") for path in paths))
            loop = next(w for w in workloads if w.kind == "loop")
            loop_paths = [request.key.path for request in load_inputs(loop.resources_path, loop.requests_path).requests]
            self.assertEqual(loop_paths[:12], [f"/object/{index:02d}" for index in range(12)])
            self.assertEqual(loop_paths[12], loop_paths[0])

    def test_mixed_trace_has_fitting_eviction_and_oversized_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workload = next(w for w in generate_suite(Path(directory), seed=7, counts={"small": 72}) if w.kind == "mixed")
            parsed = load_inputs(workload.resources_path, workload.requests_path)
            for policy in (FIFOPolicy, LRUPolicy, LFUPolicy):
                with self.subTest(policy=policy.__name__):
                    engine = SharedCacheEngine(parsed.resources, policy(), capacity_bytes=512 * 1024)
                    events = engine.process_all(parsed.requests)
                    self.assertEqual(events[11].resource_key.path, "/object/11")
                    self.assertTrue(events[11].evicted)  # Fitting 384 KiB media object displaces small objects.
                    self.assertLessEqual(events[11].cache_used_bytes, 512 * 1024)
                    self.assertEqual(events[13].resource_key.path, "/video/oversized.mp4")
                    self.assertFalse(events[13].hit)
                    self.assertEqual(events[13].evicted, ())
                    self.assertEqual(events[13].cache_contents_oldest_first, events[12].cache_contents_oldest_first)
                    metrics = MetricsAccumulator(parsed.resources, capacity_bytes=512 * 1024)
                    metrics.consume_all(events)
                    summary = metrics.summary
                    self.assertEqual(summary.hits + summary.misses, 72)
                    self.assertEqual(summary.hit_bytes + summary.origin_bytes, summary.request_bytes)

    def test_mixed_oversized_video_is_about_once_per_hundred_requests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workload = next(w for w in generate_suite(Path(directory), seed=7, counts={"large": 1440}) if w.kind == "mixed")
            paths = [request.key.path for request in load_inputs(workload.resources_path, workload.requests_path).requests]
            video_indices = [i for i, path in enumerate(paths) if path == "/video/oversized.mp4"]
            self.assertEqual(video_indices, [13, *range(100, 1440, 100)])

    def test_every_capacity_has_real_eviction_pressure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workload = next(w for w in generate_suite(Path(directory), seed=20261111, counts={"medium": 360}) if w.kind == "sequential")
            parsed = load_inputs(workload.resources_path, workload.requests_path)
            for capacity in CAPACITIES_BYTES:
                for policy in (FIFOPolicy, LRUPolicy, LFUPolicy):
                    with self.subTest(capacity=capacity, policy=policy.__name__):
                        engine = SharedCacheEngine(parsed.resources, policy(), capacity_bytes=capacity)
                        events = engine.process_all(parsed.requests)
                        self.assertTrue(any(event.evicted for event in events))
                        self.assertTrue(all(event.cache_used_bytes <= capacity for event in events))
                        metrics = MetricsAccumulator(parsed.resources, capacity_bytes=capacity)
                        metrics.consume_all(events)
                        summary = metrics.summary
                        self.assertEqual(summary.hits + summary.misses, 360)
                        self.assertEqual(summary.hit_bytes + summary.origin_bytes, summary.request_bytes)


class ExperimentTests(unittest.TestCase):
    def test_five_policy_runner_uses_same_inputs_and_writes_all_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Placeholder constructors test orchestration only; the D policies
            # are verified separately once their branch is integrated.
            registry = {"FIFO": FIFOPolicy, "LRU": LRUPolicy, "LFU": LFUPolicy, "GDSF": LRUPolicy, "CUSTOM": LRUPolicy}
            manifest = run_suite(
                root, seed=17, counts={"tiny": 24},
                capacities_bytes=(32 * 1024, 512 * 1024, 1024 * 1024),
                policies=DEFAULT_POLICIES, registry=registry,
            )
            self.assertEqual(manifest["planned_runs"], 45)
            self.assertEqual(manifest["completed_runs"], 45)
            self.assertEqual(len(manifest["source_sha256"]), 64)
            self.assertTrue(all(run["status"] == "complete" for run in manifest["runs"]))
            with (root / "summary.csv").open(newline="") as handle:
                summaries = list(csv.DictReader(handle))
            with (root / "clients.csv").open(newline="") as handle:
                clients = list(csv.DictReader(handle))
            self.assertEqual(len(summaries), 45)
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

    def test_missing_policy_fails_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "policy not registered: NOPE"):
                run_suite(Path(directory), counts={"tiny": 24}, policies=("NOPE",))


if __name__ == "__main__":
    unittest.main()
