"""Audit the committed experiment manifests and aggregate table grids.

This checks provenance metadata and coverage. It cannot recompute metrics from
uncommitted per-run CSVs or verify hashes of inputs absent from the archive.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
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
