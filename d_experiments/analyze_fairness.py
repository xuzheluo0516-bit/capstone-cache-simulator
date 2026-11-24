"""Client fairness analysis from the per-client results of run_main.py.

For every (policy, capacity) of one workload (default: mixed):
  * Jain index J = (sum x_c)^2 / (n * sum x_c^2) over the clients' request hit
    rates x_c, computed per seed and then averaged over seeds. J is in [1/n, 1];
    1 means all clients enjoy equal hit rates. If every x_c is 0 it is undefined
    and reported as nan. A client with an inherently low hit rate (e.g. a media
    consumer) lowers J for every policy, so compare policies, not absolute J.
  * worst-client response time: the largest per-client average response time
    (per seed, then averaged over seeds) and the client that is most often worst.
Also writes each client's mean hit rate / response time and its change relative
to a baseline policy (default LRU; negative delta = faster than the baseline).
Outputs: fairness.csv and per_client.csv in --results-dir.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path

from common import mean, stdev, write_csv

FAIRNESS_FIELDS = (
    "workload", "capacity_KiB", "policy", "n_seeds", "jain_mean", "jain_std",
    "worst_client_ms_mean", "worst_client_id",
)
PER_CLIENT_FIELDS = (
    "workload", "capacity_KiB", "policy", "client_id", "n_seeds",
    "hit_rate_mean", "avg_response_ms_mean", "delta_vs_baseline_ms",
)


def jain(values: Sequence[float]) -> float:
    squares = sum(v * v for v in values)
    if not values or squares == 0:
        return math.nan
    return sum(values) ** 2 / (len(values) * squares)


def fairness_tables(
    client_rows: Sequence[dict], workload: str = "mixed", baseline: str = "LRU"
) -> tuple[list[dict], list[dict]]:
    rows = [r for r in client_rows if r["workload"] == workload]
    if not rows:
        raise ValueError(f"no client rows for workload {workload!r}")
    runs: dict[tuple, list[dict]] = defaultdict(list)  # (policy, capacity, seed)
    for row in rows:
        runs[(row["policy"], int(row["capacity_bytes"]), row["seed"])].append(row)

    cells: dict[tuple, list[tuple[float, float, str]]] = defaultdict(list)
    for (policy, capacity, _seed), members in runs.items():
        worst = max(members, key=lambda r: (float(r["average_response_ms"]), r["client_id"]))
        cells[(policy, capacity)].append((
            jain([float(m["request_hit_rate"]) for m in members]),
            float(worst["average_response_ms"]), worst["client_id"],
        ))
    fairness = []
    for (policy, capacity), items in sorted(cells.items()):
        jains = [j for j, _, _ in items if not math.isnan(j)]
        ids = Counter(i for _, _, i in items)
        top = max(ids.values())
        fairness.append({
            "workload": workload, "capacity_KiB": capacity / 1024, "policy": policy,
            "n_seeds": len(items),
            "jain_mean": mean(jains) if jains else math.nan,
            "jain_std": stdev(jains) if jains else math.nan,
            "worst_client_ms_mean": mean([ms for _, ms, _ in items]),
            "worst_client_id": sorted(i for i, c in ids.items() if c == top)[0],
        })

    per: dict[tuple, list[dict]] = defaultdict(list)  # (policy, capacity, client)
    for row in rows:
        per[(row["policy"], int(row["capacity_bytes"]), row["client_id"])].append(row)
    means = {
        key: (mean([float(m["request_hit_rate"]) for m in ms]),
              mean([float(m["average_response_ms"]) for m in ms]), len(ms))
        for key, ms in per.items()
    }
    per_client = []
    for (policy, capacity, client), (hit, ms, n) in sorted(means.items()):
        base = means.get((baseline, capacity, client))
        per_client.append({
            "workload": workload, "capacity_KiB": capacity / 1024, "policy": policy,
            "client_id": client, "n_seeds": n, "hit_rate_mean": hit,
            "avg_response_ms_mean": ms,
            "delta_vs_baseline_ms": "" if base is None else ms - base[1],
        })
    return fairness, per_client


def read_client_rows(results_dir: Path, seeds: Sequence[int] | None = None) -> list[dict]:
    if seeds is None:
        paths = sorted(results_dir.glob("seed_*/clients.csv"))
    else:
        paths = [results_dir / f"seed_{seed}" / "clients.csv" for seed in seeds]
    rows: list[dict] = []
    for path in paths:
        with path.open(newline="", encoding="utf-8") as handle:
            rows.extend(csv.DictReader(handle))
    if not rows:
        raise FileNotFoundError(f"no clients.csv for the requested seeds under {results_dir}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--workload", default="mixed")
    parser.add_argument("--baseline", default="LRU")
    parser.add_argument(
        "--seeds", type=int, nargs="+", default=None,
        help="only aggregate these seeds (default: every seed_*/clients.csv found)",
    )
    args = parser.parse_args()
    fairness, per_client = fairness_tables(
        read_client_rows(args.results_dir, args.seeds), args.workload, args.baseline
    )
    write_csv(args.results_dir / "fairness.csv", FAIRNESS_FIELDS, fairness)
    write_csv(args.results_dir / "per_client.csv", PER_CLIENT_FIELDS, per_client)
    print(f"workload={args.workload}  fairness rows={len(fairness)}  "
          f"per-client rows={len(per_client)}")
    print(f"{'policy':<8}{'KiB':>8}{'Jain':>8}{'worst ms':>10}  worst client")
    for row in fairness:
        print(f"{row['policy']:<8}{row['capacity_KiB']:>8.0f}{row['jain_mean']:>8.3f}"
              f"{row['worst_client_ms_mean']:>10.2f}  {row['worst_client_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
