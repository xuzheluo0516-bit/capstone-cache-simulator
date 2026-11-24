"""Shared helpers for D's experiment scripts (multi-seed runs, aggregation)."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
from collections import defaultdict
from collections.abc import Mapping, Sequence
from importlib import metadata
from pathlib import Path

from cache_simulator.cli import POLICY_REGISTRY
from cache_simulator.experiments import run_suite
from cache_simulator.gdsf import GDSFPolicy
from cache_simulator.rwcsf import RWCSFPolicy
from cache_simulator.workloads import DEFAULT_COUNTS

WORKLOADS = ("repeated", "sequential", "mixed")
TUNING_SEED = 31415  # fixed by the tuning pre-registration; never a formal seed


def validate_formal_seeds(parser, seeds) -> None:
    """Reject tuning/duplicate/too-few seeds before an experiment starts."""
    if TUNING_SEED in seeds:
        parser.error(f"seed {TUNING_SEED} is the tuning seed and must not be used here")
    if len(set(seeds)) != len(seeds):
        parser.error("formal seeds must be unique")
    if len(set(seeds)) < 2:
        parser.error("give at least 2 different seeds (standard deviations need n >= 2)")


def validate_half_life(parser, half_life) -> None:
    """Reject NaN/inf/non-positive H before any stage spends time running."""
    if half_life is not None and not (math.isfinite(half_life) and half_life > 0):
        parser.error("--half-life must be a finite positive number")


def build_registry(half_life: float) -> tuple[dict, dict]:
    """Registry + parameters: baselines, CUSTOM (full RW-CSF) and ablations."""
    registry = {**POLICY_REGISTRY, "GDSF": GDSFPolicy, "CUSTOM": RWCSFPolicy}
    parameters = {
        "CUSTOM": {"half_life": half_life},
        "ABL_NO_LATENCY": {"half_life": half_life, "use_latency": False},
        "ABL_NO_SIZE": {"half_life": half_life, "use_size": False},
        "ABL_NO_DECAY": {"half_life": math.inf},
    }
    for name in ("ABL_NO_LATENCY", "ABL_NO_SIZE", "ABL_NO_DECAY"):
        registry[name] = RWCSFPolicy
    return registry, parameters


def run_seeds(
    output_dir: Path,
    seeds: Sequence[int],
    policies: Sequence[str],
    registry: Mapping,
    parameters: Mapping,
    scale: str,
    capacities_bytes: Sequence[int] | None = None,
) -> list[dict]:
    """Run run_suite once per seed (own sub-directory); return all summary rows."""
    rows: list[dict] = []
    for seed in seeds:
        seed_dir = output_dir / f"seed_{seed}"
        kwargs = {} if capacities_bytes is None else {"capacities_bytes": capacities_bytes}
        try:
            manifest = run_suite(
                seed_dir, seed=seed, counts={scale: DEFAULT_COUNTS[scale]},
                policies=list(policies), registry=registry,
                policy_parameters={k: v for k, v in parameters.items() if k in policies},
                **kwargs,
            )
        except Exception:
            # run_suite writes a failed manifest itself; rewrite it so a bare
            # Infinity from ABL_NO_DECAY never reaches a strict JSON reader.
            rewrite_manifest(seed_dir / "manifest.json")
            raise
        write_manifest(seed_dir / "manifest.json", manifest)
        with (seed_dir / "summary.csv").open(newline="", encoding="utf-8") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def _json_safe(value):
    """Replace non-standard JSON floats (Infinity/NaN) with explicit strings."""
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return "nan"
        return "inf" if value > 0 else "-inf"
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def rewrite_manifest(path: Path) -> None:
    """Re-serialize an existing manifest as strict JSON, keeping its content."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    write_manifest(path, manifest)


def experiment_source_sha256() -> str:
    """Hash the D experiment scripts so the committed tables are auditable."""
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).resolve().parent.glob("*.py")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def core_source_sha256() -> str:
    """Same source hash that cache_simulator.experiments writes into manifests."""
    from cache_simulator import __file__ as package_file

    digest = hashlib.sha256()
    for path in sorted(Path(package_file).resolve().parent.glob("*.py")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


MANIFEST_PATH_FIELDS = ("events_file", "resources_file", "requests_file", "metadata_file")


def _posix_paths(value):
    """Keep committed manifests identical on Windows and POSIX."""
    if isinstance(value, dict):
        return {
            key: (item.replace("\\", "/")
                  if key in MANIFEST_PATH_FIELDS and isinstance(item, str)
                  else _posix_paths(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_posix_paths(item) for item in value]
    return value


def write_manifest(path: Path, manifest: Mapping) -> dict:
    """Write a strict-JSON manifest with experiment-script provenance."""
    safe = _posix_paths(_json_safe(dict(manifest)))
    safe["experiment_source_sha256"] = experiment_source_sha256()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(safe, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    return safe


def dependency_versions() -> dict:
    try:
        package = metadata.version("capstone-cache-simulator")
    except metadata.PackageNotFoundError:
        package = None
    return {"python": platform.python_version(), "package": package}


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def stdev(values: Sequence[float]) -> float:
    """Sample standard deviation (n - 1); 0.0 for fewer than two values."""
    if len(values) < 2:
        return 0.0
    centre = mean(values)
    return math.sqrt(sum((v - centre) ** 2 for v in values) / (len(values) - 1))


METRICS = ("average_response_ms", "request_hit_rate", "byte_hit_rate", "origin_bytes")


def aggregate_summary(rows: Sequence[dict], metrics: Sequence[str] = METRICS) -> list[dict]:
    """Mean and sample std over seeds for every (workload, capacity, policy)."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["workload"], float(row["capacity_KiB"]), row["policy"])].append(row)
    out: list[dict] = []
    for (workload, capacity, policy), members in sorted(groups.items()):
        seeds = {m["seed"] for m in members}
        if len(seeds) != len(members):
            raise ValueError(f"duplicate rows for one seed in {(workload, capacity, policy)}")
        line = {"workload": workload, "capacity_KiB": capacity, "policy": policy,
                "n_seeds": len(seeds)}
        for metric in metrics:
            values = [float(m[metric]) for m in members]
            line[f"{metric}_mean"] = mean(values)
            line[f"{metric}_std"] = stdev(values)
        out.append(line)
    return out


def aggregate_fields(metrics: Sequence[str] = METRICS) -> tuple[str, ...]:
    fields = ["workload", "capacity_KiB", "policy", "n_seeds"]
    for metric in metrics:
        fields += [f"{metric}_mean", f"{metric}_std"]
    return tuple(fields)


def percent_change(value: float, base: float) -> float:
    if base == 0:
        return math.nan
    return (value - base) / base * 100.0


def mean_response_by(rows: Sequence[dict], keys: Sequence[str]) -> dict[tuple, float]:
    """Mean of average_response_ms grouped by the given summary columns."""
    groups: dict[tuple, list[float]] = defaultdict(list)
    for row in rows:
        groups[tuple(row[key] for key in keys)].append(float(row["average_response_ms"]))
    return {group: mean(values) for group, values in groups.items()}


def write_csv(path: Path, fields: Sequence[str], rows: Sequence[Mapping]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
