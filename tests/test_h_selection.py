import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "d_experiments"))
from run_h_tuning import H_VALUES, select_half_life, variant_name  # noqa: E402


def rows(values):
    out = []
    for h, per_workload in values.items():
        for workload, capacities in per_workload.items():
            for ms in capacities:
                out.append({"policy": variant_name(h), "workload": workload,
                            "average_response_ms": str(ms)})
    return out


class SelectionRuleTests(unittest.TestCase):
    def test_mean_of_workload_means_decides(self) -> None:
        # H=5 wins one workload hugely but loses the average to H=20.
        data = {h: {"repeated": [10, 10], "sequential": [10, 10], "mixed": [10, 10]}
                for h in H_VALUES}
        data[5] = {"repeated": [1, 1], "sequential": [40, 40], "mixed": [10, 10]}   # 17
        data[20] = {"repeated": [8, 8], "sequential": [8, 8], "mixed": [8, 8]}      # 8
        best, scores = select_half_life(rows(data))
        self.assertEqual(best, 20)
        self.assertAlmostEqual(scores[5], 17.0)

    def test_uneven_capacity_counts_do_not_skew_workload_means(self) -> None:
        data = {h: {"repeated": [10], "sequential": [10], "mixed": [10]} for h in H_VALUES}
        data[100] = {"repeated": [0, 0, 0, 30], "sequential": [10], "mixed": [10]}  # 7.5,10,10
        best, scores = select_half_life(rows(data))
        self.assertAlmostEqual(scores[100], (7.5 + 10 + 10) / 3)
        self.assertEqual(best, 100)

    def test_tie_goes_to_smaller_h(self) -> None:
        data = {h: {"repeated": [5], "sequential": [5], "mixed": [5]} for h in H_VALUES}
        self.assertEqual(select_half_life(rows(data))[0], 5)

    def test_missing_workload_is_an_error(self) -> None:
        data = {h: {"repeated": [5], "mixed": [5]} for h in H_VALUES}
        with self.assertRaises(RuntimeError):
            select_half_life(rows(data))


class ProtocolSeedTests(unittest.TestCase):
    def test_formal_seed_cannot_select_h(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(ROOT / "d_experiments" / "run_h_tuning.py"),
                 "--output-dir", tmp, "--seed", "20261111"],
                capture_output=True, text=True, cwd=ROOT,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixed at 31415", result.stderr)


if __name__ == "__main__":
    unittest.main()
