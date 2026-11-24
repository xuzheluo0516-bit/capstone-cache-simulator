"""Hotspot-drift hypothesis test for RW-CSF's recency decay.

Designed AFTER seeing the main comparison and ablation (those workloads have a
fixed popularity distribution, so decay could not help there). The design and
the predictions were written down before any result existed: see
DRIFT_PREREGISTRATION.md. H is fixed at the value chosen by run_h_tuning.py.

Trace: 1 client, 3 phases x 480 requests, 12 resources in 3 groups of 4 with
identical size/latency per slot. In phase p, 85% of requests go to group p
(uniform over its 4 resources) and 15% go to a uniform draw over all 12.

Outputs (in --output-dir): inputs/seed_<N>_{resources,requests}.csv,
drift_runs.csv (every run), drift_table.csv (mean/std over seeds),
manifest.json (parameters and input hashes), and a printed check of the
pre-registered predictions P1-P3.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import (
    core_source_sha256, dependency_versions, mean, stdev, validate_formal_seeds,
    validate_half_life, write_csv, write_manifest,
)

from cache_simulator.cli import POLICY_REGISTRY
from cache_simulator.engine import SharedCacheEngine
from cache_simulator.gdsf import GDSFPolicy
from cache_simulator.input_parser import REQUEST_FIELDS, RESOURCE_FIELDS, load_inputs
from cache_simulator.metrics import MetricsAccumulator
from cache_simulator.rwcsf import RWCSFPolicy

DEFAULT_SEEDS = (20261111, 20261112, 20261113, 20261114, 20261115)
PHASES = 3
PHASE_LEN = 480
HOT_PROB = 0.85
GROUP_SIZE = 4
SIZES_KIB = (16, 32, 64, 128)       # per slot, identical in every group
LATENCIES_MS = (60, 80, 100, 120)   # per slot, identical in every group
CAPACITIES_KIB = (32, 128, 256, 512, 1024)
POLICIES = ("FIFO", "LRU", "LFU", "GDSF", "CUSTOM", "NO_DECAY")
HIT_LATENCY_MS = 5.0
HOST = "experiment.example.invalid"
START = datetime(2026, 11, 1, tzinfo=timezone.utc)
STREAM_OFFSET = 5_000_011           # keeps the stream apart from other workloads

RUN_FIELDS = (
    "seed", "capacity_KiB", "policy", "average_response_ms",
    "request_hit_rate", "byte_hit_rate", "origin_bytes",
)
TABLE_FIELDS = (
    "capacity_KiB", "policy", "n_seeds",
    "average_response_ms_mean", "average_response_ms_std",
    "request_hit_rate_mean", "byte_hit_rate_mean",
)


def catalog() -> list[dict[str, str]]:
    rows = []
    for group in range(PHASES):
        for slot in range(GROUP_SIZE):
            rows.append({
                "scheme": "https", "host": HOST,
                "path": f"/drift/g{group}/{slot}",
                "status_code": "200", "content_type": "application/octet-stream",
                "size_bytes": str(SIZES_KIB[slot] * 1024),
                "origin_latency_ms": str(LATENCIES_MS[slot]),
                "cache_control": "public, max-age=3600",
            })
    return rows


def make_trace(seed: int, resources: list[dict[str, str]]) -> list[dict[str, str]]:
    rng = random.Random(seed + STREAM_OFFSET)
    rows = []
    for index in range(PHASES * PHASE_LEN):
        phase = index // PHASE_LEN
        if rng.random() < HOT_PROB:
            pick = phase * GROUP_SIZE + rng.randrange(GROUP_SIZE)
        else:
            pick = rng.randrange(len(resources))
        resource = resources[pick]
        rows.append({
            "timestamp": (START + timedelta(seconds=index)).isoformat().replace("+00:00", "Z"),
            "client_id": "drift-reader", "method": "GET",
            "scheme": resource["scheme"], "host": resource["host"],
            "path": resource["path"],
        })
    return rows


def _write(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_policy(name: str, half_life: float):
    if name in ("FIFO", "LRU", "LFU"):
        return POLICY_REGISTRY[name]()
    if name == "GDSF":
        return GDSFPolicy()
    if name == "CUSTOM":
        return RWCSFPolicy(half_life=half_life)
    if name == "NO_DECAY":
        return RWCSFPolicy(half_life=math.inf)
    raise ValueError(f"unknown policy {name}")


def run_cell(simulation, name: str, capacity_bytes: int, half_life: float):
    engine = SharedCacheEngine(
        simulation.resources, make_policy(name, half_life),
        capacity_bytes=capacity_bytes, hit_latency_ms=HIT_LATENCY_MS,
    )
    events = engine.process_all(simulation.requests)
    metrics = MetricsAccumulator(simulation.resources, capacity_bytes=capacity_bytes)
    metrics.consume_all(events)
    return metrics.summary


def run_all(output_dir: Path, seeds, half_life: float) -> list[dict]:
    inputs = output_dir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    resources = catalog()
    rows: list[dict] = []
    hashes: dict[str, str] = {}
    for seed in seeds:
        res_path = inputs / f"seed_{seed}_resources.csv"
        req_path = inputs / f"seed_{seed}_requests.csv"
        _write(res_path, RESOURCE_FIELDS, resources)
        _write(req_path, REQUEST_FIELDS, make_trace(seed, resources))
        hashes[f"seed_{seed}_resources"] = _sha256(res_path)
        hashes[f"seed_{seed}_requests"] = _sha256(req_path)
        simulation = load_inputs(res_path, req_path)
        for kib in CAPACITIES_KIB:
            for name in POLICIES:
                s = run_cell(simulation, name, kib * 1024, half_life)
                rows.append({
                    "seed": seed, "capacity_KiB": kib, "policy": name,
                    "average_response_ms": s.average_response_ms,
                    "request_hit_rate": s.request_hit_rate,
                    "byte_hit_rate": s.byte_hit_rate,
                    "origin_bytes": s.origin_bytes,
                })
    write_csv(output_dir / "drift_runs.csv", RUN_FIELDS, rows)
    manifest = {
        "design": "3 phases x 480 requests, hot group of 4 per phase (85%), "
                  "15% uniform over 12 resources",
        "seeds": list(seeds), "half_life": half_life, "policies": list(POLICIES),
        "policy_parameters": {
            name: ({"half_life": half_life} if name == "CUSTOM" else
                   {"half_life": "inf"} if name == "NO_DECAY" else {})
            for name in POLICIES
        },
        "capacities_KiB": list(CAPACITIES_KIB), "hit_latency_ms": HIT_LATENCY_MS,
        "sizes_KiB_per_slot": list(SIZES_KIB), "latencies_ms_per_slot": list(LATENCIES_MS),
        "input_sha256": hashes,
        "preregistration": "d_experiments/DRIFT_PREREGISTRATION.md",
        "planned_runs": len(seeds) * len(CAPACITIES_KIB) * len(POLICIES),
        "completed_runs": len(rows),
        "failed_runs": 0,
        "status": "complete",
        "source_sha256": core_source_sha256(),
        "dependency_versions": dependency_versions(),
        "command": (
            "python d_experiments/run_drift.py --output-dir <output-dir> "
            f"--half-life {half_life} --seeds " + " ".join(str(seed) for seed in seeds)
        ),
    }
    write_manifest(output_dir / "manifest.json", manifest)
    return rows


def aggregate(rows: list[dict]) -> list[dict]:
    table = []
    for kib in CAPACITIES_KIB:
        for name in POLICIES:
            cell = [r for r in rows if r["capacity_KiB"] == kib and r["policy"] == name]
            ms = [float(r["average_response_ms"]) for r in cell]
            table.append({
                "capacity_KiB": kib, "policy": name, "n_seeds": len(cell),
                "average_response_ms_mean": mean(ms),
                "average_response_ms_std": stdev(ms),
                "request_hit_rate_mean": mean([float(r["request_hit_rate"]) for r in cell]),
                "byte_hit_rate_mean": mean([float(r["byte_hit_rate"]) for r in cell]),
            })
    return table


def _mean_ms(table: list[dict], kib: int, name: str) -> float:
    return [t for t in table if t["capacity_KiB"] == kib and t["policy"] == name][0][
        "average_response_ms_mean"
    ]


def percent_diff(table: list[dict], kib: int, a: str, b: str) -> float:
    """Percent difference of a relative to b (negative = a is faster)."""
    base = _mean_ms(table, kib, b)
    return 100.0 * (_mean_ms(table, kib, a) - base) / base


def check_predictions(table: list[dict]) -> dict[str, dict]:
    """Evaluate P1-P3 exactly as written in DRIFT_PREREGISTRATION.md."""
    p1 = percent_diff(table, 256, "CUSTOM", "LFU")
    p2 = {kib: percent_diff(table, kib, "CUSTOM", "GDSF") for kib in (128, 256, 512)}
    p3 = percent_diff(table, 256, "CUSTOM", "NO_DECAY")
    return {
        "P1": {"value": p1, "holds": p1 <= -5.0,
               "rule": "RW-CSF at least 5% faster than LFU at 256 KiB"},
        "P2": {"value": p2, "holds": all(abs(v) <= 3.0 for v in p2.values()),
               "rule": "RW-CSF within 3% of GDSF at 128, 256 and 512 KiB"},
        "P3": {"value": p3, "holds": p3 <= -3.0,
               "rule": "RW-CSF at least 3% faster than NO_DECAY at 256 KiB"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--half-life", type=float, default=20.0,
                        help="the H chosen by run_h_tuning.py (do not retune)")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS))
    args = parser.parse_args()
    validate_formal_seeds(parser, args.seeds)
    validate_half_life(parser, args.half_life)
    rows = run_all(args.output_dir, args.seeds, args.half_life)
    table = aggregate(rows)
    write_csv(args.output_dir / "drift_table.csv", TABLE_FIELDS, table)
    print(f"H={args.half_life}  seeds={list(args.seeds)}  runs={len(rows)}")
    print("average response time (ms), mean over seeds")
    print("KiB   " + " ".join(f"{p:>9}" for p in POLICIES))
    for kib in CAPACITIES_KIB:
        print(f"{kib:>4}  " + " ".join(
            f"{_mean_ms(table, kib, p):9.3f}" for p in POLICIES))
    print("pre-registered predictions:")
    for key, res in check_predictions(table).items():
        value = res["value"]
        shown = ({k: round(v, 2) for k, v in value.items()}
                 if isinstance(value, dict) else round(value, 2))
        print(f"  {key}: {'HOLDS' if res['holds'] else 'DOES NOT HOLD'}  "
              f"({res['rule']}; measured % diff {shown})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
