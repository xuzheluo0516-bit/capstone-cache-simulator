"""Run the whole D experiment pipeline in order.

Stages: H tuning -> main -> fairness -> ablation -> drift -> plots.
The half-life H is read from the h_choice.json written by the tuning stage
(key chosen_half_life) and passed to main and ablation; it is never
hard-coded here. --half-life overrides it for main and ablation (the tuning
stage still runs and its choice is recorded, so the override is visible).
The drift experiment always keeps its preregistered H=20; overriding H for the
main comparison must not silently change that confirmatory test.

Everything is written under --output-dir (default data/experiments/run_all),
never into the committed data/results/. If a stage fails the script stops and
exits with that stage's non-zero code.

Layout of --output-dir:
  h-tuning/  main/  ablation/  drift/  figures/  run_all.json (what was run)
Note: the tuning stage always uses the 1440-request "large" traces and the
drift stage has a fixed design, so --scale only affects main and ablation.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from common import validate_formal_seeds, validate_half_life

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_OUTPUT = Path("data/experiments/run_all")
DEFAULT_SEEDS = (20261111, 20261112, 20261113, 20261114, 20261115)
DRIFT_HALF_LIFE = 20.0  # fixed by DRIFT_PREREGISTRATION.md
PROTECTED = (Path("data/results"),)


def script(name: str) -> str:
    return str(HERE / name)


def stage_tuning(out: Path, args) -> list[str]:
    return [sys.executable, script("run_h_tuning.py"), "--output-dir", str(out / "h-tuning")]


def stage_main(out: Path, args, half_life: float) -> list[str]:
    return [sys.executable, script("run_main.py"), "--output-dir", str(out / "main"),
            "--half-life", repr(half_life), "--scale", args.scale,
            "--seeds", *map(str, args.seeds)]


def stage_fairness(out: Path, args) -> list[str]:
    return [sys.executable, script("analyze_fairness.py"), "--results-dir", str(out / "main"),
            "--seeds", *map(str, args.seeds)]


def stage_ablation(out: Path, args, half_life: float) -> list[str]:
    return [sys.executable, script("run_ablation.py"), "--output-dir", str(out / "ablation"),
            "--half-life", repr(half_life), "--scale", args.scale,
            "--seeds", *map(str, args.seeds)]


def stage_drift(out: Path, args) -> list[str]:
    return [sys.executable, script("run_drift.py"), "--output-dir", str(out / "drift"),
            "--half-life", repr(DRIFT_HALF_LIFE), "--seeds", *map(str, args.seeds)]


def stage_plots(out: Path, args) -> list[str]:
    return [sys.executable, script("make_plots.py"), "--results-dir", str(out / "main"),
            "--figures-dir", str(out / "figures"), "--bar-capacity", str(args.bar_capacity),
            "--tuning-dir", str(out / "h-tuning")]


def read_chosen_half_life(out: Path) -> float:
    path = out / "h-tuning" / "h_choice.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return float(data["chosen_half_life"])


def check_output_dir(out: Path) -> None:
    resolved = out.resolve()
    for protected in PROTECTED:
        target = (REPO / protected).resolve()
        if resolved == target or target in resolved.parents:
            raise SystemExit(f"refusing to write into {protected}: it holds the committed results")


def run_pipeline(args, runner=subprocess.run) -> int:
    # Child stages always run with cwd=REPO, so a relative --output-dir must be
    # resolved against the caller's cwd before it is handed to them.
    out = args.output_dir.resolve()
    check_output_dir(out)
    out.mkdir(parents=True, exist_ok=True)
    log: dict = {"output_dir": str(out), "seeds": list(args.seeds), "scale": args.scale,
                 "half_life_override": args.half_life,
                 "drift_half_life": DRIFT_HALF_LIFE, "stages": []}

    def run(name: str, command: list[str]) -> int:
        print(f"\n=== {name} ===", flush=True)
        code = runner(command, cwd=str(REPO)).returncode
        log["stages"].append({"stage": name, "returncode": code})
        (out / "run_all.json").write_text(
            json.dumps(log, indent=2) + "\n", encoding="utf-8", newline="\n")
        if code != 0:
            print(f"stage '{name}' failed with exit code {code}; stopping", file=sys.stderr)
        return code

    code = run("h-tuning", stage_tuning(out, args))
    if code:
        return code
    chosen = read_chosen_half_life(out)
    half_life = args.half_life if args.half_life is not None else chosen
    log["chosen_half_life"] = chosen
    log["half_life_used"] = half_life
    print(f"chosen H = {chosen}; using H = {half_life}", flush=True)
    for name, command in (
        ("main", stage_main(out, args, half_life)),
        ("fairness", stage_fairness(out, args)),
        ("ablation", stage_ablation(out, args, half_life)),
        ("drift", stage_drift(out, args)),
        ("plots", stage_plots(out, args)),
    ):
        code = run(name, command)
        if code:
            return code
    print(f"\nall stages finished -> {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS),
                        help="formal seeds (at least 2; the tuning seed is refused)")
    parser.add_argument("--scale", default="large", choices=("small", "medium", "large"),
                        help="trace size for main and ablation")
    parser.add_argument("--half-life", type=float, default=None,
                        help="override H; by default the value chosen by the tuning stage is used")
    parser.add_argument("--bar-capacity", type=int, default=512,
                        help="capacity (KiB) of the bar charts")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_formal_seeds(parser, args.seeds)
    validate_half_life(parser, args.half_life)
    return run_pipeline(args)


if __name__ == "__main__":
    raise SystemExit(main())
