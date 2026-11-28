"""Regression tests for the PR #32 review findings (real processes, no mocks)."""

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "d_experiments"))
import analyze_fairness  # noqa: E402
import common  # noqa: E402

HEADER = ("workload,capacity_bytes,policy,seed,client_id,"
          "request_hit_rate,average_response_ms\n")
EXPECTED_MANIFESTS = 12
RUN_ALL_TIMEOUT_SECONDS = 240


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_seed(root, seed, hits, response_ms=10):
    """Write one synthetic seed directory; hits maps client_id to hit rate."""
    seed_dir = root / f"seed_{seed}"
    seed_dir.mkdir(parents=True)
    rows = "".join(
        f"mixed,32768,{policy},{seed},{client},{hit},{response_ms}\n"
        for policy in ("LRU", "LFU")
        for client, hit in hits.items()
    )
    (seed_dir / "clients.csv").write_text(HEADER + rows, encoding="utf-8")


class RelativeOutputFromOtherCwdTests(unittest.TestCase):
    def test_run_all_with_relative_output_dir_from_outside_the_repo(self):
        with tempfile.TemporaryDirectory(prefix="review-run-all-") as tmp:
            launch_dir = Path(tmp)
            relative_output = f"relative-output-{uuid.uuid4().hex}"
            env = os.environ.copy()
            src = str(ROOT / "src")
            existing = env.get("PYTHONPATH")
            env["PYTHONPATH"] = src + (os.pathsep + existing if existing else "")
            result = subprocess.run(
                [sys.executable, str(ROOT / "d_experiments" / "run_all.py"),
                 "--output-dir", relative_output, "--scale", "small",
                 "--seeds", "20261111", "20261112"],
                cwd=launch_dir, capture_output=True, text=True,
                env=env, timeout=RUN_ALL_TIMEOUT_SECONDS)
            self.assertEqual(result.returncode, 0, result.stderr)
            out = launch_dir / relative_output
            for rel in ("h-tuning/h_choice.json", "main/main_table.csv",
                        "main/fairness.csv", "main/per_client.csv",
                        "ablation/ablation_table.csv", "drift/drift_table.csv",
                        "figures/h_sensitivity.png", "run_all.json"):
                self.assertTrue((out / rel).is_file(), rel)
            self.assertFalse((ROOT / relative_output).exists(),
                             "relative output was resolved against the repository root")


class FairnessIgnoresStaleSeedsTests(unittest.TestCase):
    def test_stale_seed_directories_never_enter_the_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_seed(root, 1, {"a": "0.5", "b": "0.5"})
            write_seed(root, 2, {"a": "0.5", "b": "0.5"})
            # Uneven stale hits would change both the per-client means and Jain.
            write_seed(root, 99, {"a": "0.0", "b": "0.2"})
            self.assertEqual(analyze_fairness.main(
                ["--results-dir", tmp, "--seeds", "1", "2"]), 0)

            per_client = read_csv(root / "per_client.csv")
            fairness = read_csv(root / "fairness.csv")
            self.assertEqual(len(per_client), 4)
            self.assertEqual(len(fairness), 2)
            for row in per_client:
                self.assertEqual(row["n_seeds"], "2")
                self.assertAlmostEqual(float(row["hit_rate_mean"]), 0.5)
            for row in fairness:
                self.assertEqual(row["n_seeds"], "2")
                self.assertAlmostEqual(float(row["jain_mean"]), 1.0)
                self.assertAlmostEqual(float(row["jain_std"]), 0.0)
            self.assertEqual({row["worst_client_id"] for row in fairness}, {"b"})


class FairnessSeedSetShrinkTests(unittest.TestCase):
    def run_main(self, root, seeds):
        self.assertEqual(analyze_fairness.main(
            ["--results-dir", str(root), "--seeds", *map(str, seeds)]), 0)
        return read_csv(root / "fairness.csv"), read_csv(root / "per_client.csv")

    def test_shrinking_the_seed_set_changes_the_actual_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            both_root = Path(tmp) / "both"
            one_root = Path(tmp) / "one"
            for root in (both_root, one_root):
                write_seed(root, 1, {"a": "0.5", "b": "0.5"})
                # Seed 2 has mean hit rate 0.9 but uneven clients, so Jain moves too.
                write_seed(root, 2, {"a": "1.0", "b": "0.8"})

            both_fair, both_per = self.run_main(both_root, (1, 2))
            one_fair, one_per = self.run_main(one_root, (1,))

            self.assertEqual(len(both_fair), 2)
            self.assertEqual(len(one_fair), 2)
            self.assertEqual({row["n_seeds"] for row in both_fair}, {"2"})
            self.assertEqual({row["n_seeds"] for row in one_fair}, {"1"})

            both_jain = {row["policy"]: float(row["jain_mean"]) for row in both_fair}
            one_jain = {row["policy"]: float(row["jain_mean"]) for row in one_fair}
            expected_both_jain = (1.0 + analyze_fairness.jain([1.0, 0.8])) / 2
            for policy in ("LRU", "LFU"):
                self.assertAlmostEqual(both_jain[policy], expected_both_jain)
                self.assertAlmostEqual(one_jain[policy], 1.0)
            self.assertLess(both_jain["LRU"], one_jain["LRU"])

            both_by_key = {(row["policy"], row["client_id"]): row for row in both_per}
            one_by_key = {(row["policy"], row["client_id"]): row for row in one_per}
            self.assertEqual(len(both_by_key), 4)
            self.assertEqual(len(one_by_key), 4)
            self.assertEqual(both_by_key[("LRU", "a")]["n_seeds"], "2")
            self.assertAlmostEqual(float(both_by_key[("LRU", "a")]["hit_rate_mean"]), 0.75)
            self.assertAlmostEqual(float(both_by_key[("LRU", "b")]["hit_rate_mean"]), 0.65)
            self.assertEqual(one_by_key[("LRU", "a")]["n_seeds"], "1")
            self.assertAlmostEqual(float(one_by_key[("LRU", "a")]["hit_rate_mean"]), 0.5)
            self.assertAlmostEqual(float(one_by_key[("LRU", "b")]["hit_rate_mean"]), 0.5)


class ProvenanceTests(unittest.TestCase):
    def test_committed_manifests_match_the_current_experiment_scripts(self):
        current = common.experiment_source_sha256()
        manifests = sorted((ROOT / "data" / "results").glob("**/manifest.json"))
        self.assertEqual(
            len(manifests), EXPECTED_MANIFESTS,
            f"expected {EXPECTED_MANIFESTS} committed manifests, found {len(manifests)}")
        for path in manifests:
            text = path.read_text(encoding="utf-8")

            def reject(constant):
                raise ValueError(f"{path}: non-strict JSON constant {constant}")

            manifest = json.loads(text, parse_constant=reject)
            self.assertEqual(
                manifest.get("experiment_source_sha256"), current,
                f"{path}: results were not produced by the current d_experiments/*.py; "
                "re-run or update the scripts back")


if __name__ == "__main__":
    unittest.main()
