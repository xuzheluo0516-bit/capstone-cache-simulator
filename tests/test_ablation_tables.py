import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "d_experiments"))
from common import build_registry, percent_change  # noqa: E402
from run_ablation import VARIANTS, build_tables  # noqa: E402


def row(policy, workload, cap, ms, seed=1):
    return {"policy": policy, "workload": workload, "capacity_KiB": str(float(cap)),
            "average_response_ms": str(ms), "seed": str(seed)}


class TableTests(unittest.TestCase):
    def rows(self):
        out = []
        for workload in ("repeated", "sequential", "mixed"):
            for seed in (1, 2):
                for cap in (32, 128):
                    out.append(row("CUSTOM", workload, cap, 100.0, seed))
                    out.append(row("ABL_NO_LATENCY", workload, cap, 110.0, seed))
                    out.append(row("ABL_NO_SIZE", workload, cap, 100.0, seed))
                    out.append(row("ABL_NO_DECAY", workload, cap, 90.0 if cap == 32 else 100.0, seed))
        return out

    def test_percent_change_relative_to_full(self) -> None:
        main, detail = build_tables(self.rows())
        by_variant = {line["variant"]: line for line in main}
        self.assertAlmostEqual(by_variant["ABL_NO_LATENCY"]["mixed"], 10.0)
        self.assertAlmostEqual(by_variant["ABL_NO_SIZE"]["mixed"], 0.0)
        # mean over capacities: (90 + 100) / 2 = 95 vs 100 -> -5 %
        self.assertAlmostEqual(by_variant["ABL_NO_DECAY"]["repeated"], -5.0)
        self.assertEqual(len(detail), len(VARIANTS) * 3 * 2)

    def test_seeds_are_averaged(self) -> None:
        rows = self.rows()
        for r in rows:
            if r["policy"] == "ABL_NO_LATENCY" and r["seed"] == "2":
                r["average_response_ms"] = "130.0"  # mean(110,130) = 120
        main, _ = build_tables(rows)
        self.assertAlmostEqual(
            {l["variant"]: l for l in main}["ABL_NO_LATENCY"]["repeated"], 20.0)

    def test_percent_of_means_not_mean_of_percents(self) -> None:
        # Full policy: 100 ms at 32 KiB, 200 ms at 128 KiB (mean 150).
        # Variant:     110 ms and 200 ms (mean 155) -> +3.33 %, not (10 + 0) / 2 = 5 %.
        rows = []
        for workload in ("repeated", "sequential", "mixed"):
            for cap, full, var in ((32, 100.0, 110.0), (128, 200.0, 200.0)):
                rows.append(row("CUSTOM", workload, cap, full))
                rows.append(row("ABL_NO_LATENCY", workload, cap, var))
                rows.append(row("ABL_NO_SIZE", workload, cap, full))
                rows.append(row("ABL_NO_DECAY", workload, cap, full))
        main, _ = build_tables(rows)
        self.assertAlmostEqual(
            {l["variant"]: l for l in main}["ABL_NO_LATENCY"]["mixed"], 5 / 150 * 100)

    def test_zero_base_gives_nan_not_crash(self) -> None:
        self.assertTrue(percent_change(1.0, 0.0) != percent_change(1.0, 0.0))

    def test_registry_defines_one_change_per_variant(self) -> None:
        registry, params = build_registry(20)
        self.assertEqual(params["CUSTOM"], {"half_life": 20})
        self.assertEqual(params["ABL_NO_LATENCY"], {"half_life": 20, "use_latency": False})
        self.assertEqual(params["ABL_NO_SIZE"], {"half_life": 20, "use_size": False})
        self.assertEqual(params["ABL_NO_DECAY"], {"half_life": float("inf")})
        self.assertTrue(all(name in registry for name in params))


if __name__ == "__main__":
    unittest.main()
