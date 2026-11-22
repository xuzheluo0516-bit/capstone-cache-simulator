from __future__ import annotations

import csv
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from cache_simulator.cli import POLICY_REGISTRY, main
from cache_simulator.output import OUTPUT_FIELDS, render_events

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = REPO_ROOT / "data" / "reference"
RESOURCES = REFERENCE_DIR / "resources.csv"
REQUESTS = REFERENCE_DIR / "requests_reference.csv"


def run_cli(*extra: str) -> tuple[int, str, str]:
    argv = [
        "--resources",
        str(RESOURCES),
        "--requests",
        str(REQUESTS),
        *extra,
    ]
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class CommandLineTests(unittest.TestCase):
    def test_every_registered_policy_runs_on_reference_trace(self) -> None:
        for name in POLICY_REGISTRY:
            code, out, err = run_cli("--policy", name)
            self.assertEqual(code, 0, f"policy {name} failed: {err}")
            # One header row plus one row per reference request.
            self.assertEqual(len(out.strip().splitlines()), 16)

    def test_default_arguments_run_successfully(self) -> None:
        code, out, err = run_cli()
        self.assertEqual(code, 0, err)
        self.assertEqual(len(out.strip().splitlines()), 16)

    def test_custom_capacity_and_hit_latency_are_accepted(self) -> None:
        code, out, err = run_cli(
            "--capacity", "102400", "--hit-latency", "7.5"
        )
        self.assertEqual(code, 0, err)
        self.assertIn("7.5", out)

    def test_missing_resources_file_returns_nonzero(self) -> None:
        argv = [
            "--resources",
            "does-not-exist.csv",
            "--requests",
            str(REQUESTS),
        ]
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as context:
                main(argv)
        self.assertNotEqual(context.exception.code, 0)

    def test_invalid_policy_returns_nonzero(self) -> None:
        argv = [
            "--resources",
            str(RESOURCES),
            "--requests",
            str(REQUESTS),
            "--policy",
            "NOPE",
        ]
        err = io.StringIO()
        with redirect_stderr(err):
            with self.assertRaises(SystemExit) as context:
                main(argv)
        self.assertNotEqual(context.exception.code, 0)
        self.assertIn("invalid choice", err.getvalue())

    def test_render_events_uses_documented_columns(self) -> None:
        text = render_events([], [])
        self.assertEqual(
            next(csv.reader(io.StringIO(text, newline=""))),
            list(OUTPUT_FIELDS),
        )

    def test_repeated_calls_are_independent_and_identical(self) -> None:
        first_code, first_out, _ = run_cli("--policy", "LFU")
        second_code, second_out, _ = run_cli("--policy", "LFU")

        self.assertEqual(first_code, 0)
        self.assertEqual(second_code, 0)
        self.assertEqual(first_out, second_out)

    def test_negative_capacity_returns_nonzero(self) -> None:
        argv = [
            "--resources",
            str(RESOURCES),
            "--requests",
            str(REQUESTS),
            "--capacity",
            "-1",
        ]
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as context:
                main(argv)
        self.assertNotEqual(context.exception.code, 0)

    def test_negative_hit_latency_returns_nonzero(self) -> None:
        argv = [
            "--resources",
            str(RESOURCES),
            "--requests",
            str(REQUESTS),
            "--hit-latency",
            "-0.5",
        ]
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as context:
                main(argv)
        self.assertNotEqual(context.exception.code, 0)

    def test_non_finite_hit_latency_returns_nonzero(self) -> None:
        for bad in ("nan", "inf"):
            argv = [
                "--resources",
                str(RESOURCES),
                "--requests",
                str(REQUESTS),
                "--hit-latency",
                bad,
            ]
            with redirect_stderr(io.StringIO()):
                code = main(argv)
            self.assertNotEqual(code, 0, f"latency {bad} must be rejected")


if __name__ == "__main__":
    unittest.main()
