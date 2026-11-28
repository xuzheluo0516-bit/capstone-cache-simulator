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


def course_catalog(repo: Path) -> dict[str, int]:
    return {
        f"{r['host']}{r['path']}": int(r["size_bytes"])
        for r in rows(repo / "data" / "reference" / "resources.csv")
    }


def course_policy_catalog(repo: Path) -> dict[str, tuple[int, float]]:
    return {
        f"{r['host']}{r['path']}": (int(r["size_bytes"]), float(r["origin_latency_ms"]))
        for r in rows(repo / "data" / "reference" / "resources.csv")
    }


def audit_course_distribution(course: Path, repo: Path) -> int:
    """Audit workload_distribution.csv against resources and request traces."""
    catalog = course_catalog(repo)
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


def audit_course_workload_summary(course: Path, repo: Path) -> int:
    """Cross-check workload_summary.csv against request traces and resource sizes."""
    catalog = course_catalog(repo)
    summary = rows(course / "workload_summary.csv")
    require(len(summary) == len(COURSE_WORKLOADS), f"{course / 'workload_summary.csv'}: expected 3 rows")
    require(len({r["workload"] for r in summary}) == len(COURSE_WORKLOADS),
            f"{course / 'workload_summary.csv'}: duplicate-workload rows")
    for row in summary:
        workload = row["workload"]
        require(workload in COURSE_WORKLOADS, f"{course / 'workload_summary.csv'}: unknown workload {workload}")
        trace = rows(repo / "data" / "reference" / f"requests_{workload}.csv")
        require(len(trace) == 3000, f"{workload}: expected 3000 requests")
        counts: dict[str, int] = {}
        clients = set()
        requested_bytes = 0
        for request in trace:
            resource = f"{request['host']}{request['path']}"
            counts[resource] = counts.get(resource, 0) + 1
            clients.add(request["client_id"])
            requested_bytes += catalog[resource]
        require(int(row["total_requests"]) == len(trace), f"workload_summary: total_requests differs for {workload}")
        require(int(row["distinct_resources"]) == len(counts),
                f"workload_summary: distinct_resources differs for {workload}")
        require(int(row["distinct_clients"]) == len(clients),
                f"workload_summary: distinct_clients differs for {workload}")
        require(int(row["total_requested_bytes"]) == requested_bytes,
                f"workload_summary: total_requested_bytes differs for {workload}")
        for kib in COURSE_CAPACITIES_KIB:
            field = f"requests_larger_than_{kib}KiB"
            expected = sum(n for resource, n in counts.items() if catalog[resource] > kib * 1024)
            require(int(row[field]) == expected, f"workload_summary: {field} differs for {workload}")
    return len(summary)


def audit_course_top5(course: Path, repo: Path) -> int:
    """Independently derive the top five rows from the audited distribution, not from top5 itself."""
    catalog = course_catalog(repo)
    distribution = rows(course / "workload_distribution.csv")
    top5_rows = rows(course / "workload_top5.csv")
    require(len(top5_rows) == 15, f"{course / 'workload_top5.csv'}: expected 15 rows")
    top5 = {(r["workload"], r["rank"]): r for r in top5_rows}
    require(len(top5) == 15, f"{course / 'workload_top5.csv'}: duplicate rows")
    for workload in COURSE_WORKLOADS:
        members = [r for r in distribution if r["workload"] == workload]
        total = sum(int(r["requests"]) for r in members)
        require(total == 3000, f"workload_top5: distribution total differs for {workload}")
        ordered = sorted(members, key=lambda r: (-int(r["requests"]), r["resource"]))[:5]
        require(len(ordered) == 5, f"workload_top5: fewer than five resources for {workload}")
        for rank, expected in enumerate(ordered, start=1):
            actual = top5.get((workload, str(rank)))
            require(actual is not None, f"workload_top5: missing rank {rank} for {workload}")
            require(actual["resource"] == expected["resource"],
                    f"workload_top5: resource differs for {workload}/rank {rank}")
            require(int(actual["requests"]) == int(expected["requests"]),
                    f"workload_top5: requests differs for {workload}/rank {rank}")
            require(math.isclose(float(actual["share"]), int(expected["requests"]) / total,
                                 rel_tol=0, abs_tol=1e-9),
                    f"workload_top5: share differs for {workload}/rank {rank}")
            require(int(actual["size_bytes"]) == catalog[expected["resource"]],
                    f"workload_top5: size_bytes differs for {workload}/rank {rank}")
    return len(top5_rows)


def reference_custom_metrics(catalog: dict[str, tuple[int, float]], requests: list[dict[str, str]],
                             capacity: int, half_life: float) -> tuple[float, float]:
    """Independent RW-CSF arithmetic for the exploratory H table."""
    cache: dict[str, list] = {}  # resource -> [last_step, access_steps]
    used = hits = 0
    total_ms = 0.0
    for step, request in enumerate(requests):
        resource = f"{request['host']}{request['path']}"
        size, latency = catalog[resource]
        if size > capacity:
            total_ms += latency
            continue
        if resource in cache:
            hits += 1
            total_ms += 5.0
            cache[resource][0] = step
            cache[resource][1].append(step)
            continue
        total_ms += latency
        while used + size > capacity:
            def priority(key: str) -> float:
                history = cache[key][1]
                if math.isinf(half_life):
                    decayed = len(history)
                else:
                    decayed = sum(2.0 ** (-(step - n_j) / half_life) for n_j in history)
                victim_size, victim_latency = catalog[key]
                return decayed * max(victim_latency - 5.0, 0.0) / victim_size
            victim = min(cache, key=lambda key: (priority(key), cache[key][0], key))
            used -= catalog[victim][0]
            del cache[victim]
        cache[resource] = [step, [step]]
        used += size
    n = len(requests)
    return total_ms / n, hits / n


def audit_course_h_sensitivity(course: Path, repo: Path) -> int:
    """Recompute every exploratory RW-CSF H row from the raw traces."""
    catalog = course_policy_catalog(repo)
    h_rows = rows(course / "course_h_sensitivity.csv")
    expected = {(w, str(c), h) for w in COURSE_WORKLOADS for c in COURSE_CAPACITIES_KIB for h in COURSE_H_VALUES}
    actual = [(r["workload"], r["capacity_KiB"], r["half_life"]) for r in h_rows]
    require(len(actual) == len(set(actual)), f"{course / 'course_h_sensitivity.csv'}: duplicate rows")
    require(len(actual) == 90, f"{course / 'course_h_sensitivity.csv'}: expected 90 rows")
    require(set(actual) == expected, f"{course / 'course_h_sensitivity.csv'}: grid differs")
    by_workload: dict[str, list[dict[str, str]]] = {}
    for workload in COURSE_WORKLOADS:
        by_workload[workload] = rows(repo / "data" / "reference" / f"requests_{workload}.csv")
        require(len(by_workload[workload]) == 3000, f"{workload}: expected 3000 requests")
    for row in h_rows:
        half_life = float("inf") if row["half_life"] == "inf" else float(row["half_life"])
        average, hit_rate = reference_custom_metrics(
            catalog, by_workload[row["workload"]], int(row["capacity_KiB"]) * 1024, half_life
        )
        require(math.isclose(float(row["average_response_ms"]), average, rel_tol=0, abs_tol=1e-9),
                f"course_h_sensitivity: average_response_ms differs for {row['workload']}/"
                f"{row['capacity_KiB']}/H={row['half_life']}")
        require(math.isclose(float(row["request_hit_rate"]), hit_rate, rel_tol=0, abs_tol=1e-9),
                f"course_h_sensitivity: request_hit_rate differs for {row['workload']}/"
                f"{row['capacity_KiB']}/H={row['half_life']}")
    return len(h_rows)


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
    out["course_h_sensitivity"] = audit_course_h_sensitivity(course, repo)
    out["course_workload_summary"] = audit_course_workload_summary(course, repo)
    out["course_workload_distribution"] = audit_course_distribution(course, repo)
    out["course_top5"] = audit_course_top5(course, repo)

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
