# Formal experiment audit and archive boundary

Audit date: 2026-11-27. Source: committed `main` manifests, tables, and Python files. Run from the repository root:

```bash
python scripts/audit_results.py --results-dir data/results
```

The audit is read-only and exits nonzero on the first mismatch. It checks each formal seed manifest against the full workload × capacity × policy grid, `planned_runs`, `completed_runs`, per-run status, shared input hashes, code/dependency identifiers, fixed 5 ms hit latency, empty initial state, and `CUSTOM` half-life 20. It also audits `data/results/course/` (manifest status and run counts, SHA-256 of the committed inputs in `data/reference/`, core/experiment/course source hashes, the completeness of all seven course tables, and client-derived run average response and fairness values). It checks tuning and drift counts, the tuning seed and selected H, aggregate table row keys, and the core/experiment source hashes against current Python files. A missing-run mutation was separately tested and rejected.

## Observed result

| Stage | Conditions checked | Result |
| --- | ---: | --- |
| Main: 5 seeds × 3 workloads × 5 capacities × 5 policies | 375 | PASS |
| Ablation: 5 seeds × 3 workloads × 5 capacities × 4 variants | 300 | PASS |
| H tuning: seed 31415 × 3 workloads × 5 capacities × 8 policies | 120 | PASS |
| Drift: 5 seeds × 5 capacities × 6 policies | 150 | PASS |
| Course traces: 3 workloads × 6 capacities × 5 policies (`data/results/course/`; added by PR #43) | 90 | PASS |

The committed aggregate grids contain 75 main rows, 75 mixed per-client rows, 25 fairness rows, 3 ablation overview rows, 45 ablation-by-capacity rows, 150 drift run rows, 30 drift aggregate rows, and 120 tuning summary rows. All were checked for duplicate or missing condition keys. All 13 manifests (12 synthetic-stage plus the course-trace manifest) report complete counts; the drift manifest reports zero failed runs. The five formal seeds are `20261111`–`20261115`; tuning uses only `31415`. The selected half-life is `H = 20`.

All manifests agree on the code revision and source hashes. Independently recomputing the hashes of `src/cache_simulator/*.py` and `d_experiments/*.py` from the audited tree matched the recorded values. Within each formal seed and workload, all capacities and policies reference the same resource and request SHA-256 values.

## What this does not establish

The committed archive contains aggregate CSVs and manifests, while per-run `summary.csv`, `clients.csv`, `events/`, and generated inputs remain in ignored scratch output. Therefore this audit cannot read those absent files, recompute every numerical aggregate from raw events, or verify recorded input hashes against the original bytes. Reproduction through `python d_experiments/run_all.py` and comparison with the committed tables is the separate numerical check. A manifest's `code_version` records the revision used for the original run; the source hash check verifies the code currently archived, not that a Git history commit remains available forever.

## Archive convention for the final ZIP

Preserve `data/reference/`, the committed `data/generated/` examples, `data/tuning/`, the complete `data/results/` tree (13 manifests, CSV tables, `h_choice.json`, and twelve PNG figures), `src/`, `d_experiments/`, `tests/`, `docs/`, `README.md`, `HOWTO.md`, `pyproject.toml`, `requirements.txt`, `Makefile`, and `make.ps1`. Keep relative paths unchanged. Exclude local `.venv/`, caches, and `data/experiments/` scratch runs. The latter can be regenerated and may contain machine-specific absolute paths.

Before submission, inspect the actual ZIP listing and extract it in a clean directory. Confirm that all twelve figures and all 13 manifests are present, run the audit command above, then run the test, reference-validation, and experiment commands in `HOWTO.md`. This document records the E-side archive rule and audit; final ZIP creation and Brightspace submission belong to the team's final packaging step.
