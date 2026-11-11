"""Reproducible batch runner for shared-cache workload comparisons."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from importlib import metadata
from pathlib import Path

from .cli import POLICY_REGISTRY
from .engine import EvictionPolicy, SharedCacheEngine
from .input_parser import load_inputs
from .metrics import MetricsAccumulator
from .output import render_events
from .workloads import CAPACITIES_BYTES, DEFAULT_COUNTS, Workload, generate_suite

DEFAULT_POLICIES = ("FIFO", "LRU", "LFU", "CUSTOM")
SUMMARY_FIELDS = (
    "workload", "scale", "seed", "capacity_bytes", "capacity_KiB", "policy",
    "requests", "hits", "misses", "request_bytes", "hit_bytes",
    "origin_bytes", "request_hit_rate", "byte_hit_rate",
    "average_response_ms", "total_response_ms", "resources_sha256",
    "requests_sha256", "events_file",
)
CLIENT_FIELDS = (
    "workload", "scale", "seed", "capacity_bytes", "policy", "client_id",
    "requests", "hits", "misses", "request_hit_rate", "average_response_ms",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _code_version() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True,
            timeout=5, cwd=Path(__file__).resolve().parents[2],
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def _source_sha256() -> str:
    """Identify the actual Python sources even outside a Git checkout."""
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).resolve().parent.glob("*.py")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _package_version() -> str | None:
    try:
        return metadata.version("capstone-cache-simulator")
    except metadata.PackageNotFoundError:
        return None


def _write_rows(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_manifest(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _check_summary(summary, *, expected_requests: int) -> None:
    if summary.requests != expected_requests or summary.hits + summary.misses != summary.requests:
        raise RuntimeError("global request count invariant failed")
    if summary.hit_bytes + summary.origin_bytes != summary.request_bytes:
        raise RuntimeError("byte accounting invariant failed")
    if sum(c.requests for c in summary.per_client) != summary.requests:
        raise RuntimeError("per-client request count invariant failed")
    if sum(c.hits for c in summary.per_client) != summary.hits:
        raise RuntimeError("per-client hit count invariant failed")


def run_suite(
    output_dir: Path,
    *,
    seed: int = 20261111,
    counts: dict[str, int] | None = None,
    capacities_bytes: Sequence[int] = CAPACITIES_BYTES,
    policies: Sequence[str] = DEFAULT_POLICIES,
    registry: Mapping[str, Callable[..., EvictionPolicy]] | None = None,
    policy_parameters: Mapping[str, Mapping[str, object]] | None = None,
    hit_latency_ms: float = 5.0,
) -> dict:
    """Generate inputs once, then run every requested policy from a fresh state."""
    registry = POLICY_REGISTRY if registry is None else registry
    policy_parameters = {} if policy_parameters is None else dict(policy_parameters)
    counts = dict(DEFAULT_COUNTS if counts is None else counts)
    if not policies or len(set(policies)) != len(policies):
        raise ValueError("policies must be a nonempty unique list")
    missing = [name for name in policies if name not in registry]
    if missing:
        raise ValueError(f"policy not registered: {', '.join(missing)}; available: {', '.join(sorted(registry))}")
    if any(name not in policies for name in policy_parameters):
        raise ValueError("policy_parameters contains a policy not selected for this run")
    if not capacities_bytes or any(type(value) is not int or value < 0 for value in capacities_bytes):
        raise ValueError("capacities_bytes must contain non-negative integers")
    if len(set(capacities_bytes)) != len(capacities_bytes):
        raise ValueError("capacities_bytes must not contain duplicates")
    if not math.isfinite(hit_latency_ms) or hit_latency_ms < 0:
        raise ValueError("hit_latency_ms must be finite and non-negative")

    output_dir.mkdir(parents=True, exist_ok=True)
    workloads = generate_suite(output_dir / "inputs", seed=seed, counts=counts)
    manifest = {
        "schema_version": 1,
        "command": "python -m cache_simulator.experiments",
        "seed": seed, "counts": counts,
        "capacities_bytes": list(capacities_bytes),
        "capacity_unit": "bytes; KiB = 1024 bytes",
        "hit_latency_ms": hit_latency_ms,
        "initial_state": "empty; all requests counted; no warmup",
        "policies": list(policies),
        "policy_parameters": {name: dict(policy_parameters.get(name, {})) for name in policies},
        "code_version": _code_version(),
        "source_sha256": _source_sha256(),
        "dependency_versions": {"python": platform.python_version(), "package": _package_version()},
        "planned_runs": len(workloads) * len(capacities_bytes) * len(policies),
        "runs": [],
    }
    manifest_path = output_dir / "manifest.json"
    _write_manifest(manifest_path, manifest)
    summaries: list[dict] = []
    clients: list[dict] = []
    for workload in workloads:
        simulation = load_inputs(workload.resources_path, workload.requests_path)
        resources_hash = _sha256(workload.resources_path)
        requests_hash = _sha256(workload.requests_path)
        for capacity in capacities_bytes:
            for name in policies:
                stem = f"{workload.kind}_{workload.scale}_{capacity}B_{name}"
                events_path = output_dir / "events" / f"{stem}.csv"
                record = {
                    "workload": workload.kind, "scale": workload.scale,
                    "capacity_bytes": capacity, "policy": name,
                    "resources_file": str(workload.resources_path.relative_to(output_dir)),
                    "requests_file": str(workload.requests_path.relative_to(output_dir)),
                    "metadata_file": str(workload.metadata_path.relative_to(output_dir)),
                    "resources_sha256": resources_hash,
                    "requests_sha256": requests_hash,
                    "events_file": str(events_path.relative_to(output_dir)),
                    "status": "pending",
                }
                manifest["runs"].append(record)
                _write_manifest(manifest_path, manifest)
                try:
                    # New policy, engine, and accumulator for every condition.
                    engine = SharedCacheEngine(
                        simulation.resources, registry[name](**policy_parameters.get(name, {})),
                        capacity_bytes=capacity, hit_latency_ms=hit_latency_ms,
                    )
                    events = engine.process_all(simulation.requests)
                    metrics = MetricsAccumulator(simulation.resources, capacity_bytes=capacity)
                    snapshots = metrics.consume_all(events)
                    summary = metrics.summary
                    _check_summary(summary, expected_requests=workload.count)
                    events_path.parent.mkdir(parents=True, exist_ok=True)
                    events_path.write_text(render_events(events, snapshots), encoding="utf-8")
                    base = {
                        "workload": workload.kind, "scale": workload.scale,
                        "seed": seed, "capacity_bytes": capacity,
                        "capacity_KiB": capacity / 1024, "policy": name,
                    }
                    summaries.append({
                        **base, "requests": summary.requests, "hits": summary.hits,
                        "misses": summary.misses, "request_bytes": summary.request_bytes,
                        "hit_bytes": summary.hit_bytes, "origin_bytes": summary.origin_bytes,
                        "request_hit_rate": summary.request_hit_rate,
                        "byte_hit_rate": summary.byte_hit_rate,
                        "average_response_ms": summary.average_response_ms,
                        "total_response_ms": summary.total_response_ms,
                        "resources_sha256": resources_hash,
                        "requests_sha256": requests_hash,
                        "events_file": record["events_file"],
                    })
                    for client in summary.per_client:
                        clients.append({
                            **{key: base[key] for key in ("workload", "scale", "seed", "capacity_bytes", "policy")},
                            "client_id": client.client_id,
                            "requests": client.requests, "hits": client.hits,
                            "misses": client.misses,
                            "request_hit_rate": client.request_hit_rate,
                            "average_response_ms": client.average_response_ms,
                        })
                    record["status"] = "complete"
                except Exception as exc:
                    record["status"] = "failed"
                    record["error"] = f"{type(exc).__name__}: {exc}"
                    _write_manifest(manifest_path, manifest)
                    raise RuntimeError(f"experiment {stem} failed: {exc}") from exc
                _write_manifest(manifest_path, manifest)
    _write_rows(output_dir / "summary.csv", SUMMARY_FIELDS, summaries)
    _write_rows(output_dir / "clients.csv", CLIENT_FIELDS, clients)
    if len(summaries) != manifest["planned_runs"]:
        raise RuntimeError("summary row count does not match experiment plan")
    manifest["status"] = "complete"
    manifest["completed_runs"] = len(summaries)
    _write_manifest(manifest_path, manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/experiments/latest"))
    parser.add_argument("--seed", type=int, default=20261111)
    parser.add_argument("--capacities-bytes", type=int, nargs="+", default=CAPACITIES_BYTES)
    parser.add_argument("--policies", nargs="+", default=DEFAULT_POLICIES)
    parser.add_argument(
        "--policy-parameters-json", type=Path,
        help="JSON object mapping policy names to constructor keyword arguments",
    )
    parser.add_argument("--hit-latency-ms", type=float, default=5.0)
    args = parser.parse_args(argv)
    try:
        policy_parameters = (
            json.loads(args.policy_parameters_json.read_text(encoding="utf-8"))
            if args.policy_parameters_json else None
        )
        if policy_parameters is not None and (
            not isinstance(policy_parameters, dict)
            or any(not isinstance(value, dict) for value in policy_parameters.values())
        ):
            raise ValueError("policy parameters JSON must map policy names to objects")
        manifest = run_suite(
            args.output_dir, seed=args.seed,
            capacities_bytes=args.capacities_bytes,
            policies=args.policies, policy_parameters=policy_parameters,
            hit_latency_ms=args.hit_latency_ms,
        )
    except (ValueError, RuntimeError, OSError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Completed {manifest['completed_runs']} runs in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
