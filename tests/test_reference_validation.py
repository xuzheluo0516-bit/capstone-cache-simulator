from __future__ import annotations

import csv
import io
import unittest
from pathlib import Path

from cache_simulator.output import OUTPUT_FIELDS
from cache_simulator.reference_validation import (
    ReferenceMismatchError,
    compare_csv_text,
    validate_reference_run,
)

REFERENCE_DIR = Path(__file__).resolve().parents[1] / "data" / "reference"


class ReferenceTraceValidationTests(unittest.TestCase):
    def test_all_standard_policies_match_every_reference_field(self) -> None:
        expected = {
            "FIFO": (3, 12, 421888, 90112, 95.33333333333333),
            "LRU": (3, 12, 403456, 108544, 92.33333333333333),
            "LFU": (4, 11, 370688, 141312, 84.33333333333333),
        }
        for policy, values in expected.items():
            with self.subTest(policy=policy):
                report = validate_reference_run(REFERENCE_DIR, policy)
                self.assertEqual(
                    (report.hits, report.misses, report.origin_bytes),
                    values[:3],
                )
                self.assertAlmostEqual(report.byte_hit_rate, values[3] / 512000)
                self.assertAlmostEqual(report.average_response_ms, values[4])
                self.assertAlmostEqual(report.request_hit_rate, values[0] / 15)

    def test_per_client_reference_metrics_are_correct(self) -> None:
        expected = {
            "FIFO": [
                ("student-01", 5, 1, 0.2, 111.0),
                ("student-02", 5, 2, 0.4, 55.0),
                ("student-03", 5, 0, 0.0, 120.0),
            ],
            "LRU": [
                ("student-01", 5, 2, 0.4, 87.0),
                ("student-02", 5, 1, 0.2, 70.0),
                ("student-03", 5, 0, 0.0, 120.0),
            ],
            "LFU": [
                ("student-01", 5, 2, 0.4, 87.0),
                ("student-02", 5, 1, 0.2, 70.0),
                ("student-03", 5, 1, 0.2, 96.0),
            ],
        }
        for policy, expected_clients in expected.items():
            with self.subTest(policy=policy):
                report = validate_reference_run(REFERENCE_DIR, policy)
                actual = [
                    (
                        client.client_id,
                        client.requests,
                        client.hits,
                        client.request_hit_rate,
                        client.average_response_ms,
                    )
                    for client in report.per_client
                ]
                self.assertEqual(actual, expected_clients)

    def test_comparator_ignores_line_endings_quoting_and_numeric_spelling(self) -> None:
        row = ["1", "A", "student,01", "MISS", "-", "A,B", "32", "5", "32768", "0"]
        expected_buffer = io.StringIO(newline="")
        csv.writer(expected_buffer, lineterminator="\r\n").writerow(OUTPUT_FIELDS)
        csv.writer(expected_buffer, lineterminator="\r\n").writerow(row)
        expected = expected_buffer.getvalue()

        actual_buffer = io.StringIO(newline="")
        writer = csv.writer(actual_buffer, lineterminator="\n")
        writer.writerow(OUTPUT_FIELDS)
        writer.writerow(
            ["1.0", "A", "student,01", "MISS", "-", "A,B", "32.0", "5.0", "32768.0", "0.0"]
        )
        compare_csv_text(expected, actual_buffer.getvalue(), policy="TEST")

    def test_comparator_reports_policy_step_and_wrong_field(self) -> None:
        expected = io.StringIO(newline="")
        writer = csv.writer(expected, lineterminator="\n")
        writer.writerow(OUTPUT_FIELDS)
        writer.writerow(["1", "A", "c1", "HIT", "-", "A", "1", "5", "0", "1"])
        actual = expected.getvalue().replace(",HIT,", ",MISS,")
        with self.assertRaisesRegex(
            ReferenceMismatchError,
            r"LRU step 1 field result: expected 'HIT', actual 'MISS'",
        ):
            compare_csv_text(expected.getvalue(), actual, policy="LRU")

    def test_comparator_detects_eviction_and_cumulative_counter_mismatch(self) -> None:
        expected = io.StringIO(newline="")
        writer = csv.writer(expected, lineterminator="\n")
        writer.writerow(OUTPUT_FIELDS)
        writer.writerow(["1", "A", "c1", "MISS", "-", "A", "1", "5", "10", "0"])
        actual = expected.getvalue().replace(",-,A,1,5,10,0", ",B,A,1,5,11,0")
        with self.assertRaisesRegex(ReferenceMismatchError, "field evicted"):
            compare_csv_text(expected.getvalue(), actual, policy="FIFO")
        actual = expected.getvalue().replace(",10,0", ",11,0")
        with self.assertRaisesRegex(ReferenceMismatchError, "field cumulative_origin_bytes"):
            compare_csv_text(expected.getvalue(), actual, policy="FIFO")

    def test_comparator_checks_header_order_and_row_count(self) -> None:
        header = ",".join(OUTPUT_FIELDS)
        with self.assertRaisesRegex(ReferenceMismatchError, "header mismatch"):
            compare_csv_text(header + "\n", ",".join(reversed(OUTPUT_FIELDS)) + "\n", policy="LFU")
        with self.assertRaisesRegex(ReferenceMismatchError, "row count mismatch"):
            compare_csv_text(header + "\n", header + "\n" + "1,A,c,HIT,-,A,1,5,0,1\n", policy="LFU")


    def test_comparator_rejects_rows_with_missing_or_extra_columns(self) -> None:
        header = ",".join(OUTPUT_FIELDS)
        missing = header + "\\n" + "1,A,c,HIT,-,A,1,5,0\\n"
        extra = header + "\\n" + "1,A,c,HIT,-,A,1,5,0,1,unexpected\\n"
        with self.assertRaisesRegex(ReferenceMismatchError, "malformed row 2"):
            compare_csv_text(header + "\\n", missing, policy="FIFO")
        with self.assertRaisesRegex(ReferenceMismatchError, "malformed row 2"):
            compare_csv_text(header + "\\n", extra, policy="FIFO")


if __name__ == "__main__":
    unittest.main()
