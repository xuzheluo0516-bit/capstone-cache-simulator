"""CSV parsing and validation for resource metadata and request traces."""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from .models import Request, Resource, ResourceKey

RESOURCE_FIELDS = (
    "scheme",
    "host",
    "path",
    "status_code",
    "content_type",
    "size_bytes",
    "origin_latency_ms",
    "cache_control",
)
REQUEST_FIELDS = (
    "timestamp",
    "client_id",
    "method",
    "scheme",
    "host",
    "path",
)

_NON_NEGATIVE_INTEGER = re.compile(r"^[0-9]+$")


class InputValidationError(ValueError):
    """A parse or validation error with a useful file location."""

    def __init__(
        self,
        message: str,
        *,
        path: Path | str | None = None,
        line: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.path = Path(path) if path is not None else None
        self.line = line

    def __str__(self) -> str:
        if self.path is None:
            return self.message
        location = str(self.path)
        if self.line is not None:
            location = f"{location}:{self.line}"
        return f"{location}: {self.message}"


@dataclass(frozen=True, slots=True)
class SimulationInputs:
    """Validated resources and requests ready for a simulation run."""

    resources: Mapping[ResourceKey, Resource]
    requests: tuple[Request, ...]


def load_inputs(
    resources_path: str | Path,
    requests_path: str | Path,
) -> SimulationInputs:
    """Load both input files, resolving every request against the resources."""

    resources = parse_resources(resources_path)
    requests = parse_requests(requests_path, resources)
    return SimulationInputs(resources=resources, requests=requests)


def parse_resources(path: str | Path) -> dict[ResourceKey, Resource]:
    """Parse a resources CSV into resources keyed by ``(scheme, host, path)``."""

    csv_path = Path(path)
    rows = _read_csv(csv_path, RESOURCE_FIELDS)
    resources: dict[ResourceKey, Resource] = {}
    key_lines: dict[ResourceKey, int] = {}

    for line, row in rows:
        key = ResourceKey(
            scheme=_required(row, "scheme", csv_path, line),
            host=_required(row, "host", csv_path, line),
            path=_required(row, "path", csv_path, line),
        )
        if key in resources:
            raise InputValidationError(
                f"duplicate resource key {key!r}; first declared on line "
                f"{key_lines[key]}",
                path=csv_path,
                line=line,
            )

        size_text = _required(row, "size_bytes", csv_path, line)
        if not _NON_NEGATIVE_INTEGER.fullmatch(size_text):
            raise InputValidationError(
                f"size_bytes for resource {key!r} must be a non-negative "
                f"integer, got {size_text!r}",
                path=csv_path,
                line=line,
            )

        latency_text = _required(row, "origin_latency_ms", csv_path, line)
        try:
            latency = float(latency_text)
        except ValueError as exc:
            raise InputValidationError(
                f"origin_latency_ms for resource {key!r} must be a "
                f"non-negative number, got {latency_text!r}",
                path=csv_path,
                line=line,
            ) from exc
        if not math.isfinite(latency) or latency < 0:
            raise InputValidationError(
                f"origin_latency_ms for resource {key!r} must be a finite "
                f"non-negative number, got {latency_text!r}",
                path=csv_path,
                line=line,
            )

        status_text = _required(row, "status_code", csv_path, line)
        try:
            status_code = int(status_text)
        except ValueError as exc:
            raise InputValidationError(
                f"status_code for resource {key!r} must be an integer, "
                f"got {status_text!r}",
                path=csv_path,
                line=line,
            ) from exc
        if not 100 <= status_code <= 599:
            raise InputValidationError(
                f"status_code for resource {key!r} must be between 100 and "
                f"599, got {status_code}",
                path=csv_path,
                line=line,
            )

        resources[key] = Resource(
            key=key,
            status_code=status_code,
            content_type=_required(row, "content_type", csv_path, line),
            size_bytes=int(size_text),
            origin_latency_ms=latency,
            cache_control=row["cache_control"].strip(),
        )
        key_lines[key] = line

    return resources


def parse_requests(
    path: str | Path,
    resources: Mapping[ResourceKey, Resource],
) -> tuple[Request, ...]:
    """Parse a request CSV and assign stable sequence numbers.

    Requests are sorted by timestamp with Python's stable sort. Requests with
    equal timestamps therefore retain their order from the source file.
    """

    csv_path = Path(path)
    rows = _read_csv(csv_path, REQUEST_FIELDS, allow_empty=True)
    parsed: list[tuple[datetime, str, ResourceKey, int]] = []
    timestamp_kinds: set[bool] = set()

    for line, row in rows:
        timestamp_text = _required(row, "timestamp", csv_path, line)
        try:
            timestamp = _parse_timestamp(timestamp_text)
        except ValueError as exc:
            raise InputValidationError(
                f"invalid timestamp {timestamp_text!r}",
                path=csv_path,
                line=line,
            ) from exc
        timestamp_kinds.add(timestamp.tzinfo is not None)

        client_id = _required(row, "client_id", csv_path, line)
        method = _required(row, "method", csv_path, line)
        if method != "GET":
            raise InputValidationError(
                f"unsupported HTTP method {method!r} for client "
                f"{client_id!r}; only GET is allowed",
                path=csv_path,
                line=line,
            )

        key = ResourceKey(
            scheme=_required(row, "scheme", csv_path, line),
            host=_required(row, "host", csv_path, line),
            path=_required(row, "path", csv_path, line),
        )
        if key not in resources:
            raise InputValidationError(
                f"request references unknown resource {key!r}",
                path=csv_path,
                line=line,
            )

        parsed.append((timestamp, client_id, key, line))

    if len(timestamp_kinds) > 1:
        raise InputValidationError(
            "timestamps must either all include a timezone or all omit it",
            path=csv_path,
        )

    # Python's sort is stable, which is the required tie-breaking rule.
    parsed.sort(key=lambda item: item[0])
    return tuple(
        Request(
            timestamp=timestamp,
            client_id=client_id,
            method="GET",
            key=key,
            sequence=index,
            source_line=line,
        )
        for index, (timestamp, client_id, key, line) in enumerate(parsed, start=1)
    )


def _read_csv(
    path: Path,
    expected_fields: tuple[str, ...],
    *,
    allow_empty: bool = False,
) -> Iterable[tuple[int, dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, restkey="__extra__")
            if reader.fieldnames is None:
                if allow_empty:
                    return []
                raise InputValidationError(
                    "CSV is empty; expected a header row",
                    path=path,
                    line=1,
                )
            actual_fields = tuple(reader.fieldnames)
            if actual_fields != expected_fields:
                raise InputValidationError(
                    f"expected CSV header {expected_fields!r}, got "
                    f"{actual_fields!r}",
                    path=path,
                    line=1,
                )

            rows: list[tuple[int, dict[str, str]]] = []
            try:
                for row in reader:
                    line = reader.line_num
                    if "__extra__" in row:
                        raise InputValidationError(
                            "row has more fields than the header",
                            path=path,
                            line=line,
                        )
                    if any(value is None for value in row.values()):
                        raise InputValidationError(
                            "row has fewer fields than the header",
                            path=path,
                            line=line,
                        )
                    if all(not (row[field] or "").strip() for field in expected_fields):
                        raise InputValidationError(
                            "row is empty",
                            path=path,
                            line=line,
                        )
                    rows.append((line, row))
            except csv.Error as exc:
                raise InputValidationError(
                    f"invalid CSV syntax: {exc}",
                    path=path,
                    line=reader.line_num,
                ) from exc
            return rows
    except FileNotFoundError as exc:
        raise InputValidationError("file does not exist", path=path) from exc
    except UnicodeDecodeError as exc:
        raise InputValidationError("file is not valid UTF-8", path=path) from exc
    except OSError as exc:
        raise InputValidationError(f"cannot read file: {exc}", path=path) from exc


def _required(
    row: Mapping[str, str | None],
    field: str,
    path: Path,
    line: int,
) -> str:
    value = row.get(field)
    if value is None or not value.strip():
        raise InputValidationError(
            f"field {field!r} must not be empty",
            path=path,
            line=line,
        )
    return value.strip()


def _parse_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    return datetime.fromisoformat(normalized)
