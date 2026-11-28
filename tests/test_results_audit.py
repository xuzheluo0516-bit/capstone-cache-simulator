"""Regression checks for the committed formal-result audit."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.audit_results import audit_run_manifest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "audit_results.py"
RESULTS = REPO / "data" / "results"


class ResultsAuditTests(unittest.TestCase):
    def test_committed_results_pass(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--results-dir", str(RESULTS)],
            cwd=REPO, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS main: 375", result.stdout)
        self.assertIn("PASS drift: 150", result.stdout)

    def test_missing_run_is_rejected(self):
        source = RESULTS / "main" / "seed_20261111" / "manifest.json"
        data = json.loads(source.read_text(encoding="utf-8"))
        data["runs"].pop()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "run count mismatch"):
                audit_run_manifest(
                    path, 20261111, ("FIFO", "LRU", "LFU", "GDSF", "CUSTOM")
                )


if __name__ == "__main__":
    unittest.main()
