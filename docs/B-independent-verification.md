# B3/B4 — Independent verification and fairness review

## Scope and status (2026-11-27)
The committed formal results are from PR #32, accepted in #33. This review independently recalculates relationships in the published tables and inspects the fairness implementation; it does not claim a new raw-event replay. Original events and generated inputs are reproducible scratch files, not committed. The raw-event audit in tools/b_verify.py is ready for execution but is not yet verified against the full simulator.

## B3 — Cross-table check
The published mixed workload has 1,440 requests per seed. A candidate fixed client-count vector (browser 483, media 486, random 471) was inferred using CUSTOM 32 and 256 KiB global hit rates and the total count. These are calibration rows, not independent validation. Recomputing the weighted global hit rates and latencies across all 25 mixed cells gives maximum absolute differences of 1.12e-16 and 4.27e-14 ms respectively. The 23 remaining cells are holdout consistency checks, conditional on these counts. Raw traces must confirm the counts.

| Policy | KiB | Weighted hit rate | Weighted mean latency (ms) |
|---|---:|---:|---:|
| CUSTOM | 32 | 17.125000% | 122.086806 |
| CUSTOM | 128 | 17.944444% | 119.301111 |
| CUSTOM | 256 | 56.902778% | 87.783472 |
| CUSTOM | 512 | 64.236111% | 73.966389 |
| CUSTOM | 1024 | 98.125000% | 21.460417 |
| FIFO | 32 | 16.166667% | 122.229028 |

Example: CUSTOM 512 KiB request hit rate = (483*0.9730848861283643 + 486*0.4082304526748971 + 471*0.5447983014861996)/1440 = 0.6423611111. Latency = (483*7.540786749482402 + 486*148.3724279835391 + 471*65.30870488322718)/1440 = 73.9663888889 ms. Byte hit rate cannot generally be derived from averaged origin traffic because per-seed denominators may differ.

All five committed manifests have 75 planned, 75 completed, 75 unique condition keys and 75 complete run statuses (375 total). Each records source revision 170da5de4cdaf3054b856c9689848a0b22c8687e. This verifies the recorded counts, not actual execution.

## Raw replay (UNVERIFIED)
From repository root, use a fresh scratch directory:
```sh
python -m pip install -e .
python d_experiments/run_main.py --output-dir data/experiments/B-audit --half-life 20
python tools/b_verify.py --generated data/experiments/B-audit
```
The audit independently reads resources, requests and events, compares input hashes with committed manifests, checks event identity, counters, latency and capacity, then recomputes all four metrics (mean and sample SD) for six conditions (three workloads x CUSTOM/LRU at 512 KiB) and all mixed cells. It also checks all fairness and per-client rows. It does not independently implement replacement strategies. Record actual terminal output and six worked calculations before B3 sign-off. Never replace committed results with scratch outputs.

## B4 — Fairness
Source-level methodology agrees with the data dictionary: Jain index is calculated over each seed's client request hit rates and then averaged; all-zero rates are undefined. Worst latency is the mean of per-seed maxima; the most frequent worst client is reported, with alphabetical tie conventions documented. Client delta = policy latency minus same-client LRU latency. All 75 published delta values match subtraction exactly; media is the worst client in all 25 mixed cells. Full per-seed fairness replay is still UNVERIFIED.

| Mixed, 512 KiB | CUSTOM | LRU |
|---|---:|---:|
| Request hit rate | 64.24% | 42.31% |
| Byte hit rate | 9.84% | 11.79% |
| Mean latency (ms) | 73.97 | 81.78 |
| Mean origin bytes | 792459673.6 | 775317094.4 |
| Jain index | 0.8766 | 0.9507 |
| Worst-client latency (ms) | 148.37 | 127.06 |

Browser improves by 28.89 ms and random by 16.25 ms, while media worsens by 21.32 ms. The custom policy improves aggregate request hits and latency versus LRU, but increases origin traffic and reduces hit-rate equality. Jain measures equality, not latency or satisfaction. Results are descriptive, not significance tests. At 1024 KiB all five policies tie on mixed metrics. CUSTOM is not the overall latency winner at mixed 512 KiB (GDSF is).

## Acceptance status
| Criterion | Status | Evidence |
|---|---|---|
| Published cross-table arithmetic | PASS (conditional counts) | main_table.csv, per_client.csv; calculations above |
| Recorded run completeness | PASS (manifest only) | five seed manifests |
| Six independent raw-event results | UNVERIFIED | tools/b_verify.py; replay required |
| Fairness definitions and client deltas | PASS (source/table checks) | analyze_fairness.py, fairness.csv, per_client.csv |
| Fairness per-seed numerical replay | UNVERIFIED | tools/b_verify.py |
| Overall B3/B4 final sign-off | UNVERIFIED | raw replay and human review pending |

Sources: [main results](../data/results/main/), [fairness code](../d_experiments/analyze_fairness.py), [data dictionary](data_dictionary.md), [#33](https://github.com/xuzheluo0516-bit/capstone-cache-simulator/issues/33), [#15](https://github.com/xuzheluo0516-bit/capstone-cache-simulator/issues/15).
