import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "d_experiments"))
import run_all  # noqa: E402


class FakeResult:
    def __init__(self, code):
        self.returncode = code


def args_for(out, **kw):
    base = dict(output_dir=out, seeds=[20261111, 20261112], scale="small",
                half_life=None, bar_capacity=512)
    base.update(kw)
    return SimpleNamespace(**base)


class CliTests(unittest.TestCase):
    def test_help_smoke(self):
        r = subprocess.run([sys.executable, str(ROOT / "d_experiments" / "run_all.py"), "--help"],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        for flag in ("--output-dir", "--seeds", "--scale", "--half-life"):
            self.assertIn(flag, r.stdout)

    def test_tuning_seed_and_single_seed_refused(self):
        for bad in (["--seeds", "31415", "1"], ["--seeds", "20261111"]):
            with self.assertRaises(SystemExit) as cm:
                run_all.main(bad)
            self.assertNotEqual(cm.exception.code, 0)

    def test_duplicate_seeds_refused(self):
        with self.assertRaises(SystemExit) as cm:
            run_all.main(["--seeds", "1", "1", "2"])
        self.assertNotEqual(cm.exception.code, 0)

    def test_non_finite_or_non_positive_half_life_refused(self):
        for bad in ("nan", "inf", "-1", "0"):
            with self.assertRaises(SystemExit) as cm:
                run_all.main(["--half-life", bad])
            self.assertNotEqual(cm.exception.code, 0)

    def test_committed_results_dir_refused(self):
        with self.assertRaises(SystemExit):
            run_all.check_output_dir(ROOT / "data" / "results")
        with self.assertRaises(SystemExit):
            run_all.check_output_dir(ROOT / "data" / "results" / "main")
        run_all.check_output_dir(ROOT / "data" / "experiments" / "run_all")


class OrchestrationTests(unittest.TestCase):
    def fake_runner(self, calls, fail_on=None, chosen=100):
        def runner(command, cwd=None):
            name = Path(command[1]).name
            calls.append(command)
            if name == "run_h_tuning.py":
                out = Path(command[command.index("--output-dir") + 1])
                out.mkdir(parents=True, exist_ok=True)
                (out / "h_choice.json").write_text(json.dumps({"chosen_half_life": chosen}))
            return FakeResult(1 if name == fail_on else 0)
        return runner

    def test_order_and_h_is_read_from_choice_file(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            code = run_all.run_pipeline(args_for(Path(tmp)), self.fake_runner(calls, chosen=100))
        self.assertEqual(code, 0)
        self.assertEqual([Path(c[1]).name for c in calls],
                         ["run_h_tuning.py", "run_main.py", "analyze_fairness.py",
                          "run_ablation.py", "run_drift.py", "make_plots.py"])
        for c in calls:
            name = Path(c[1]).name
            if name in ("run_main.py", "run_ablation.py"):
                self.assertEqual(float(c[c.index("--half-life") + 1]), 100.0)
            elif name == "run_drift.py":
                # The confirmatory drift test keeps its preregistered H and seeds.
                self.assertEqual(float(c[c.index("--half-life") + 1]), 20.0)
                self.assertEqual(c[c.index("--seeds") + 1:],
                                 [str(seed) for seed in run_all.DRIFT_SEEDS])
        fairness = next(c for c in calls if Path(c[1]).name == "analyze_fairness.py")
        self.assertEqual(fairness[fairness.index("--seeds") + 1:],
                         ["20261111", "20261112"])

    def test_relative_output_dir_is_resolved_before_child_stages(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                code = run_all.run_pipeline(args_for(Path("relative-out")),
                                            self.fake_runner(calls))
            finally:
                os.chdir(previous)
        self.assertEqual(code, 0)
        for c in calls:
            if "--output-dir" in c:
                self.assertTrue(
                    Path(c[c.index("--output-dir") + 1]).is_absolute(), c)

    def test_manual_half_life_overrides(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            run_all.run_pipeline(args_for(Path(tmp), half_life=7.0), self.fake_runner(calls))
            log = json.loads((Path(tmp) / "run_all.json").read_text())
        self.assertEqual(log["half_life_used"], 7.0)
        self.assertEqual(log["chosen_half_life"], 100.0)
        drift = next(c for c in calls if Path(c[1]).name == "run_drift.py")
        self.assertEqual(float(drift[drift.index("--half-life") + 1]), 20.0)

    def test_failure_stops_and_propagates(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            code = run_all.run_pipeline(args_for(Path(tmp)),
                                        self.fake_runner(calls, fail_on="run_ablation.py"))
        self.assertEqual(code, 1)
        names = [Path(c[1]).name for c in calls]
        self.assertEqual(names[-1], "run_ablation.py")
        self.assertNotIn("run_drift.py", names)
        self.assertNotIn("make_plots.py", names)


class EndToEndTests(unittest.TestCase):
    def test_small_pipeline_produces_all_outputs(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "data") as tmp:
            out = Path(tmp) / "run"
            code = run_all.main(["--output-dir", str(out), "--scale", "small",
                                 "--seeds", "20261111", "20261112"])
            self.assertEqual(code, 0)
            for rel in ("h-tuning/h_choice.json", "main/main_table.csv", "main/fairness.csv",
                        "main/per_client.csv", "ablation/ablation_table.csv",
                        "drift/drift_table.csv", "figures/response_time_vs_capacity.png",
                        "figures/h_sensitivity.png", "run_all.json"):
                self.assertTrue((out / rel).is_file(), rel)
            chosen = json.loads((out / "h-tuning/h_choice.json").read_text())["chosen_half_life"]
            manifest = json.loads((out / "main/seed_20261111/manifest.json").read_text())
            self.assertEqual(manifest["policy_parameters"]["CUSTOM"]["half_life"], chosen)


if __name__ == "__main__":
    unittest.main()
