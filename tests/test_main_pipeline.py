import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "d_experiments"))
import analyze_fairness  # noqa: E402
from analyze_fairness import fairness_tables, jain, read_client_rows  # noqa: E402
from common import aggregate_summary, stdev, write_manifest  # noqa: E402

try:
    import matplotlib  # noqa: F401
    import make_plots
    HAVE_MPL = True
except ImportError:  # pragma: no cover
    HAVE_MPL = False


def srow(workload, cap, policy, seed, ms, hit=0.5, byte=0.4, origin=1000):
    return {"workload": workload, "capacity_KiB": str(float(cap)), "policy": policy,
            "seed": str(seed), "average_response_ms": str(ms),
            "request_hit_rate": str(hit), "byte_hit_rate": str(byte),
            "origin_bytes": str(origin)}


def crow(policy, seed, client, hit, ms, cap=32768, workload="mixed"):
    return {"workload": workload, "capacity_bytes": str(cap), "policy": policy,
            "seed": str(seed), "client_id": client, "request_hit_rate": str(hit),
            "average_response_ms": str(ms)}


class AggregateTests(unittest.TestCase):
    def test_mean_and_sample_std(self) -> None:
        rows = [srow("mixed", 32, "LRU", s, ms) for s, ms in ((1, 10), (2, 20), (3, 30))]
        (line,) = aggregate_summary(rows)
        self.assertEqual(line["n_seeds"], 3)
        self.assertAlmostEqual(line["average_response_ms_mean"], 20.0)
        self.assertAlmostEqual(line["average_response_ms_std"], 10.0)  # n - 1, not n

    def test_single_seed_has_zero_std(self) -> None:
        self.assertEqual(stdev([5.0]), 0.0)

    def test_cells_are_separated_and_duplicates_rejected(self) -> None:
        rows = [srow("mixed", 32, "LRU", 1, 10), srow("mixed", 128, "LRU", 1, 4),
                srow("repeated", 32, "LRU", 1, 7)]
        self.assertEqual(len(aggregate_summary(rows)), 3)
        with self.assertRaises(ValueError):
            aggregate_summary(rows + [srow("mixed", 32, "LRU", 1, 99)])


class JainTests(unittest.TestCase):
    def test_known_values(self) -> None:
        self.assertAlmostEqual(jain([0.4, 0.4, 0.4]), 1.0)
        self.assertAlmostEqual(jain([1.0, 0.0, 0.0]), 1 / 3)
        self.assertAlmostEqual(jain([1, 2, 3]), 36 / (3 * 14))
        self.assertTrue(math.isnan(jain([0.0, 0.0])))
        self.assertTrue(math.isnan(jain([])))


class FairnessTests(unittest.TestCase):
    def rows(self):
        out = []
        # seed 1: LRU hit rates (0.5, 0.5) -> J = 1; seed 2: (1.0, 0.0) -> J = 0.5
        for client, hit, ms in (("a", 0.5, 10), ("b", 0.5, 50)):
            out.append(crow("LRU", 1, client, hit, ms))
        for client, hit, ms in (("a", 1.0, 5), ("b", 0.0, 90)):
            out.append(crow("LRU", 2, client, hit, ms))
        for seed in (1, 2):
            out.append(crow("CUSTOM", seed, "a", 0.5, 8))
            out.append(crow("CUSTOM", seed, "b", 0.5, 70))
        out.append(crow("LRU", 1, "a", 0.9, 1, workload="repeated"))  # other workload
        return out

    def test_jain_is_computed_per_seed_then_averaged(self) -> None:
        fair, _ = fairness_tables(self.rows())
        lru = next(r for r in fair if r["policy"] == "LRU")
        self.assertAlmostEqual(lru["jain_mean"], (1.0 + 0.5) / 2)
        self.assertEqual(lru["n_seeds"], 2)

    def test_worst_client_is_the_slowest_one(self) -> None:
        fair, _ = fairness_tables(self.rows())
        lru = next(r for r in fair if r["policy"] == "LRU")
        self.assertAlmostEqual(lru["worst_client_ms_mean"], (50 + 90) / 2)
        self.assertEqual(lru["worst_client_id"], "b")
        custom = next(r for r in fair if r["policy"] == "CUSTOM")
        self.assertAlmostEqual(custom["worst_client_ms_mean"], 70.0)

    def test_delta_against_baseline_per_client(self) -> None:
        _, per_client = fairness_tables(self.rows())
        cell = {(r["policy"], r["client_id"]): r for r in per_client}
        # LRU client b mean ms = 70, CUSTOM client b = 70 -> 0; client a: 7.5 vs 8 -> +0.5
        self.assertAlmostEqual(cell[("CUSTOM", "b")]["delta_vs_baseline_ms"], 0.0)
        self.assertAlmostEqual(cell[("CUSTOM", "a")]["delta_vs_baseline_ms"], 0.5)
        self.assertAlmostEqual(cell[("LRU", "a")]["delta_vs_baseline_ms"], 0.0)

    def test_workloads_are_not_mixed_and_missing_workload_errors(self) -> None:
        fair, per_client = fairness_tables(self.rows())
        self.assertTrue(all(r["workload"] == "mixed" for r in fair + per_client))
        with self.assertRaises(ValueError):
            fairness_tables(self.rows(), workload="nope")


class ManifestTests(unittest.TestCase):
    def test_manifest_is_strict_json_with_posix_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            write_manifest(path, {
                "runs": [{"events_file": "events\\mixed.csv"}],
                "parameter": math.inf,
            })
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("Infinity", text)
            self.assertIn('"events/mixed.csv"', text)
            self.assertIn('"parameter": "inf"', text)
            self.assertNotIn("\r\n", text)


class FairnessSeedSelectionTests(unittest.TestCase):
    def test_only_requested_seeds_are_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for seed, hit in ((1, "0.5"), (2, "0.9")):
                seed_dir = root / f"seed_{seed}"
                seed_dir.mkdir()
                (seed_dir / "clients.csv").write_text(
                    "workload,capacity_bytes,policy,seed,client_id,"
                    "request_hit_rate,average_response_ms\n"
                    f"mixed,32768,LRU,{seed},a,{hit},10\n",
                    encoding="utf-8",
                )
            rows = read_client_rows(root, [1])
            self.assertEqual({row["seed"] for row in rows}, {"1"})
            with self.assertRaises(FileNotFoundError):
                read_client_rows(root, [99])
            with self.assertRaises(ValueError):
                read_client_rows(root, [1, 1])

    def test_cli_rejects_duplicate_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as cm:
                analyze_fairness.main(
                    ["--results-dir", tmp, "--seeds", "1", "1", "2"])
        self.assertNotEqual(cm.exception.code, 0)


class RunMainGuardTests(unittest.TestCase):
    def test_tuning_seed_is_refused(self) -> None:
        import run_main
        from run_h_tuning import TUNING_SEED
        argv = ["run_main", "--output-dir", "x", "--half-life", "20",
                "--seeds", str(TUNING_SEED)]
        with mock.patch.object(sys, "argv", argv), self.assertRaises(SystemExit):
            run_main.main()


class RunAblationGuardTests(unittest.TestCase):
    def test_tuning_seed_is_refused(self) -> None:
        import run_ablation
        from run_h_tuning import TUNING_SEED
        argv = ["run_ablation", "--output-dir", "x", "--half-life", "20",
                "--seeds", str(TUNING_SEED)]
        with mock.patch.object(sys, "argv", argv), self.assertRaises(SystemExit):
            run_ablation.main()


@unittest.skipUnless(HAVE_MPL, "matplotlib is not installed")
class PlotSmokeTests(unittest.TestCase):
    def test_all_figures_are_written(self) -> None:
        policies = ("FIFO", "LRU", "LFU", "GDSF", "CUSTOM")
        summary = []
        for workload in ("repeated", "sequential", "mixed"):
            for cap in (32, 128):
                for i, policy in enumerate(policies):
                    summary.append(srow(workload, cap, policy, 1, 50 - i))
        table = aggregate_summary(summary)
        for row in table:
            row.update({k: str(v) for k, v in row.items()})
        per_client = [
            {"workload": "mixed", "capacity_KiB": "128.0", "policy": p, "client_id": c,
             "hit_rate_mean": "0.3", "avg_response_ms_mean": "40"}
            for p in policies for c in ("a", "b")]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            make_plots.metric_vs_capacity(table, "request_hit_rate", "hit", out / "a.png", 100)
            make_plots.byte_hit_bars(table, 128.0, out / "b.png")
            make_plots.per_client_bars(per_client, 128.0, out / "c.png")
            for name in ("a.png", "b.png", "c.png"):
                data = (out / name).read_bytes()
                self.assertTrue(data.startswith(b"\x89PNG"), name)
                self.assertGreater(len(data), 2000, name)

    def test_missing_cell_is_an_error_not_a_silent_gap(self) -> None:
        table = aggregate_summary([srow("mixed", 32, "LRU", 1, 5)])
        with self.assertRaises(ValueError):
            make_plots.byte_hit_bars(table, 128.0, Path("never.png"))


if __name__ == "__main__":
    unittest.main()
