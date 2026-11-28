"""Tests for the course-trace experiment (d_experiments/course/run_course.py)."""

import csv
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "d_experiments" / "course"))
sys.path.insert(0, str(ROOT / "d_experiments"))
import run_course as rc  # noqa: E402

REF = ROOT / "data" / "reference"
RESOURCES = REF / "resources.csv"


def read(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_catalog():
    return {(r["scheme"], r["host"], r["path"]): (int(r["size_bytes"]), float(r["origin_latency_ms"]))
            for r in read(RESOURCES)}


def load_requests(workload):
    return [(r["scheme"], r["host"], r["path"], r["client_id"])
            for r in read(REF / f"requests_{workload}.csv")]


def reference_run(policy, workload, capacity):
    """Independent simulator for all five policies.

    FIFO/LRU/LFU are written from the course text. GDSF and RW-CSF are written
    from their definitions (docs/custom-policy-design.md), with the decayed
    count computed as an explicit sum over the access history instead of the
    incremental update the policy classes use.
    """
    catalog = load_catalog()
    cache = {}  # key -> [insert_step, last_step, count, access_steps, K]
    inflation = 0.0  # GDSF's L
    used = hits = hit_bytes = origin = evictions = oversized = 0
    total_ms = 0.0
    util = 0.0
    requests = load_requests(workload)
    for step, (scheme, host, path, _client) in enumerate(requests):
        key = (scheme, host, path)
        size, latency = catalog[key]
        if size > capacity:
            oversized += 1
        if key in cache:
            hits += 1
            hit_bytes += size
            total_ms += 5.0
            cache[key][1] = step
            cache[key][2] += 1
            cache[key][3].append(step)
            gain = max(latency - 5.0, 0.0)
            cache[key][4] = inflation + cache[key][2] * gain / size
        else:
            total_ms += latency
            origin += size
            if size <= capacity:
                while used + size > capacity:
                    if policy == "FIFO":
                        victim = min(cache, key=lambda k: cache[k][0])
                    elif policy == "LRU":
                        victim = min(cache, key=lambda k: cache[k][1])
                    elif policy == "LFU":  # ties -> least recently used
                        victim = min(cache, key=lambda k: (cache[k][2], cache[k][1]))
                    elif policy == "GDSF":  # K = L + F * dT / s; ties -> LRU, then key
                        victim = min(cache, key=lambda k: (cache[k][4], cache[k][1], k))
                    else:  # CUSTOM = RW-CSF, H = 20: P = (sum 2^-(n-n_j)/H) * dT / s
                        def priority(k):
                            decayed = sum(2.0 ** (-(step - n_j) / 20.0) for n_j in cache[k][3])
                            return decayed * max(catalog[k][1] - 5.0, 0.0) / catalog[k][0]
                        victim = min(cache, key=lambda k: (priority(k), cache[k][1], k))
                    if policy == "GDSF":
                        inflation = cache[victim][4]
                    used -= catalog[victim][0]
                    del cache[victim]
                    evictions += 1
                cache[key] = [step, step, 1, [step], inflation + max(latency - 5.0, 0.0) / size]
                used += size
        util += used / capacity
    n = len(requests)
    return {"hits": hits, "origin_bytes": origin, "evictions": evictions,
            "oversized_requests": oversized, "average_response_ms": total_ms / n,
            "avg_cache_utilization": util / n, "request_hit_rate": hits / n,
            "byte_hit_rate": hit_bytes / sum(catalog[(s, h, p)][0] for s, h, p, _ in requests)}


class CourseRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        rc.run_all(RESOURCES, REF, cls.out, rc.PREREGISTERED_HALF_LIFE)
        cls.runs = read(cls.out / "course_runs.csv")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_grid_is_complete(self):
        self.assertEqual(len(self.runs), 3 * 6 * 5)
        self.assertEqual(len({(r["workload"], r["capacity_KiB"], r["policy"]) for r in self.runs}), 90)
        self.assertIn("5120", {r["capacity_KiB"] for r in self.runs})   # 5 MiB

    def test_all_policies_match_an_independent_simulator(self):
        for r in self.runs:
            ref = reference_run(r["policy"], r["workload"], int(r["capacity_KiB"]) * 1024)
            label = (r["workload"], r["capacity_KiB"], r["policy"])
            for field in ("hits", "origin_bytes", "evictions", "oversized_requests"):
                self.assertEqual(int(r[field]), ref[field], (label, field))
            for field in ("average_response_ms", "avg_cache_utilization",
                          "request_hit_rate", "byte_hit_rate"):
                self.assertAlmostEqual(float(r[field]), ref[field], places=9, msg=(label, field))

    def test_committed_course_runs_match_independent_simulator(self):
        committed = read(ROOT / "data" / "results" / "course" / "course_runs.csv")
        self.assertEqual(len(committed), 90)
        for r in committed:
            ref = reference_run(r["policy"], r["workload"], int(r["capacity_KiB"]) * 1024)
            label = (r["workload"], r["capacity_KiB"], r["policy"])
            for field in ("hits", "origin_bytes", "evictions", "oversized_requests"):
                self.assertEqual(int(r[field]), ref[field], (label, field))
            for field in ("average_response_ms", "avg_cache_utilization",
                          "request_hit_rate", "byte_hit_rate"):
                self.assertAlmostEqual(float(r[field]), ref[field], places=9, msg=(label, field))

    def test_hits_plus_misses_and_oversized_bounds(self):
        for r in self.runs:
            self.assertEqual(int(r["hits"]) + int(r["misses"]), int(r["requests"]))
            self.assertLessEqual(int(r["oversized_requests"]), int(r["misses"]))
            self.assertTrue(0 <= float(r["avg_cache_utilization"]) <= 1)

    def test_everything_fits_gives_no_difference_in_response_time(self):
        for workload in rc.WORKLOADS:
            cell = {r["policy"]: float(r["average_response_ms"]) for r in self.runs
                    if r["workload"] == workload and r["capacity_KiB"] == "10240"}
            self.assertEqual(len({round(v, 9) for v in cell.values()}), 1, (workload, cell))

    def test_characterisation_matches_a_direct_count(self):
        catalog = load_catalog()
        for row in read(self.out / "workload_summary.csv"):
            reqs = load_requests(row["workload"])
            self.assertEqual(int(row["total_requests"]), len(reqs))
            self.assertEqual(int(row["distinct_resources"]), len({(s, h, p) for s, h, p, _ in reqs}))
            self.assertEqual(int(row["distinct_clients"]), len({c for *_, c in reqs}))
            self.assertEqual(int(row["total_requested_bytes"]),
                             sum(catalog[(s, h, p)][0] for s, h, p, _ in reqs))
            for kib in rc.CAPACITIES_KIB:
                self.assertEqual(int(row[f"requests_larger_than_{kib}KiB"]),
                                 sum(1 for s, h, p, _ in reqs if catalog[(s, h, p)][0] > kib * 1024))
        top = [r for r in read(self.out / "workload_top5.csv") if r["workload"] == "repetitive"]
        counts = Counter(f"{h}{p}" for _s, h, p, _c in load_requests("repetitive")).most_common(5)
        self.assertEqual([int(r["requests"]) for r in top], [n for _, n in counts])

    def test_h_sensitivity_agrees_with_the_main_grid(self):
        h_rows = read(self.out / "course_h_sensitivity.csv")
        self.assertEqual(len(h_rows), 3 * 6 * 5)
        self.assertEqual({r["half_life"] for r in h_rows}, {"5", "20", "100", "500", "inf"})
        for r in h_rows:
            if r["half_life"] == "20":
                main = next(m for m in self.runs if m["workload"] == r["workload"]
                            and m["capacity_KiB"] == r["capacity_KiB"] and m["policy"] == "CUSTOM")
                self.assertAlmostEqual(float(r["average_response_ms"]),
                                       float(main["average_response_ms"]), places=9)

    def test_client_rows_add_up(self):
        for workload in rc.WORKLOADS:
            rows = [r for r in read(self.out / "course_clients.csv")
                    if r["workload"] == workload and r["capacity_KiB"] == "5120" and r["policy"] == "LRU"]
            run = next(r for r in self.runs if r["workload"] == workload
                       and r["capacity_KiB"] == "5120" and r["policy"] == "LRU")
            self.assertEqual(sum(int(r["requests"]) for r in rows), 3000)
            self.assertEqual(sum(int(r["hits"]) for r in rows), int(run["hits"]))

    def test_manifest_is_strict_json_and_records_inputs(self):
        def reject(constant):
            raise ValueError(constant)
        manifest = json.loads((self.out / "manifest.json").read_text(), parse_constant=reject)
        self.assertEqual(manifest["half_life"], 20.0)
        self.assertFalse(manifest["exploratory"])
        self.assertEqual(manifest["completed_runs"], manifest["planned_runs"])
        self.assertEqual(len(manifest["input_sha256"]), 4)
        self.assertIn("course_source_sha256", manifest)


class GuardTests(unittest.TestCase):
    def test_exploratory_h_cannot_be_written_under_data_results(self):
        with self.assertRaises(SystemExit):
            rc.main(["--half-life", "5", "--output-dir", str(ROOT / "data" / "results" / "course")])

    def test_non_finite_h_refused(self):
        with self.assertRaises(SystemExit):
            rc.main(["--half-life", "inf", "--output-dir", "x"])


if __name__ == "__main__":
    unittest.main()
