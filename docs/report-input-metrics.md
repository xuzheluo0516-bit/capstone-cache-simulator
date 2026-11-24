# Report material — inputs, metrics, and experiment method

This note supplies the report sections on input data, metrics, output, and
reproducibility. It describes the final experiment artifacts produced by
`d_experiments/` and the committed tables under `data/results/`. Numeric
comparisons and conclusions must be read from those tables after the
corresponding acceptance review, not from this method note.

## 1. Input data and event processing

The simulator reads two UTF-8 CSV inputs. The resource catalogue has eight
fields: `scheme`, `host`, `path`, `status_code`, `content_type`,
`size_bytes`, `origin_latency_ms`, and `cache_control`. A resource is
identified by the complete `(scheme, host, path)` key, not by its path alone.
The request trace has six fields: `timestamp`, `client_id`, `method`,
`scheme`, `host`, and `path`. Every request must be a `GET` for a resource in
the catalogue.

The parser uses standard CSV handling, so quoted fields may contain commas.
Requests are stably sorted by timestamp; equal timestamps retain their file
order. The parser then assigns a one-based sequence number, giving a
deterministic order for policy updates. Malformed rows, duplicate resource
keys, unknown resource references, invalid sizes or latencies, and invalid
timestamps are rejected with contextual validation errors.

## 2. Cache simulation and output

The cache is shared across clients and starts empty for each independent run.
Capacity and object sizes are represented in bytes; displayed cache usage in
KiB is bytes / 1,024. A hit uses the configured hit latency and contributes no
origin traffic. A miss uses the resource's origin latency and adds the full
object size to origin traffic. A resource larger than total cache capacity is
fetched but bypasses admission and does not evict resident objects.

The per-request output has ten fields: step, resource ID, client ID, HIT/MISS
result, eviction order, resident cache contents in insertion order, cache
usage in KiB, response time in milliseconds, cumulative origin bytes, and
cumulative hits. The metrics accumulator consumes each event once; the
serializer reads the resulting snapshots and does not update counters again.

## 3. Performance metrics

For N requests, H hits, requested resource size `s_i`, hit indicator `h_i`,
and response time `t_i`, the project reports:

- **Request hit rate:** `H / N`.
- **Byte hit rate:** `sum(h_i * s_i) / sum(s_i)`.
- **Average response time:** `sum(t_i) / N`.
- **Origin traffic:** `sum(s_i for every miss)`.

Repeated requests count each time in the byte denominator and, when they hit,
in the hit-byte numerator. Oversized-resource misses also contribute their
full size to request bytes and origin traffic. The global average response
time is request-weighted; it is not the average of per-client averages.
Per-client hit rate and average response time use that client's own request
count as the denominator. Undefined ratios are reported as `N/A` in the report
rather than dividing by zero.

## 4. Experiment design

The main comparison covers five policies: `FIFO`, `LRU`, `LFU`, `GDSF`, and
`CUSTOM` (RW-CSF). The half-life `H` is selected only on the tuning seed
`31415` from the candidates 5, 20, 100, and 500, using the pre-registered rule
in `d_experiments/run_h_tuning.py`; the selected value is `H = 20`. Formal runs
use seeds `20261111` through `20261115` and must not use the tuning seed.

Each formal run uses the three workload families (`repeated`, `sequential`,
`mixed`) at the large scale and five capacities: 32, 128, 256, 512, and
1,024 KiB. Every policy/capacity condition starts from a fresh empty cache and
uses the same input pair for a given workload and seed. The simulator uses a
5 ms hit latency.

The ablation removes one ingredient of RW-CSF at the fixed `H = 20`:

| Variant | Change |
| --- | --- |
| `ABL_NO_LATENCY` | Latency benefit replaced by 1; score `F / s` |
| `ABL_NO_SIZE` | Size normalization removed; score `F * dT` |
| `ABL_NO_DECAY` | Half-life set to infinity; no frequency decay |

The hotspot-drift check is supplementary and pre-registered in
`d_experiments/DRIFT_PREREGISTRATION.md`. It is not used to choose `H`. It
uses three 480-request phases, a four-resource hot group per phase (85% of
requests), 12 resources, one client, and capacities 32–1,024 KiB. Its
predictions and outcomes are reported separately from the main comparison.

## 5. Result files and reproducibility

`d_experiments/run_all.py` runs six stages, each of which must return zero:
half-life tuning, main comparison, fairness analysis, ablation, drift, and
plotting. It writes `run_all.json` with the seeds, scale, chosen half-life, and
per-stage return codes.

The committed tables are:

| Path | Content |
| --- | --- |
| `data/results/main/main_table.csv` | Mean and sample standard deviation over seeds for response time, request/byte hit rate, and origin traffic |
| `data/results/main/per_client.csv` | Per-client means and change relative to the `LRU` baseline |
| `data/results/main/fairness.csv` | Jain index and worst-client response time per policy and capacity |
| `data/results/h-tuning/summary.csv` | Per-run tuning rows for the candidate half-lives |
| `data/results/h-tuning/h_choice.json` | Pre-registered rule, candidate scores, and selected `H` |
| `data/results/ablation/ablation_table.csv` | Percent response-time change of each ablation variant relative to full RW-CSF |
| `data/results/ablation/ablation_by_capacity.csv` | Same comparison split by capacity |
| `data/results/drift/drift_runs.csv` | Drift result per seed, capacity, and policy |
| `data/results/drift/drift_table.csv` | Drift results aggregated over seeds |
| `data/results/figures/*.png` | Six figures regenerated from the committed CSVs |

Each seed directory also has a `manifest.json` recording the command, seed,
capacities, hit latency, initial state, policies and parameters, tested code
revision, simulator-source hash, experiment-source hash, dependency versions,
planned/completed run counts, and per-run input hashes and status. Generated
workload metadata records the workload kind, scale, seeds, counts, resource
sizes, and relative input filenames. Absolute paths in `run_all.json` are
machine-specific.

Per-seed `summary.csv`, `clients.csv`, `events/`, and generated inputs are
reproducible working files and are not all committed. The committed
aggregates and manifests are enough to trace each reported cell to its input
hashes and tested code revision.

## 6. Aggregation and fairness conventions

For repeated seeds, compute the metric within each seed for the same
workload/capacity/policy condition, then report the mean and sample standard
deviation across seeds (denominator `n - 1`). Do not pool requests across seeds
for the response-time mean.

For client fairness, Jain's index over non-negative client values `x_i` is

`J = (sum(x_i))^2 / (n * sum(x_i^2))`.

The committed table uses each client's request hit rate as `x_i`, computes `J`
per seed, and averages over seeds. The index is in `[1/n, 1]`; 1 means equal
client hit rates. If every `x_i` is zero, the value is undefined and is stored
as `nan`, not silently replaced with 0 or 1. A client with an inherently low
hit rate lowers `J` for every policy, so compare policies at the same capacity
instead of treating the absolute value as a quality score.

The worst client is the client with the largest per-client average response
time in a seed. `fairness.csv` reports the mean of that per-seed maximum as
`worst_client_ms_mean` and the client most often worst as `worst_client_id`,
with lexicographic tie-breaking. `per_client.csv` reports each client's mean
response time and its difference from the same client under `LRU`; a negative
difference means the policy is faster for that client.

## 7. Reference validation

The reference validator compares parsed CSV headers, row counts, and fields.
Text and integer values are checked exactly; numeric fields are compared
numerically, so equivalent representations such as 32 and 32.0 do not cause
false mismatches. Valid CSV quoting and CRLF/LF differences are ignored.

On the instructor's reference trace, with a 102,400-byte cache and 5 ms hit
latency, FIFO, LRU, and LFU produce 3, 3, and 4 hits respectively. Their
average response times are 95.33 ms, 92.33 ms, and 84.33 ms. These are
reference-validation results, not conclusions about the generated workloads
or the `GDSF`/`CUSTOM` policies.

Comparisons and conclusions belong in the report after the `data/results/`
tables pass acceptance. In particular, a pre-registered drift prediction that
is not supported must be reported as such rather than reframed after the
fact.
