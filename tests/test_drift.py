import math
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "d_experiments"))
import run_drift as rd  # noqa: E402
from cache_simulator.input_parser import load_inputs  # noqa: E402
from common import TUNING_SEED  # noqa: E402


def build(seed, tmp):
    res = rd.catalog()
    rp, qp = Path(tmp) / "r.csv", Path(tmp) / "q.csv"
    rd._write(rp, rd.RESOURCE_FIELDS, res)
    rd._write(qp, rd.REQUEST_FIELDS, rd.make_trace(seed, res))
    return res, load_inputs(rp, qp)


class TraceTests(unittest.TestCase):
    def test_structure_and_hot_share(self):
        res = rd.catalog()
        trace = rd.make_trace(20261111, res)
        self.assertEqual(len(trace), 1440)
        self.assertEqual(len(res), 12)
        for phase in range(3):
            chunk = trace[phase * 480:(phase + 1) * 480]
            hot = sum(1 for r in chunk if r["path"].startswith(f"/drift/g{phase}/"))
            # 85% hot plus 1/3 of the 15% that lands in the same group = 90%
            self.assertTrue(0.84 <= hot / 480 <= 0.96, hot / 480)

    def test_deterministic_and_seed_dependent(self):
        res = rd.catalog()
        self.assertEqual(rd.make_trace(1, res), rd.make_trace(1, res))
        self.assertNotEqual(rd.make_trace(1, res), rd.make_trace(2, res))

    def test_groups_identical_size_latency(self):
        res = rd.catalog()
        for slot in range(4):
            vals = {(r["size_bytes"], r["origin_latency_ms"])
                    for r in res if r["path"].endswith(f"/{slot}")}
            self.assertEqual(len(vals), 1)

    def test_tuning_seed_refused(self):
        self.assertEqual(TUNING_SEED, 31415)
        self.assertNotIn(31415, rd.DEFAULT_SEEDS)


class PreregistrationTests(unittest.TestCase):
    def run_cli(self, *args):
        script = Path(__file__).resolve().parents[1] / "d_experiments" / "run_drift.py"
        with tempfile.TemporaryDirectory() as tmp:
            return subprocess.run(
                [sys.executable, str(script), "--output-dir", tmp, *args],
                capture_output=True, text=True)

    def test_direct_run_refuses_other_half_life(self):
        result = self.run_cli("--half-life", "5")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixes H at 20", result.stderr)

    def test_direct_run_refuses_subset_of_preregistered_seeds(self):
        result = self.run_cli("--seeds", "20261111", "20261112")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("five preregistered seeds", result.stderr)


class SimulationTests(unittest.TestCase):
    def test_everything_fits_all_policies_equal(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, sim = build(20261111, tmp)
            vals = {n: rd.run_cell(sim, n, 1024 * 1024, 20.0).average_response_ms
                    for n in rd.POLICIES}
        self.assertEqual(len({round(v, 9) for v in vals.values()}), 1, vals)

    def test_lru_matches_independent_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            res, sim = build(20261112, tmp)
            info = {r["path"]: (int(r["size_bytes"]), int(r["origin_latency_ms"])) for r in res}
            trace = rd.make_trace(20261112, res)
            cap = 256 * 1024
            cache, used, total = [], 0, 0.0
            for r in trace:
                p = r["path"]
                size, lat = info[p]
                if p in cache:
                    cache.remove(p); cache.append(p); total += 5.0
                    continue
                total += lat
                while used + size > cap and cache:
                    used -= info[cache.pop(0)][0]
                cache.append(p); used += size
            ref = total / len(trace)
            got = rd.run_cell(sim, "LRU", cap, 20.0).average_response_ms
        self.assertAlmostEqual(ref, got, places=6)

    def test_no_decay_equals_huge_half_life(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, sim = build(20261113, tmp)
            a = rd.run_cell(sim, "NO_DECAY", 256 * 1024, 20.0).average_response_ms
            b = rd.run_cell(sim, "CUSTOM", 256 * 1024, 1e12).average_response_ms
        self.assertAlmostEqual(a, b, places=6)

    def test_prediction_check_logic(self):
        table = []
        for kib in rd.CAPACITIES_KIB:
            for name, v in zip(rd.POLICIES, (100, 100, 100, 100, 100, 100)):
                table.append({"capacity_KiB": kib, "policy": name,
                              "average_response_ms_mean": float(v)})
        res = rd.check_predictions(table)
        self.assertFalse(res["P1"]["holds"])
        self.assertTrue(res["P2"]["holds"])
        self.assertFalse(res["P3"]["holds"])
        for t in table:
            if t["policy"] == "CUSTOM" and t["capacity_KiB"] == 256:
                t["average_response_ms_mean"] = 90.0
        res = rd.check_predictions(table)
        self.assertTrue(res["P1"]["holds"] and res["P3"]["holds"])
        self.assertFalse(res["P2"]["holds"])


if __name__ == "__main__":
    unittest.main()
