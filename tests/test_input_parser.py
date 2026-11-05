from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cache_simulator.input_parser import (
    REQUEST_FIELDS,
    RESOURCE_FIELDS,
    InputValidationError,
    load_inputs,
    parse_requests,
    parse_resources,
)

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


class InputParserValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self._temp_dir.name)

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def write(self, name: str, content: str) -> Path:
        path = self.temp_path / name
        path.write_text(content, encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
