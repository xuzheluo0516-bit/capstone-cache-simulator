"""Experiments on the three course-provided traces (sequential, repetitive, mixed).

The course supplies requests_sequential.csv, requests_repetitive.csv and
requests_mixed.csv (3000 requests each) plus one shared resources.csv. This script
characterises the three traces and runs FIFO, LRU, LFU, GDSF and RW-CSF (CUSTOM) on
each of them at six cache capacities. The traces are fixed files, so every run is
deterministic: there are no seeds and no standard deviations.

H is NOT tuned here. It stays at the value chosen on the synthetic tuning traces
(H = 20); see COURSE_PREREGISTRATION.md. Passing another --half-life marks the run
as exploratory in the manifest.

Outputs (in --output-dir):
  workload_summary.csv      the seven characterisation numbers per workload
  workload_top5.csv         the five most requested resources per workload
  workload_distribution.csv requests per resource per workload
  course_runs.csv           every (workload, capacity, policy) run, all metrics
  course_clients.csv        per-client hit rate and mean response time
  course_fairness.csv       Jain index and worst client per (workload, capacity, policy)
  course_h_sensitivity.csv  EXPLORATORY: RW-CSF at several H (never used to choose H)
  manifest.json             parameters, input hashes, source hashes, run counts
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # d_experiments/ (common, analyze_fairness)

from analyze_fairness import jain  # noqa: E402
from common import (  # noqa: E402
    build_registry, core_source_sha256, dependency_versions, experiment_source_sha256,
    validate_half_life, write_csv, write_manifest,
)

from cache_simulator.engine import SharedCacheEngine  # noqa: E402
from cache_simulator.input_parser import load_inputs  # noqa: E402
from cache_simulator.metrics import MetricsAccumulator  # noqa: E402
from cache_simulator.rwcsf import RWCSFPolicy  # noqa: E402

REPO = HERE.parent.parent
WORKLOADS = ("sequential", "repetitive", "mixed")
POLICIES = ("FIFO", "LRU", "LFU", "GDSF", "CUSTOM")
KIB = 1024
CAPACITIES_KIB = (100, 500, 1024, 2048, 5120, 10240)  # 5120 KiB = 5 MiB, the standard one
STANDARD_KIB = 5120
PREREGISTERED_HALF_LIFE = 20.0
HIT_LATENCY_MS = 5.0

RUN_FIELDS = (
    "workload", "capacity_KiB", "policy", "requests", "hits", "misses",
    "request_hit_rate", "byte_hit_rate", "average_response_ms", "origin_bytes",
    "evictions", "oversized_requests", "avg_cache_utilization",
)
CLIENT_FIELDS = (
    "workload", "capacity_KiB", "policy", "client_id", "requests", "hits",
    "request_hit_rate", "average_response_ms",
)
FAIRNESS_FIELDS = (
    "workload", "capacity_KiB", "policy", "jain", "worst_client_id", "worst_client_ms",
)
H_SENSITIVITY_VALUES = (5.0, 20.0, 100.0, 500.0, float("inf"))
H_FIELDS = ("workload", "capacity_KiB", "half_life", "average_response_ms", "request_hit_rate")
SUMMARY_FIELDS = (
    "workload", "total_requests", "distinct_resources", "distinct_clients",
    "total_requested_bytes",
) + tuple(f"requests_larger_than_{kib}KiB" for kib in CAPACITIES_KIB)
TOP5_FIELDS = ("workload", "rank", "resource", "requests", "share", "size_bytes")
DIST_FIELDS = ("workload", "resource", "requests", "size_bytes")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def course_source_sha256() -> str:
    digest = hashlib.sha256()
    for path in sorted(HERE.glob("*.py")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def resource_name(key) -> str:
    return f"{key.host}{key.path}"


def characterize(workload: str, simulation) -> tuple[dict, list[dict], list[dict]]:
    """The seven numbers the course asks for, the top five and the full distribution."""
    sizes = {key: res.size_bytes for key, res in simulation.resources.items()}
    counts = Counter(req.key for req in simulation.requests)
    total = len(simulation.requests)
    summary = {
        "workload": workload,
        "total_requests": total,
        "distinct_resources": len(counts),
        "distinct_clients": len({req.client_id for req in simulation.requests}),
        "total_requested_bytes": sum(sizes[req.key] for req in simulation.requests),
    }
    for kib in CAPACITIES_KIB:
        summary[f"requests_larger_than_{kib}KiB"] = sum(
            n for key, n in counts.items() if sizes[key] > kib * KIB)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], resource_name(kv[0])))
    top5 = [{"workload": workload, "rank": i + 1, "resource": resource_name(key),
             "requests": n, "share": n / total, "size_bytes": sizes[key]}
            for i, (key, n) in enumerate(ordered[:5])]
    dist = [{"workload": workload, "resource": resource_name(key), "requests": n,
             "size_bytes": sizes[key]} for key, n in ordered]
    return summary, top5, dist


def run_one(simulation, name: str, capacity_bytes: int, half_life: float) -> tuple[dict, list[dict]]:
    registry, parameters = build_registry(half_life)
    policy = registry[name](**parameters.get(name, {})) if name in parameters else registry[name]()
    engine = SharedCacheEngine(simulation.resources, policy, capacity_bytes=capacity_bytes,
                               hit_latency_ms=HIT_LATENCY_MS)
    events = engine.process_all(simulation.requests)
    metrics = MetricsAccumulator(simulation.resources, capacity_bytes=capacity_bytes)
    metrics.consume_all(events)
    summary = metrics.summary
    evictions = sum(len(event.evicted) for event in events)
    oversized = sum(1 for event in events
                    if simulation.resources[event.request.key].size_bytes > capacity_bytes)
    utilization = sum(event.cache_used_bytes for event in events) / (
        len(events) * capacity_bytes)
    row = {
        "requests": summary.requests, "hits": summary.hits, "misses": summary.misses,
        "request_hit_rate": summary.request_hit_rate, "byte_hit_rate": summary.byte_hit_rate,
        "average_response_ms": summary.average_response_ms, "origin_bytes": summary.origin_bytes,
        "evictions": evictions, "oversized_requests": oversized,
        "avg_cache_utilization": utilization,
    }
    clients = [{"client_id": c.client_id, "requests": c.requests, "hits": c.hits,
                "request_hit_rate": c.request_hit_rate,
                "average_response_ms": c.average_response_ms} for c in summary.per_client]
    return row, clients


def h_sensitivity_rows(workload: str, simulation) -> list[dict]:
    """Exploratory only: how RW-CSF changes with H on these traces. Not used to pick H."""
    rows = []
    for kib in CAPACITIES_KIB:
        for half_life in H_SENSITIVITY_VALUES:
            engine = SharedCacheEngine(simulation.resources, RWCSFPolicy(half_life=half_life),
                                       capacity_bytes=kib * KIB, hit_latency_ms=HIT_LATENCY_MS)
            metrics = MetricsAccumulator(simulation.resources, capacity_bytes=kib * KIB)
            metrics.consume_all(engine.process_all(simulation.requests))
            summary = metrics.summary
            rows.append({"workload": workload, "capacity_KiB": kib,
                         "half_life": "inf" if half_life == float("inf") else f"{half_life:g}",
                         "average_response_ms": summary.average_response_ms,
                         "request_hit_rate": summary.request_hit_rate})
    return rows


def fairness_rows(client_rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in client_rows:
        groups[(row["workload"], row["capacity_KiB"], row["policy"])].append(row)
    out = []
    for (workload, capacity, policy), members in groups.items():
        worst = max(members, key=lambda r: (float(r["average_response_ms"]), r["client_id"]))
        out.append({
            "workload": workload, "capacity_KiB": capacity, "policy": policy,
            "jain": jain([float(m["request_hit_rate"]) for m in members]),
            "worst_client_id": worst["client_id"],
            "worst_client_ms": float(worst["average_response_ms"]),
        })
    return out


def run_all(resources: Path, requests_dir: Path, output_dir: Path, half_life: float) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries, top5s, dists, runs, client_rows, h_rows = [], [], [], [], [], []
    inputs = {"resources.csv": sha256(resources)}
    for workload in WORKLOADS:
        request_file = requests_dir / f"requests_{workload}.csv"
        inputs[request_file.name] = sha256(request_file)
        simulation = load_inputs(resources, request_file)
        summary, top5, dist = characterize(workload, simulation)
        summaries.append(summary)
        top5s += top5
        dists += dist
        h_rows += h_sensitivity_rows(workload, simulation)
        for kib in CAPACITIES_KIB:
            for policy in POLICIES:
                row, clients = run_one(simulation, policy, kib * KIB, half_life)
                runs.append({"workload": workload, "capacity_KiB": kib, "policy": policy, **row})
                client_rows += [{"workload": workload, "capacity_KiB": kib, "policy": policy, **c}
                                for c in clients]
    write_csv(output_dir / "workload_summary.csv", SUMMARY_FIELDS, summaries)
    write_csv(output_dir / "workload_top5.csv", TOP5_FIELDS, top5s)
    write_csv(output_dir / "workload_distribution.csv", DIST_FIELDS, dists)
    write_csv(output_dir / "course_runs.csv", RUN_FIELDS, runs)
    write_csv(output_dir / "course_clients.csv", CLIENT_FIELDS, client_rows)
    write_csv(output_dir / "course_fairness.csv", FAIRNESS_FIELDS, fairness_rows(client_rows))
    write_csv(output_dir / "course_h_sensitivity.csv", H_FIELDS, h_rows)
    manifest = {
        "experiment": "course-provided traces",
        "preregistration": "d_experiments/course/COURSE_PREREGISTRATION.md",
        "exploratory": half_life != PREREGISTERED_HALF_LIFE,
        "half_life": half_life, "policies": list(POLICIES), "workloads": list(WORKLOADS),
        "capacities_KiB": list(CAPACITIES_KIB), "standard_capacity_KiB": STANDARD_KIB,
        "hit_latency_ms": HIT_LATENCY_MS, "deterministic": True,
        "h_sensitivity": "exploratory; values 5, 20, 100, 500, inf; not used to choose H",
        "input_sha256": inputs,
        "planned_runs": len(WORKLOADS) * len(CAPACITIES_KIB) * len(POLICIES),
        "completed_runs": len(runs), "failed_runs": 0, "status": "complete",
        "source_sha256": core_source_sha256(),
        "course_source_sha256": course_source_sha256(),
        "dependency_versions": dependency_versions(),
        "command": "python d_experiments/course/run_course.py --output-dir <output-dir>",
    }
    write_manifest(output_dir / "manifest.json", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--resources", type=Path, default=REPO / "data/reference/resources.csv")
    parser.add_argument("--requests-dir", type=Path, default=REPO / "data/reference")
    parser.add_argument("--output-dir", type=Path, default=REPO / "data/experiments/course")
    parser.add_argument("--half-life", type=float, default=PREREGISTERED_HALF_LIFE,
                        help="fixed at 20 (chosen on the synthetic tuning traces); another "
                             "value is recorded as exploratory")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_half_life(parser, args.half_life)
    protected = (REPO / "data/results").resolve()
    out = args.output_dir.resolve()
    if args.half_life != PREREGISTERED_HALF_LIFE and (out == protected or protected in out.parents):
        parser.error("an exploratory H must not be written under data/results/")
    manifest = run_all(args.resources, args.requests_dir, args.output_dir, args.half_life)
    print(f"H={args.half_life}  runs={manifest['completed_runs']}  -> {args.output_dir}")
    standard = [r for r in csv.DictReader((args.output_dir / "course_runs.csv").open(newline=""))
                if int(r["capacity_KiB"]) == STANDARD_KIB]
    print(f"average response time (ms) at {STANDARD_KIB} KiB = 5 MiB")
    for workload in WORKLOADS:
        cells = {r["policy"]: float(r["average_response_ms"])
                 for r in standard if r["workload"] == workload}
        print(f"  {workload:<11}" + " ".join(f"{p}={cells[p]:7.2f}" for p in POLICIES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
