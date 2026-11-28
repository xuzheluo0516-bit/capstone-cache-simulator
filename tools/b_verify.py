#!/usr/bin/env python3
"""B3/B4: audit raw formal events without importing simulator metrics or D aggregators."""
import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

SEEDS = tuple(range(20261111, 20261116))
POLICIES = ("FIFO", "LRU", "LFU", "GDSF", "CUSTOM")
CAPS = (32, 128, 256, 512, 1024)
WORKLOADS = ("repeated", "sequential", "mixed")
GRID = {(w, c, p) for w in WORKLOADS for c in CAPS for p in POLICIES}
SIX = {(w, 512, p) for w in WORKLOADS for p in ("CUSTOM", "LRU")}
MIXED = {(w, c, p) for w, c, p in GRID if w == "mixed"}

def require(condition, message):
    if not condition:
        raise ValueError(message)

def read(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))

def key(row):
    return tuple(row[field] for field in ("scheme", "host", "path"))

def cell(row):
    return row["workload"], int(float(row["capacity_KiB"])), row["policy"]

def run_cell(row):
    return row["workload"], int(row["capacity_bytes"]) // 1024, row["policy"]

def indexed(rows, key_func):
    result = {}
    for row in rows:
        k = key_func(row)
        require(k not in result, f"duplicate row: {k}")
        result[k] = row
    return result

def check(actual, expected, label):
    a, b = float(actual), float(expected)
    if math.isnan(a) and math.isnan(b):
        return
    require(math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-8),
            f"{label}: recomputed={a}, published={b}")

def excel_label(index):
    label = ""
    n = index + 1
    while n:
        n, r = divmod(n - 1, 26)
        label = chr(65 + r) + label
    return label

def audit_run(base, run, hit_latency):
    paths = {name: base / run[name + "_file"] for name in ("resources", "requests", "events")}
    for name in ("resources", "requests"):
        require(hashlib.sha256(paths[name].read_bytes()).hexdigest() == run[name + "_sha256"],
                f"input hash mismatch: {paths[name]}")
    resources = indexed(read(paths["resources"]), key)
    requests, events = read(paths["requests"]), read(paths["events"])
    require(len(requests) == len(events) == 1440, "unexpected formal request count")
    labels = {}
    clients = defaultdict(lambda: [0, 0, 0.0])
    hits = hit_bytes = total_bytes = origin = 0
    elapsed = 0.0
    capacity = int(run["capacity_bytes"])
    for step, (r, e) in enumerate(zip(requests, events), 1):
        k = key(r)
        if k not in labels:
            labels[k] = excel_label(len(labels))
        require(int(e["step"]) == step and e["client_id"] == r["client_id"]
                and e["resource_id"] == labels[k], f"event/request mismatch at {step}")
        resource = resources[k]
        size = int(resource["size_bytes"])
        require(e["result"] in ("HIT", "MISS"), "invalid result")
        hit = int(e["result"] == "HIT")
        require(not hit or size <= capacity, "oversized hit")
        t = float(e["response_ms"])
        check(t, hit_latency if hit else resource["origin_latency_ms"], "response_ms")
        hits += hit
        total_bytes += size
        hit_bytes += size * hit
        origin += size * (1 - hit)
        elapsed += t
        require(int(e["cumulative_hits"]) == hits, "cumulative hits")
        require(int(e["cumulative_origin_bytes"]) == origin, "cumulative origin bytes")
        require(0 <= float(e["cache_used_KiB"]) <= capacity / 1024, "capacity violation")
        c = clients[r["client_id"]]
        c[0] += 1
        c[1] += hit
        c[2] += t
    require(hit_bytes + origin == total_bytes, "byte invariant")
    require(sum(v[0] for v in clients.values()) == len(requests), "client request invariant")
    require(sum(v[1] for v in clients.values()) == hits, "client hits invariant")
    metrics = dict(average_response_ms=elapsed / len(requests), request_hit_rate=hits / len(requests),
                   byte_hit_rate=hit_bytes / total_bytes, origin_bytes=origin)
    return metrics, {name: (v[1] / v[0], v[2] / v[0]) for name, v in clients.items()}

def audit(generated, official):
    main = indexed(read(official / "main_table.csv"), cell)
    fair = indexed(read(official / "fairness.csv"), cell)
    pc = indexed(read(official / "per_client.csv"), lambda r: (*cell(r), r["client_id"]))
    require(set(main) == GRID, "official main grid mismatch")
    require(set(fair) == MIXED, "official fairness grid mismatch")
    results, client, fairness = defaultdict(list), defaultdict(list), defaultdict(list)
    for seed in SEEDS:
        base = generated / f"seed_{seed}"
        m = json.loads((base / "manifest.json").read_text())
        original = json.loads((official / f"seed_{seed}" / "manifest.json").read_text())
        for manifest in (m, original):
            require(manifest["seed"] == seed, "seed mismatch")
            require(manifest["planned_runs"] == manifest["completed_runs"] == 75, "run count")
            require(manifest["policy_parameters"]["CUSTOM"]["half_life"] == 20, "half-life mismatch")
            check(manifest["hit_latency_ms"], 5, "hit latency")
        originals = indexed(original["runs"], run_cell)
        runs = indexed(m["runs"], run_cell)
        require(set(runs) == set(originals) == GRID, "formal run grid mismatch")
        for k, r in runs.items():
            require(r["status"] == originals[k]["status"] == "complete", "incomplete run")
            require(r["scale"] == originals[k]["scale"] == "large", "scale mismatch")
            for field in ("requests_sha256", "resources_sha256"):
                require(r[field] == originals[k][field], f"formal input mismatch: {seed}, {k}, {field}")
            if k not in SIX | MIXED:
                continue
            metrics, clients = audit_run(base, r, float(m["hit_latency_ms"]))
            results[k].append(metrics)
            if k in SIX:
                print(f"RAW {seed} {k}: {metrics}")
            if k in MIXED:
                rates = [v[0] for v in clients.values()]
                squares = sum(v*v for v in rates)
                j = sum(rates)**2 / (len(rates)*squares) if squares else math.nan
                worst = max(clients, key=lambda name: (clients[name][1], name))
                fairness[k].append((j, clients[worst][1], worst))
                for name, v in clients.items():
                    client[(*k, name)].append(v)
    for k, runs in sorted(results.items()):
        expected = main[k]
        require(len(runs) == int(expected["n_seeds"]) == 5, "seed count")
        for metric in runs[0]:
            vals = [r[metric] for r in runs]
            check(statistics.mean(vals), expected[metric+"_mean"], f"{k} {metric} mean")
            check(statistics.stdev(vals), expected[metric+"_std"], f"{k} {metric} std")
        if k in SIX:
            print("PASS six-cell metrics:", k)
    require(set(results) == SIX | MIXED, "audited grid mismatch")
    require(set(fairness) == set(fair), "fairness grid mismatch")
    for k, items in sorted(fairness.items()):
        exp = fair[k]
        require(len(items) == int(exp["n_seeds"]) == 5, "fairness seed count")
        js = [j for j, _, _ in items if not math.isnan(j)]
        ids = Counter(i for _, _, i in items)
        for field, value in (("jain_mean", statistics.mean(js) if js else math.nan),
                             ("jain_std", statistics.stdev(js) if len(js) > 1 else (0.0 if js else math.nan)),
                             ("worst_client_ms_mean", statistics.mean(t for _, t, _ in items))):
            check(value, exp[field], f"{k} {field}")
        require(min(ids, key=lambda i: (-ids[i], i)) == exp["worst_client_id"], "worst client mismatch")
    require(set(client) == set(pc), "per-client grid mismatch")
    for k, items in client.items():
        exp = pc[k]
        require(len(items) == int(exp["n_seeds"]) == 5, "client seed count")
        h = statistics.mean(v[0] for v in items)
        t = statistics.mean(v[1] for v in items)
        baseline = statistics.mean(v[1] for v in client[(k[0], k[1], "LRU", k[3])])
        for field, value in (("hit_rate_mean", h), ("avg_response_ms_mean", t), ("delta_vs_baseline_ms", t-baseline)):
            check(value, exp[field], f"{k} {field}")
    print(f"PASS: {len(results)} metric cells; {len(fairness)} fairness cells; {len(client)} per-client rows.")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--official", type=Path, default=Path("data/results/main"))
    args = parser.parse_args()
    audit(args.generated, args.official)

if __name__ == "__main__":
    main()
