"""Audit the committed experiment manifests and aggregate table grids.

This checks provenance metadata and coverage. It cannot recompute metrics from
uncommitted per-run CSVs or verify hashes of inputs absent from the archive.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

SEEDS = tuple(range(20261111, 20261116))
WORKLOADS = ("repeated", "sequential", "mixed")
CAPACITIES = (32768, 131072, 262144, 524288, 1048576)
MAIN_POLICIES = ("FIFO", "LRU", "LFU", "GDSF", "CUSTOM")
ABLATION_POLICIES = ("CUSTOM", "ABL_NO_LATENCY", "ABL_NO_SIZE", "ABL_NO_DECAY")
HASH = re.compile(r"[0-9a-f]{64}\Z")


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"non-finite JSON value: {x}")))


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def source_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(directory.glob("*.py"))
    require(bool(files), f"{directory}: no Python source files")
    for path in files:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def audit_run_manifest(path: Path, seed: int, policies: tuple[str, ...]) -> int:
    d = read_json(path)
    expected = {(w, "large", c, p) for w in WORKLOADS for c in CAPACITIES for p in policies}
    require(d.get("seed") == seed, f"{path}: wrong seed")
    require(tuple(d.get("policies", ())) == policies, f"{path}: policy list differs")
    require(tuple(d.get("capacities_bytes", ())) == CAPACITIES, f"{path}: capacities differ")
    require(d.get("hit_latency_ms") == 5 and d.get("initial_state") == "empty; all requests counted; no warmup", f"{path}: assumptions differ")
    require(d.get("status") == "complete", f"{path}: incomplete status")
    runs = d.get("runs", [])
    require(d.get("planned_runs") == len(expected) == d.get("completed_runs") == len(runs), f"{path}: run count mismatch")
    require(d.get("policy_parameters", {}).get("CUSTOM", {}).get("half_life") == 20, f"{path}: CUSTOM H differs")
    for field in ("source_sha256", "experiment_source_sha256"):
        require(bool(HASH.fullmatch(str(d.get(field, "")))), f"{path}: invalid {field}")
    require(bool(d.get("code_version")) and bool(d.get("dependency_versions")), f"{path}: missing code/dependency version")
    seen = set()
    input_hashes = {}
    for r in runs:
        key = (r.get("workload"), r.get("scale"), r.get("capacity_bytes"), r.get("policy"))
        require(key not in seen, f"{path}: duplicate run {key}")
        seen.add(key)
        require(r.get("status") == "complete", f"{path}: failed run {key}")
        for field in ("resources_file", "requests_file", "metadata_file", "events_file"):
            require(bool(r.get(field)), f"{path}: missing {field} in {key}")
        pair = (r.get("resources_sha256"), r.get("requests_sha256"))
        require(all(isinstance(x, str) and HASH.fullmatch(x) for x in pair), f"{path}: invalid input hash in {key}")
        workload = r.get("workload")
        require(workload not in input_hashes or input_hashes[workload] == pair, f"{path}: strategies did not share inputs for {workload}")
        input_hashes[workload] = pair
    require(seen == expected, f"{path}: missing or extra condition(s): {len(expected - seen)} missing, {len(seen - expected)} extra")
    return len(runs)


def audit_grid(path: Path, expected: set[tuple], fields: tuple[str, ...]) -> int:
    actual = [tuple(r[f] for f in fields) for r in rows(path)]
    require(len(actual) == len(set(actual)), f"{path}: duplicate rows")
    require(set(actual) == expected, f"{path}: table grid differs; {len(expected - set(actual))} missing, {len(set(actual) - expected)} extra")
    return len(actual)


COURSE_WORKLOADS = ("sequential", "repetitive", "mixed")
COURSE_POLICIES = ("FIFO", "LRU", "LFU", "GDSF", "CUSTOM")
COURSE_CAPACITIES_KIB = (100, 500, 1024, 2048, 5120, 10240)
COURSE_H_VALUES = ("5", "20", "100", "500", "inf")
COURSE_CLIENTS = tuple(f"student-0{i}" for i in range(1, 7))


def audit_course_distribution(course: Path, repo: Path) -> int:
    """Audit workload_distribution.csv against resources and request traces."""
    catalog = {
        f"{r['host']}{r['path']}": int(r["size_bytes"])
        for r in rows(repo / "data" / "reference" / "resources.csv")
    }
    expected = {(w, resource) for w in COURSE_WORKLOADS for resource in catalog}
    distribution = rows(course / "workload_distribution.csv")
    actual = [(r["workload"], r["resource"]) for r in distribution]
    require(len(actual) == len(set(actual)), f"{course / 'workload_distribution.csv'}: duplicate rows")
    require(len(actual) == 63, f"{course / 'workload_distribution.csv'}: expected 63 rows")
    require(set(actual) == expected, f"{course / 'workload_distribution.csv'}: grid differs")

    request_counts: dict[tuple[str, str], int] = {}
    for workload in COURSE_WORKLOADS:
        trace = rows(repo / "data" / "reference" / f"requests_{workload}.csv")
        require(len(trace) == 3000, f"{workload}: expected 3000 requests")
        for request in trace:
            key = (workload, f"{request['host']}{request['path']}")
            request_counts[key] = request_counts.get(key, 0) + 1

    for row in distribution:
        key = (row["workload"], row["resource"])
        require(row["resource"] in catalog, f"unknown resource: {row['resource']}")
        require(int(row["size_bytes"]) == catalog[row["resource"]], f"size differs: {key}")
        require(int(row["requests"]) == request_counts.get(key, 0), f"request count differs: {key}")
    for workload in COURSE_WORKLOADS:
        require(sum(int(r["requests"]) for r in distribution if r["workload"] == workload) == 3000,
                f"{workload}: distribution request total differs")
    return len(distribution)


def audit_course(root: Path, repo: Path, experiment_hash: str, core_hash: str) -> dict[str, int]:
    """Audit data/results/course: manifest, input hashes, source hashes and table grids."""
    course = root / "course"
    d = read_json(course / "manifest.json")
    require(d.get("status") == "complete" and d.get("exploratory") is False, "course manifest: not a complete formal run")
    require(d.get("planned_runs") == d.get("completed_runs") == 90 and d.get("failed_runs") == 0, "course manifest: run count differs")
    require(tuple(d.get("workloads", ())) == COURSE_WORKLOADS and tuple(d.get("policies", ())) == COURSE_POLICIES, "course manifest: workloads or policies differ")
    require(tuple(d.get("capacities_KiB", ())) == COURSE_CAPACITIES_KIB and d.get("standard_capacity_KiB") == 5120, "course manifest: capacities differ")
    require(d.get("half_life") == 20.0 and d.get("hit_latency_ms") == 5.0, "course manifest: H or hit latency differs")
    for field in ("source_sha256", "experiment_source_sha256", "course_source_sha256"):
        require(bool(HASH.fullmatch(str(d.get(field, "")))), f"course manifest: invalid {field}")
    require(d["source_sha256"] == core_hash, "course manifest: core source hash differs from the audited tree")
    require(d["experiment_source_sha256"] == experiment_hash, "course manifest: experiment source hash differs from the audited tree")
    require(d["course_source_sha256"] == source_hash(repo / "d_experiments" / "course"), "course manifest: course script hash differs")
    for name, recorded in d.get("input_sha256", {}).items():
        actual = hashlib.sha256((repo / "data" / "reference" / name).read_bytes()).hexdigest()
        require(actual == recorded, f"course manifest: input {name} differs from the committed file")
    require(set(d.get("input_sha256", {})) == {"resources.csv", *(f"requests_{w}.csv" for w in COURSE_WORKLOADS)}, "course manifest: input list differs")
    caps = {str(c) for c in COURSE_CAPACITIES_KIB}
    out = {}
    out["course_runs"] = audit_grid(course / "course_runs.csv", {(w, c, p) for w in COURSE_WORKLOADS for c in caps for p in COURSE_POLICIES}, ("workload", "capacity_KiB", "policy"))
    out["course_clients"] = audit_grid(course / "course_clients.csv", {(w, c, p, k) for w in COURSE_WORKLOADS for c in caps for p in COURSE_POLICIES for k in COURSE_CLIENTS}, ("workload", "capacity_KiB", "policy", "client_id"))
    out["course_fairness"] = audit_grid(course / "course_fairness.csv", {(w, c, p) for w in COURSE_WORKLOADS for c in caps for p in COURSE_POLICIES}, ("workload", "capacity_KiB", "policy"))
    out["course_h_sensitivity"] = audit_grid(course / "course_h_sensitivity.csv", {(w, c, h) for w in COURSE_WORKLOADS for c in caps for h in COURSE_H_VALUES}, ("workload", "capacity_KiB", "half_life"))
    out["course_workload_summary"] = audit_grid(course / "workload_summary.csv", {(w,) for w in COURSE_WORKLOADS}, ("workload",))
    out["course_top5"] = audit_grid(course / "workload_top5.csv", {(w, str(k)) for w in COURSE_WORKLOADS for k in range(1, 6)}, ("workload", "rank"))
    out["course_workload_distribution"] = audit_course_distribution(course, repo)

    client_groups: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for client in rows(course / "course_clients.csv"):
        key = (client["workload"], client["capacity_KiB"], client["policy"])
        client_groups.setdefault(key, []).append(client)
    for r in rows(course / "course_runs.csv"):
        key = (r["workload"], r["capacity_KiB"], r["policy"])
        members = client_groups.get(key, [])
        require(len(members) == len(COURSE_CLIENTS), f"course_runs: client count differs for {key}")
        total_requests = sum(int(c["requests"]) for c in members)
        total_hits = sum(int(c["hits"]) for c in members)
        require(int(r["requests"]) == total_requests, f"course_runs: client requests differ for {key}")
        require(int(r["hits"]) == total_hits, f"course_runs: client hits differ for {key}")
        require(int(r["hits"]) + int(r["misses"]) == int(r["requests"]) == 3000, f"course_runs: hits + misses != 3000 for {key}")
        weighted_ms = sum(int(c["requests"]) * float(c["average_response_ms"]) for c in members) / total_requests
        require(math.isclose(float(r["average_response_ms"]), weighted_ms, rel_tol=0, abs_tol=1e-9),
                f"course_runs: average_response_ms differs for {key}")
        require(math.isclose(float(r["request_hit_rate"]), total_hits / total_requests, rel_tol=0, abs_tol=1e-9),
                f"course_runs: request_hit_rate differs for {key}")

    for f in rows(course / "course_fairness.csv"):
        key = (f["workload"], f["capacity_KiB"], f["policy"])
        members = client_groups.get(key, [])
        require(len(members) == len(COURSE_CLIENTS), f"course_fairness: client count differs for {key}")
        rates = [float(c["request_hit_rate"]) for c in members]
        squares = sum(rate * rate for rate in rates)
        require(squares > 0, f"course_fairness: all-zero client hit rates for {key}")
        jain = sum(rates) ** 2 / (len(rates) * squares)
        require(math.isclose(float(f["jain"]), jain, rel_tol=0, abs_tol=1e-9),
                f"course_fairness: Jain differs for {key}")
        worst = max(members, key=lambda c: (float(c["average_response_ms"]), c["client_id"]))
        require(f["worst_client_id"] == worst["client_id"], f"course_fairness: worst client differs for {key}")
        require(math.isclose(float(f["worst_client_ms"]), float(worst["average_response_ms"]), rel_tol=0, abs_tol=1e-9),
                f"course_fairness: worst-client latency differs for {key}")
    return out


def audit(root: Path) -> dict[str, int]:
    out = {}
    versions = set()
    for group, policies in (("main", MAIN_POLICIES), ("ablation", ABLATION_POLICIES)):
        total = 0
        for seed in SEEDS:
            path = root / group / f"seed_{seed}" / "manifest.json"
            total += audit_run_manifest(path, seed, policies)
            d = read_json(path)
            versions.add((d["code_version"], d["source_sha256"], d["experiment_source_sha256"]))
        out[group] = total
    for group, expected_seed, planned in (("h-tuning", 31415, 120), ("drift", None, 150)):
        path = root / group / "manifest.json"
        d = read_json(path)
        require(d.get("status") == "complete" and d.get("planned_runs") == d.get("completed_runs") == planned, f"{path}: incomplete runs")
        if expected_seed is not None:
            require(d.get("seed") == expected_seed and len(d.get("runs", [])) == planned, f"{path}: tuning run/seed mismatch")
            require(all(r.get("status") == "complete" for r in d["runs"]), f"{path}: failed tuning run")
        else:
            require(d.get("failed_runs") == 0 and d.get("seeds") == list(SEEDS), f"{path}: drift failures/seeds differ")
            require(len(d.get("input_sha256", {})) == 2 * len(SEEDS), f"{path}: drift input hashes missing")
        versions.add((d["code_version"], d["source_sha256"], d["experiment_source_sha256"]))
        out[group] = planned
    require(len(versions) == 1, "manifests use different code/source versions")
    _, recorded_core, recorded_experiment = next(iter(versions))
    repo = root.parent.parent
    require(source_hash(repo / "src" / "cache_simulator") == recorded_core, "core source hash differs from manifests")
    require(source_hash(repo / "d_experiments") == recorded_experiment, "experiment source hash differs from manifests")
    out.update(audit_course(root, repo, recorded_experiment, recorded_core))
    choice = read_json(root / "h-tuning" / "h_choice.json")
    require(choice.get("seed") == 31415 and choice.get("chosen_half_life") == 20, "tuning choice differs")
    caps = {str(float(c // 1024)) for c in CAPACITIES}
    main_grid = {(w, c, p) for w in WORKLOADS for c in caps for p in MAIN_POLICIES}
    out["main_table"] = audit_grid(root / "main" / "main_table.csv", main_grid, ("workload", "capacity_KiB", "policy"))
    require(all(r["n_seeds"] == "5" for r in rows(root / "main" / "main_table.csv")), "main table seed count differs")
    out["per_client"] = audit_grid(root / "main" / "per_client.csv", {( "mixed", c, p, client) for c in caps for p in MAIN_POLICIES for client in ("browser", "media", "random")}, ("workload", "capacity_KiB", "policy", "client_id"))
    out["fairness"] = audit_grid(root / "main" / "fairness.csv", {("mixed", c, p) for c in caps for p in MAIN_POLICIES}, ("workload", "capacity_KiB", "policy"))
    variants = ABLATION_POLICIES[1:]
    out["ablation_table"] = audit_grid(root / "ablation" / "ablation_table.csv", {(v,) for v in variants}, ("variant",))
    out["ablation_by_capacity"] = audit_grid(root / "ablation" / "ablation_by_capacity.csv", {(v, w, c) for v in variants for w in WORKLOADS for c in caps}, ("variant", "workload", "capacity_KiB"))
    drift_policies = ("FIFO", "LRU", "LFU", "GDSF", "CUSTOM", "NO_DECAY")
    out["drift_runs"] = audit_grid(root / "drift" / "drift_runs.csv", {(str(s), str(c // 1024), p) for s in SEEDS for c in CAPACITIES for p in drift_policies}, ("seed", "capacity_KiB", "policy"))
    out["drift_table"] = audit_grid(root / "drift" / "drift_table.csv", {(str(c // 1024), p) for c in CAPACITIES for p in drift_policies}, ("capacity_KiB", "policy"))
    out["tuning_summary"] = audit_grid(root / "h-tuning" / "summary.csv", {(w, "large", "31415", str(c), p) for w in WORKLOADS for c in CAPACITIES for p in ("FIFO", "LRU", "LFU", "GDSF", "RWCSF_H5", "RWCSF_H20", "RWCSF_H100", "RWCSF_H500")}, ("workload", "scale", "seed", "capacity_bytes", "policy"))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results-dir", type=Path, default=Path("data/results"))
    args = parser.parse_args()
    try:
        counts = audit(args.results_dir)
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")
    for name, count in counts.items():
        print(f"PASS {name}: {count}")
    print("PASS manifest coverage, shared inputs, provenance fields, and aggregate grids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
