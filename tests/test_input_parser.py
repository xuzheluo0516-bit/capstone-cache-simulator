from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from cache_simulator.input_parser import (
    REQUEST_FIELDS,
    RESOURCE_FIELDS,
    InputValidationError,
    load_inputs,
    parse_requests,
    parse_resources,
)
from cache_simulator.models import ResourceKey

REFERENCE_DIR = (
    Path(__file__).resolve().parents[1] / "data" / "reference"
)


class InputParserReferenceTests(unittest.TestCase):
    def test_reference_inputs_have_expected_counts_and_fields(self) -> None:
        inputs = load_inputs(
            REFERENCE_DIR / "resources.csv",
            REFERENCE_DIR / "requests_reference.csv",
        )

        self.assertEqual(len(inputs.resources), 21)
        self.assertEqual(len(inputs.requests), 15)
        self.assertEqual(
            inputs.resources[
                next(iter(inputs.resources))
            ].cache_control,
            "public, max-age=300",
        )
        self.assertEqual([request.sequence for request in inputs.requests], list(range(1, 16)))
        self.assertTrue(all(request.method == "GET" for request in inputs.requests))
        self.assertEqual(
            [
                request.timestamp
                for request in inputs.requests
            ],
            sorted(request.timestamp for request in inputs.requests),
        )
        with (REFERENCE_DIR / "resources.csv").open(newline="") as handle:
            for row in csv.DictReader(handle):
                key = ResourceKey(row["scheme"], row["host"], row["path"])
                with self.subTest(resource=key):
                    resource = inputs.resources[key]
                    self.assertEqual(resource.status_code, int(row["status_code"]))
                    self.assertEqual(resource.content_type, row["content_type"])
                    self.assertEqual(resource.size_bytes, int(row["size_bytes"]))
                    self.assertEqual(resource.origin_latency_ms, float(row["origin_latency_ms"]))
                    self.assertEqual(resource.cache_control, row["cache_control"])
        with (REFERENCE_DIR / "requests_reference.csv").open(newline="") as handle:
            expected = list(csv.DictReader(handle))
        for step, (request, row) in enumerate(zip(inputs.requests, expected), start=1):
            with self.subTest(step=step):
                self.assertEqual(request.timestamp, datetime.fromisoformat(row["timestamp"]))
                self.assertEqual(request.client_id, row["client_id"])
                self.assertEqual(request.method, row["method"])
                self.assertEqual(request.key, ResourceKey(row["scheme"], row["host"], row["path"]))
                self.assertEqual(request.sequence, step)
                self.assertEqual(request.source_line, step + 1)


class InputParserValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self._temp_dir.name)

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def write(self, name: str, content: str) -> Path:
        path = self.temp_path / name
        path.write_text(content, encoding="utf-8", newline="")
        return path

    def resource_csv(self, rows: str) -> Path:
        return self.write("resources.csv", ",".join(RESOURCE_FIELDS) + "\n" + rows)

    def request_csv(self, rows: str) -> Path:
        return self.write("requests.csv", ",".join(REQUEST_FIELDS) + "\n" + rows)

    def test_quoted_commas_and_non_integer_sizes(self) -> None:
        resources_path = self.resource_csv(
            'https,example.com,"/a,b",200,text/plain,12,4,"public, max-age=60"\n'
        )
        requests_path = self.request_csv(
            "2026-10-26T09:00:00Z,c1,GET,https,example.com,\"/a,b\"\n"
        )

        inputs = load_inputs(resources_path, requests_path)
        key = next(iter(inputs.resources))

        self.assertEqual(key.path, "/a,b")
        self.assertEqual(inputs.resources[key].cache_control, "public, max-age=60")
        self.assertEqual(inputs.requests[0].key, key)

    def test_out_of_order_and_equal_timestamps_are_stable(self) -> None:
        resources_path = self.resource_csv(
            "https,example.com,/a,200,text/plain,1,1,public\n"
        )
        resources = parse_resources(resources_path)
        requests_path = self.request_csv(
            "2026-10-26T09:00:02Z,third,GET,https,example.com,/a\n"
            "2026-10-26T09:00:01Z,first,GET,https,example.com,/a\n"
            "2026-10-26T09:00:01Z,second,GET,https,example.com,/a\n"
        )

        requests = parse_requests(requests_path, resources)

        self.assertEqual(
            [request.client_id for request in requests],
            ["first", "second", "third"],
        )
        self.assertEqual([request.sequence for request in requests], [1, 2, 3])

    def test_malformed_resource_quotes_report_csv_location(self) -> None:
        for row in (
            'https,example.com,"/a"junk,200,text/plain,1,1,public\n',
            'https,example.com,/a,200,text/plain,1,1,"public',
        ):
            with self.subTest(row=row):
                with self.assertRaisesRegex(
                    InputValidationError,
                    r"resources\.csv:2: invalid CSV syntax:",
                ):
                    parse_resources(self.resource_csv(row))

    def test_malformed_request_quotes_report_csv_location(self) -> None:
        resources = parse_resources(self.resource_csv(
            "https,example.com,/a,200,text/plain,1,1,public\n"
            "https,example.com,/ajunk,200,text/plain,1,1,public\n"
        ))
        for path in ('"/a"junk\n', '"/a'):
            with self.subTest(path=path):
                with self.assertRaisesRegex(
                    InputValidationError,
                    r"requests\.csv:2: invalid CSV syntax:",
                ):
                    parse_requests(self.request_csv(
                        "2026-10-26T09:00:00Z,c1,GET,https,example.com," + path
                    ), resources)

    def test_malformed_headers_report_csv_location(self) -> None:
        for name, fields, parse in (
            ("resources.csv", RESOURCE_FIELDS, parse_resources),
            ("requests.csv", REQUEST_FIELDS, lambda path: parse_requests(path, {})),
        ):
            for header in ('"' + fields[0] + '"junk,' + ','.join(fields[1:]),
                           '"' + ','.join(fields)):
                with self.subTest(name=name, header=header):
                    with self.assertRaisesRegex(
                        InputValidationError,
                        rf"{name}:1: invalid CSV syntax:",
                    ):
                        parse(self.write(name, header))

    def test_multiline_csv_error_reports_physical_line(self) -> None:
        with self.assertRaisesRegex(
            InputValidationError,
            r"resources\.csv:3: invalid CSV syntax:",
        ):
            parse_resources(self.resource_csv(
                'https,example.com,/a,200,text/plain,1,1,"public\nunfinished'
            ))

    def test_escaped_quotes_and_multiline_fields_are_legal(self) -> None:
        resources = parse_resources(self.resource_csv(
            'https,example.com,"/a,""b""",200,text/plain,1,1,"public,\nmax-age=60"\n'
        ))
        requests = parse_requests(self.request_csv(
            '2026-10-26T09:00:00Z,c1,GET,https,example.com,"/a,""b"""\n'
        ), resources)
        key = next(iter(resources))
        self.assertEqual(key.path, '/a,"b"')
        self.assertEqual(resources[key].cache_control, "public,\nmax-age=60")
        self.assertEqual(requests[0].key, key)

    def test_header_only_request_file_is_empty(self) -> None:
        resources_path = self.resource_csv(
            "https,example.com,/a,200,text/plain,1,1,public\n"
        )
        resources = parse_resources(resources_path)

        self.assertEqual(parse_requests(self.request_csv(""), resources), ())

    def test_zero_byte_request_file_is_empty(self) -> None:
        resources_path = self.resource_csv(
            "https,example.com,/a,200,text/plain,1,1,public\n"
        )
        resources = parse_resources(resources_path)

        self.assertEqual(parse_requests(self.write("requests.csv", ""), resources), ())

    def test_missing_csv_header_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            InputValidationError,
            r"resources\.csv:1: expected CSV header",
        ):
            parse_resources(
                self.write(
                    "resources.csv",
                    "https,example.com,/a,200,text/plain,1,1,public\n",
                )
            )

    def test_duplicate_resource_key_reports_line(self) -> None:
        row = "https,example.com,/a,200,text/plain,1,1,public\n"

        with self.assertRaisesRegex(
            InputValidationError,
            r"resources\.csv:3: duplicate resource key",
        ):
            parse_resources(self.resource_csv(row + row))

    def test_missing_field_reports_line(self) -> None:
        resources_path = self.resource_csv(
            "https,example.com,/a,200,text/plain,1,1,public\n"
        )
        resources = parse_resources(resources_path)
        requests_path = self.request_csv(
            "2026-10-26T09:00:00Z,c1,GET,https,example.com\n"
        )

        with self.assertRaisesRegex(
            InputValidationError,
            r"requests\.csv:2: row has fewer fields",
        ):
            parse_requests(requests_path, resources)

    def test_invalid_size_and_latency_include_resource_and_line(self) -> None:
        for size, latency, expected in (
            ("-1", "1", "size_bytes"),
            ("1.5", "1", "size_bytes"),
            ("1", "nan", "origin_latency_ms"),
            ("1", "-2", "origin_latency_ms"),
        ):
            with self.subTest(size=size, latency=latency):
                with self.assertRaisesRegex(
                    InputValidationError,
                    rf"resources\.csv:2:.*{expected}",
                ):
                    parse_resources(
                        self.resource_csv(
                            f"https,example.com,/a,200,text/plain,{size},"
                            f"{latency},public\n"
                        )
                    )

    def test_invalid_timestamp_and_non_get_are_rejected(self) -> None:
        resources_path = self.resource_csv(
            "https,example.com,/a,200,text/plain,1,1,public\n"
        )
        resources = parse_resources(resources_path)

        with self.assertRaisesRegex(InputValidationError, "invalid timestamp"):
            parse_requests(
                self.request_csv(
                    "not-a-timestamp,c1,GET,https,example.com,/a\n"
                ),
                resources,
            )

        with self.assertRaisesRegex(InputValidationError, "only GET is allowed"):
            parse_requests(
                self.request_csv(
                    "2026-10-26T09:00:00Z,c1,POST,https,example.com,/a\n"
                ),
                resources,
            )

    def test_unknown_resource_has_request_location_and_key(self) -> None:
        resources_path = self.resource_csv(
            "https,example.com,/a,200,text/plain,1,1,public\n"
        )
        resources = parse_resources(resources_path)

        with self.assertRaisesRegex(
            InputValidationError,
            r"requests\.csv:2: request references unknown resource",
        ):
            parse_requests(
                self.request_csv(
                    "2026-10-26T09:00:00Z,c1,GET,https,example.com,/missing\n"
                ),
                resources,
            )

    def test_zero_sizes_and_latencies_are_legal(self) -> None:
        resources = parse_resources(
            self.resource_csv(
                "https,example.com,/empty,204,text/plain,0,0,public\n"
            )
        )

        resource = next(iter(resources.values()))
        self.assertEqual(resource.size_bytes, 0)
        self.assertEqual(resource.origin_latency_ms, 0)

    def test_resource_identity_uses_all_three_key_fields(self) -> None:
        resources = parse_resources(self.resource_csv(
            "https,example.com,/a,200,text/plain,1,1,public\n"
            "http,example.com,/a,200,text/plain,2,2,public\n"
            "https,other.com,/a,200,text/plain,3,3,public\n"
            "https,example.com,/b,200,text/plain,4,4,public\n"
        ))
        self.assertEqual(len(resources), 4)
        self.assertEqual(
            resources[ResourceKey("http", "example.com", "/a")].size_bytes, 2
        )

    def test_extra_fields_are_rejected_in_both_input_files(self) -> None:
        with self.assertRaisesRegex(InputValidationError, "resources.csv:2: row has more fields"):
            parse_resources(self.resource_csv(
                "https,example.com,/a,200,text/plain,1,1,public,extra\n"
            ))
        with self.assertRaisesRegex(InputValidationError, "requests.csv:2: row has more fields"):
            parse_requests(self.request_csv(
                "2026-10-26T09:00:00Z,c1,GET,https,example.com,/a,extra\n"
            ), {})


if __name__ == "__main__":
    unittest.main()
