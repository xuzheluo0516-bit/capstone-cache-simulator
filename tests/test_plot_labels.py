import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "d_experiments"))
from make_plots import (  # noqa: E402
    POLICIES, per_client_bars, per_client_figure_path, single_workload,
)


def per_client_rows(workload="sequential"):
    rows = []
    for policy in POLICIES:
        for client in ("browser", "media"):
            rows.append({
                "workload": workload, "capacity_KiB": "32.0", "policy": policy,
                "client_id": client, "n_seeds": "5",
                "hit_rate_mean": "0.5", "avg_response_ms_mean": "10.0",
                "delta_vs_baseline_ms": "0.0",
            })
    return rows


class WorkloadLabelTests(unittest.TestCase):
    def test_single_workload_is_returned(self):
        self.assertEqual(single_workload(per_client_rows("repeated")), "repeated")

    def test_mixed_workloads_are_refused(self):
        rows = per_client_rows("sequential") + per_client_rows("repeated")
        with self.assertRaises(ValueError):
            single_workload(rows)

    def test_per_client_figure_name_follows_its_workload(self):
        rows = per_client_rows("sequential")
        with tempfile.TemporaryDirectory() as tmp:
            path = per_client_figure_path(rows, Path(tmp))
            self.assertEqual(path.name, "per_client_sequential.png")
            returned = per_client_bars(rows, 32.0, path)
            self.assertEqual(returned, path)
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
