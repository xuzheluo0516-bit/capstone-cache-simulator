"""Regression checks for the committed formal-result audit."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.audit_results import audit_run_manifest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "audit_results.py"
RESULTS = REPO / "data" / "results"


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class ResultsAuditTests(unittest.TestCase):
    def _copy_course(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "results"
        shutil.copytree(RESULTS / "course", root / "course")
        return root

    def _audit_course_copy(self, root: Path) -> dict[str, int]:
        from scripts.audit_results import audit_course, source_hash

        return audit_course(
            root,
            REPO,
            source_hash(REPO / "d_experiments"),
            source_hash(REPO / "src" / "cache_simulator"),
        )

    def test_committed_results_pass(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--results-dir", str(RESULTS)],
            cwd=REPO, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS main: 375", result.stdout)
        self.assertIn("PASS drift: 150", result.stdout)
        self.assertIn("PASS course_runs: 90", result.stdout)
        self.assertIn("PASS course_clients: 540", result.stdout)
        self.assertIn("PASS course_fairness: 90", result.stdout)
        self.assertIn("PASS course_h_sensitivity: 90", result.stdout)
        self.assertIn("PASS course_workload_summary: 3", result.stdout)
        self.assertIn("PASS course_top5: 15", result.stdout)
        self.assertIn("PASS course_workload_distribution: 63", result.stdout)

    def test_course_workload_summary_total_requests_tampering_is_rejected(self):
        root = self._copy_course()
        path = root / "course" / "workload_summary.csv"
        fields, rows = read_csv(path)
        rows[0]["total_requests"] = str(int(rows[0]["total_requests"]) + 1)
        write_csv(path, fields, rows)
        with self.assertRaisesRegex(ValueError, "total_requests differs"):
            self._audit_course_copy(root)

    def test_course_workload_summary_bytes_tampering_is_rejected(self):
        root = self._copy_course()
        path = root / "course" / "workload_summary.csv"
        fields, rows = read_csv(path)
        rows[0]["total_requested_bytes"] = str(int(rows[0]["total_requested_bytes"]) + 1)
        write_csv(path, fields, rows)
        with self.assertRaisesRegex(ValueError, "total_requested_bytes differs"):
            self._audit_course_copy(root)

    def test_course_workload_summary_threshold_tampering_is_rejected(self):
        root = self._copy_course()
        path = root / "course" / "workload_summary.csv"
        fields, rows = read_csv(path)
        rows[0]["requests_larger_than_5120KiB"] = str(int(rows[0]["requests_larger_than_5120KiB"]) + 1)
        write_csv(path, fields, rows)
        with self.assertRaisesRegex(ValueError, "requests_larger_than_5120KiB differs"):
            self._audit_course_copy(root)

    def test_course_workload_summary_distinct_resources_tampering_is_rejected(self):
        root = self._copy_course()
        path = root / "course" / "workload_summary.csv"
        fields, rows = read_csv(path)
        rows[0]["distinct_resources"] = str(int(rows[0]["distinct_resources"]) + 1)
        write_csv(path, fields, rows)
        with self.assertRaisesRegex(ValueError, "distinct_resources differs"):
            self._audit_course_copy(root)

    def test_course_top5_requests_tampering_is_rejected(self):
        root = self._copy_course()
        path = root / "course" / "workload_top5.csv"
        fields, rows = read_csv(path)
        rows[0]["requests"] = str(int(rows[0]["requests"]) + 1)
        write_csv(path, fields, rows)
        with self.assertRaisesRegex(ValueError, "workload_top5: requests differs"):
            self._audit_course_copy(root)

    def test_course_top5_share_tampering_is_rejected(self):
        root = self._copy_course()
        path = root / "course" / "workload_top5.csv"
        fields, rows = read_csv(path)
        rows[0]["share"] = "0.0"
        write_csv(path, fields, rows)
        with self.assertRaisesRegex(ValueError, "workload_top5: share differs"):
            self._audit_course_copy(root)

    def test_course_h_sensitivity_value_tampering_is_rejected(self):
        root = self._copy_course()
        path = root / "course" / "course_h_sensitivity.csv"
        fields, rows = read_csv(path)
        rows[0]["average_response_ms"] = "0.0"
        write_csv(path, fields, rows)
        with self.assertRaisesRegex(ValueError, "course_h_sensitivity: average_response_ms differs"):
            self._audit_course_copy(root)

    def test_course_manifest_tampering_is_rejected(self):
        root = self._copy_course()
        path = root / "course" / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["completed_runs"] = 89
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "run count differs"):
            self._audit_course_copy(root)

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

    def test_course_distribution_missing_is_rejected(self):
        root = self._copy_course()
        (root / "course" / "workload_distribution.csv").unlink()
        with self.assertRaises(FileNotFoundError):
            self._audit_course_copy(root)

    def test_course_distribution_requests_tampering_is_rejected(self):
        root = self._copy_course()
        path = root / "course" / "workload_distribution.csv"
        fields, rows = read_csv(path)
        rows[0]["requests"] = str(int(rows[0]["requests"]) + 1)
        write_csv(path, fields, rows)
        with self.assertRaisesRegex(ValueError, "request count differs"):
            self._audit_course_copy(root)

    def test_course_distribution_size_tampering_is_rejected(self):
        root = self._copy_course()
        path = root / "course" / "workload_distribution.csv"
        fields, rows = read_csv(path)
        rows[0]["size_bytes"] = str(int(rows[0]["size_bytes"]) + 1)
        write_csv(path, fields, rows)
        with self.assertRaisesRegex(ValueError, "size differs"):
            self._audit_course_copy(root)

    def test_course_distribution_duplicate_row_is_rejected(self):
        root = self._copy_course()
        path = root / "course" / "workload_distribution.csv"
        fields, rows = read_csv(path)
        rows.append(dict(rows[0]))
        write_csv(path, fields, rows)
        with self.assertRaisesRegex(ValueError, "duplicate rows"):
            self._audit_course_copy(root)

    def test_course_distribution_missing_row_is_rejected(self):
        root = self._copy_course()
        path = root / "course" / "workload_distribution.csv"
        fields, rows = read_csv(path)
        rows.pop()
        write_csv(path, fields, rows)
        with self.assertRaisesRegex(ValueError, "expected 63 rows"):
            self._audit_course_copy(root)

    def test_course_run_average_response_tampering_is_rejected(self):
        root = self._copy_course()
        path = root / "course" / "course_runs.csv"
        fields, rows = read_csv(path)
        rows[0]["average_response_ms"] = "0.0"
        write_csv(path, fields, rows)
        with self.assertRaisesRegex(ValueError, "average_response_ms differs"):
            self._audit_course_copy(root)

    def test_course_fairness_jain_tampering_is_rejected(self):
        root = self._copy_course()
        path = root / "course" / "course_fairness.csv"
        fields, rows = read_csv(path)
        rows[0]["jain"] = "0.0"
        write_csv(path, fields, rows)
        with self.assertRaisesRegex(ValueError, "Jain differs"):
            self._audit_course_copy(root)

    def test_course_input_hash_tampering_is_rejected(self):
        root = self._copy_course()
        path = root / "course" / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["input_sha256"]["resources.csv"] = "0" * 64
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "input resources.csv differs"):
            self._audit_course_copy(root)

    def test_course_source_hash_tampering_is_rejected(self):
        root = self._copy_course()
        path = root / "course" / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["source_sha256"] = "0" * 64
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "core source hash differs"):
            self._audit_course_copy(root)


if __name__ == "__main__":
    unittest.main()
