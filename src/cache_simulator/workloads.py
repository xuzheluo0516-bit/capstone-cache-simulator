"""Deterministic, parser-compatible traces for experiment workloads."""

from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .input_parser import REQUEST_FIELDS, RESOURCE_FIELDS, load_inputs

DEFAULT_COUNTS = {"small": 72, "medium": 360, "large": 1440}
KINDS = ("repeated", "sequential", "mixed")
ALL_KINDS = (*KINDS, "loop")
SEQUENTIAL_REPEAT_PROBABILITY = 0.125
MIXED_OVERSIZED_INTERVAL = 100
START = datetime(2026, 11, 1, tzinfo=timezone.utc)
HOST = "experiment.example.invalid"
SIZES_KIB = (8, 12, 16, 20, 24, 32, 40, 48, 64, 96, 128, 384)
CAPACITIES_BYTES = tuple(kib * 1024 for kib in (32, 128, 256, 512, 1024))


@dataclass(frozen=True)
class Workload:
    kind: str
    scale: str
    seed: int
    count: int
    resources_path: Path
    requests_path: Path
    metadata_path: Path


def _catalog(*, sequential_pool_size: int = 0) -> list[dict[str, str]]:
    rows = []
    for index, size_kib in enumerate(SIZES_KIB):
        rows.append({
            "scheme": "https", "host": HOST, "path": f"/object/{index:02d}",
            "status_code": "200", "content_type": "application/octet-stream",
            "size_bytes": str(size_kib * 1024),
            "origin_latency_ms": str(40 + index * 13),
            "cache_control": "public, max-age=3600",
        })
    # This request is intentionally too large for every configured capacity.
    rows.append({
        "scheme": "https", "host": HOST, "path": "/video/oversized.mp4",
        "status_code": "200", "content_type": "video/mp4",
        "size_bytes": str(44 * 1024 * 1024), "origin_latency_ms": "1500",
        "cache_control": "public, max-age=3600",
    })
    # Append new URLs after catalog[12], which the mixed trace uses as the
    # oversized video. This keeps every existing repeated/mixed index stable.
    extra_sizes_kib = (16, 24, 32, 48, 64, 96, 128, 192, 256)
    for offset in range(sequential_pool_size):
        rows.append({
            "scheme": "https", "host": HOST,
            "path": f"/sequential/{offset:04d}",
            "status_code": "200", "content_type": "application/octet-stream",
            "size_bytes": str(extra_sizes_kib[offset % len(extra_sizes_kib)] * 1024),
            "origin_latency_ms": str(55 + offset % 31 * 7),
            "cache_control": "public, max-age=3600",
        })
    return rows


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _request(index: int, client: str, resource: dict[str, str]) -> dict[str, str]:
    return {
        "timestamp": (START + timedelta(seconds=index)).isoformat().replace("+00:00", "Z"),
        "client_id": client, "method": "GET", "scheme": resource["scheme"],
        "host": resource["host"], "path": resource["path"],
    }


def _trace(kind: str, count: int, rng: random.Random, catalog: list[dict[str, str]]) -> list[dict[str, str]]:
    if count < 24:
        raise ValueError("each workload needs at least 24 requests")
    rows: list[dict[str, str]] = []
    if kind == "repeated":
        for index in range(count):
            resource = catalog[rng.randrange(4 if rng.random() < 0.85 else 12)]
            rows.append(_request(index, "repeat-reader", resource))
    elif kind == "sequential":
        # Mostly first visits from a pool large enough for this trace. Randomly
        # place about 12.5% revisits so even short traces keep that intended
        # rate; each revisit draws from prior first visits.
        fresh = list(range(13, len(catalog)))
        rng.shuffle(fresh)
        repeat_positions = set(rng.sample(range(1, count), round(count * SEQUENTIAL_REPEAT_PROBABILITY)))
        seen: list[int] = []
        for index in range(count):
            if index in repeat_positions:
                resource_index = rng.choice(seen)
            else:
                if not fresh:
                    raise ValueError("sequential resource pool exhausted")
                resource_index = fresh.pop()
                seen.append(resource_index)
            rows.append(_request(index, "sequential-reader", catalog[resource_index]))
    elif kind == "loop":
        # Keep the previous 12-object loop as an optional worst-case trace.
        for index in range(count):
            rows.append(_request(index, "sequential-reader", catalog[index % 12]))
    elif kind == "mixed":
        # The fixed prefix creates observable competition at 512 KiB: small
        # objects occupy the cache before a fitting 384 KiB object arrives.
        prefix = [("browser", i) for i in range(11)] + [
            ("media", 11), ("browser", 0), ("media", 12),
        ]
        for index in range(count):
            if index < len(prefix):
                client, resource_index = prefix[index]
            elif index % MIXED_OVERSIZED_INTERVAL == 0:
                client, resource_index = "media", 12
            else:
                client = ("browser", "media", "random")[index % 3]
                if client == "browser":
                    resource_index = rng.randrange(4)
                elif client == "media":
                    resource_index = rng.choice((10, 11, 11))
                else:
                    resource_index = rng.randrange(12)
            rows.append(_request(index, client, catalog[resource_index]))
    else:
        raise ValueError(f"unknown workload kind: {kind}")
    return rows


def generate_suite(
    output_dir: Path,
    *,
    seed: int,
    counts: dict[str, int] | None = None,
    kinds: tuple[str, ...] = KINDS,
) -> tuple[Workload, ...]:
    """Generate all kinds and sizes; validate every output with the real parser."""
    counts = dict(DEFAULT_COUNTS if counts is None else counts)
    if not counts or any(not name or count < 24 for name, count in counts.items()):
        raise ValueError("counts must map scale names to at least 24 requests")
    if not kinds or len(set(kinds)) != len(kinds) or any(kind not in ALL_KINDS for kind in kinds):
        raise ValueError(f"kinds must be distinct names from {ALL_KINDS}")
    output_dir.mkdir(parents=True, exist_ok=True)
    result = []
    for kind in kinds:
        for scale, count in counts.items():
            # Every sequential trace has at least 60 possible fresh URLs and
            # enough unused URLs for all requests, even at the largest scale.
            catalog = _catalog(sequential_pool_size=max(60, count) if kind == "sequential" else 0)
            stem = f"{kind}_{scale}"
            resources_path = output_dir / f"{stem}_resources.csv"
            requests_path = output_dir / f"{stem}_requests.csv"
            metadata_path = output_dir / f"{stem}_metadata.json"
            # Independent stream per condition, unaffected by other scale order.
            condition_seed = seed + ALL_KINDS.index(kind) * 1_000_003 + sum(ord(c) for c in scale)
            rows = _trace(kind, count, random.Random(condition_seed), catalog)
            _write_csv(resources_path, RESOURCE_FIELDS, catalog)
            _write_csv(requests_path, REQUEST_FIELDS, rows)
            parsed = load_inputs(resources_path, requests_path)
            if len(parsed.requests) != count or len(parsed.resources) != len(catalog):
                raise RuntimeError(f"generated input count mismatch for {stem}")
            active_paths = {row["path"] for row in rows}
            active = [row for row in catalog if row["path"] in active_paths]
            metadata = {
                "kind": kind, "scale": scale, "seed": seed,
                "condition_seed": condition_seed, "request_count": count,
                "client_count": len({row["client_id"] for row in rows}),
                "resource_count": len(catalog),
                "active_resource_count": len(active),
                "active_resource_bytes": sum(int(row["size_bytes"]) for row in active),
                "active_fitting_resource_bytes_at_1_MiB": sum(
                    int(row["size_bytes"]) for row in active
                    if int(row["size_bytes"]) <= 1024 * 1024
                ),
                "resource_sizes_bytes": [int(row["size_bytes"]) for row in catalog],
                "sequential_repeat_probability": (
                    SEQUENTIAL_REPEAT_PROBABILITY if kind == "sequential" else None
                ),
                "mixed_oversized_interval": (
                    MIXED_OVERSIZED_INTERVAL if kind == "mixed" else None
                ),
                "resources_file": resources_path.name,
                "requests_file": requests_path.name,
                "generator_command": (
                    "python -m cache_simulator.workloads --output-dir "
                    f"{output_dir} --seed {seed}"
                    + (" --include-loop" if "loop" in kinds else "")
                ),
                "reference_files_modified": False,
            }
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result.append(Workload(kind, scale, seed, count, resources_path, requests_path, metadata_path))
    return tuple(result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/generated"))
    parser.add_argument("--seed", type=int, default=20261111)
    parser.add_argument("--include-loop", action="store_true", help="Also generate the optional 12-object loop trace")
    args = parser.parse_args()
    workloads = generate_suite(
        args.output_dir, seed=args.seed,
        kinds=ALL_KINDS if args.include_loop else KINDS,
    )
    print(f"Generated and parser-validated {len(workloads)} workloads in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
