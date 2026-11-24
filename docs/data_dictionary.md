# Data dictionary and simulation conventions

This document is the shared contract for the parser (#4), cache engine and
policies (#5–#7), metrics/output (#8), and reference validation (#9). The
instructor-provided files in `data/reference/` remain unchanged and are the
source of the reference trace.

## 1. Input CSV schemas

Both inputs are UTF-8 CSV files. Read them with Python's standard-library
`csv` module and `newline=""`; do not split lines or fields manually.
Fields containing commas, quotes, or line breaks must follow standard CSV
quoting and escaping rules. A quoted comma is part of one field, not a column
separator. For example, `"public, max-age=300"` is one `cache_control`
value. A quote inside a quoted field is escaped by doubling it (`""`).

### 1.1 Resource metadata: `resources.csv`

Exactly eight columns, in this order:

| Column | Type / unit | Meaning and validation |
| --- | --- | --- |
| `scheme` | non-empty string | URL scheme; part of resource identity |
| `host` | non-empty string | Host name; part of resource identity |
| `path` | non-empty string | URL path; part of resource identity |
| `status_code` | integer | Metadata retained on the Resource object |
| `content_type` | non-empty string | Metadata retained on the Resource object |
| `size_bytes` | non-negative integer, bytes | Resource size and accounting unit |
| `origin_latency_ms` | finite non-negative number, ms | Miss response time |
| `cache_control` | string | Retained as metadata; ignored by the core simulation |

The unique resource key is the complete tuple
`(scheme, host, path)`. The three components are compared independently;
identical paths on different hosts or schemes are different resources.
Duplicate tuples are invalid. The input has no `resource_id` column.

The parser does not filter resources based on `status_code` or
`cache_control`. In particular, `private`, `no-store`, `max-age`, and
non-200 status values do not change admission in this course's offline core
simulation. Every listed resource is available to the trace; only a request
that references a listed key is simulated.

### 1.2 Request trace: `requests_reference.csv`

Exactly six columns, in this order:

| Column | Type / unit | Meaning and validation |
| --- | --- | --- |
| `timestamp` | ISO-8601 datetime | Request time; reference values end in `Z` (UTC) |
| `client_id` | non-empty string | Client making the request |
| `method` | string | Must be exactly `GET` |
| `scheme` | non-empty string | First component of resource key |
| `host` | non-empty string | Second component of resource key |
| `path` | non-empty string | Third component of resource key |

Each request key must exist in the resource dictionary. The parser accepts
ISO-8601 timestamps; timezone-aware values are normalized by Python's
`datetime` ordering. A trace must not mix timezone-aware and naive
timestamps. The supplied reference trace uses the explicit UTC suffix `Z`.
All requests must use `GET`.

Requests are stably sorted by timestamp. If two timestamps are equal, their
original file order is preserved. After sorting, the parser assigns a
one-based, contiguous `sequence` (1, 2, ...). The sequence, not timestamp
precision, is the definitive tie-breaker for LRU/LFU access order. The parser
also retains the original physical CSV line as `source_line` for diagnostics.

An out-of-order input is therefore accepted and stably sorted, rather than
rejected. This behavior is covered by parser tests and is part of the contract.

### 1.3 Validation errors

Malformed headers, missing/extra fields, malformed quoting, empty required
values, duplicate resource keys, unknown request keys, non-GET methods,
invalid sizes, invalid/non-finite/negative latencies, and invalid timestamps
raise `InputValidationError`. Where a row is involved, the message includes
the source filename and physical line number; resource-specific errors include
the resource key when available. A request file containing only its correct
header, or a zero-byte request file, represents an empty trace. A resource
file must contain its header.

## 2. Resource IDs in output

The reference expected files use short labels A–E. These labels are a
presentation convention only; they are not input identifiers and must not be
hard-coded into the cache engine.

| Reference ID | Resource key: `(scheme, host, path)` |
| --- | --- |
| A | `(https, learn.university.edu, /courses/ics/index.html)` |
| B | `(https, learn.university.edu, /static/main.css)` |
| C | `(https, learn.university.edu, /static/logo.svg)` |
| D | `(https, cdn.university.edu, /images/avatar-default.png)` |
| E | `(https, pypi.org, /static/css/warehouse.css)` |

For general traces, output labels are assigned in order of first appearance
in the request sequence: A, B, ..., Z, AA, AB, ... . The same key always
keeps the same label within one output. A different trace starts a fresh
label map. The engine and policies always use the full `ResourceKey`, never
these display labels, so any number of valid resources is supported.

## 3. Cache and policy semantics

- Capacity and resource sizes are integers measured in **bytes**. The
  reference capacity is 100 KiB = 102,400 bytes.
- The cache begins empty and is shared by all clients.
- A hit uses the configured hit latency (5 ms for the reference run), adds
  zero origin bytes, and counts as a hit for the requesting client.
- A miss uses the resource's `origin_latency_ms` and adds the full resource
  size to origin traffic.
- A miss for a resource no larger than total capacity must admit it. Evict
  repeatedly until enough free space exists. A resource larger than total
  capacity is fetched but not cached; it must not evict existing entries.
- FIFO hits do not change insertion order. LRU hits update most-recent-access
  order. LFU starts at frequency 1 on insertion, increments on every hit,
  breaks equal-frequency ties by least recent access, and removes frequency
  history on eviction. Reinsertion starts at 1 again.
- `cache_contents_oldest_first` always displays resident entries in insertion
  order, even under LRU/LFU. It is not the eviction-priority order.
  `evicted` lists victims in the exact order the engine evicted them.
- Cache-Control and expiration are ignored for this core offline exercise.

## 4. Per-request output CSV

The output contains exactly ten columns in this order:

| Column | Type / unit | Definition |
| --- | --- | --- |
| `step` | positive integer | Stable one-based request sequence |
| `resource_id` | string | First-appearance label described in §2 |
| `client_id` | string | Request's client |
| `result` | `HIT` or `MISS` | Engine result |
| `evicted` | string | Comma-separated labels in actual eviction order; `-` if none |
| `cache_contents_oldest_first` | string | Comma-separated labels in insertion order; `-` if empty |
| `cache_used_KiB` | number, KiB | `cache_used_bytes / 1024`; retain fractional KiB |
| `response_ms` | number, ms | Hit latency or resource origin latency |
| `cumulative_origin_bytes` | non-negative integer, bytes | Sum of miss resource sizes through this step |
| `cumulative_hits` | non-negative integer | Number of hits through this step |

The serializer uses the standard CSV writer. A list such as `A,B` is one
field and is quoted by the writer when required by CSV syntax. `-` means an
empty eviction/cache list; it is not a resource ID. Numeric columns are
compared numerically, so equivalent forms such as `32` and `32.0` match.
Valid CSV quoting and CRLF/LF line endings do not affect semantic equality.

## 5. Metrics definitions

Every `RequestResult` is consumed exactly once by the metrics accumulator.
The engine emits events; it does not own aggregate counters. The output
serializer is read-only and uses the cumulative values in metric snapshots.

Let N be the request count, H the hit count, M the miss count,
s_i the requested resource size in bytes, h_i equal to 1 for a hit (0 for a
miss), and t_i the response time in milliseconds.

| Metric | Formula |
| --- | --- |
| Request hit rate | H / N |
| Byte hit rate | sum(h_i × s_i) / sum(s_i) |
| Average response time | sum(t_i) / N |
| Origin traffic | sum(s_i for every miss), in bytes |

Repeated requests count repeatedly in the request-byte denominator and
numerator as appropriate. Oversized-resource misses also contribute their
full size to the denominator and to origin traffic. Global average response
time is calculated over all requests; do not average client averages.

For each client, request hit rate is that client's hits divided by that
client's request count, and average response time is that client's response
time sum divided by that client's request count. Client results are reported
in first-seen client order.

### 5.1 Empty and zero-denominator behavior

Each metric checks its own denominator independently:

- With no requests, request hit rate and average response time are undefined.
- With zero total requested bytes (for example, a trace of zero-byte
  resources), byte hit rate is undefined even if requests exist.
- Undefined ratios/averages are represented as `null` in machine-readable
  summaries and displayed as `N/A` in human-readable reports. Do not divide
  by zero.
- Counts and origin traffic remain valid numeric zeroes for an empty trace.

### 5.2 Invariants

For every completed run:

1. `hits + misses = requests`.
2. Sum of per-client request counts equals the global request count.
3. Sum of per-client hit counts equals the global hit count.
4. `hit bytes + origin bytes = total requested bytes`.
5. At every event, `0 <= cache used bytes <= capacity bytes`.

These are tested for repeated requests, unequal client workloads, oversized
requests, non-integral KiB values, and empty input.

## 6. Reference comparison precision

The three expected files are parsed with the standard CSV parser and compared
by header, row count, and field:

- Text fields (`resource_id`, `client_id`, `result`, `evicted`, and
  `cache_contents_oldest_first`) must match exactly after CSV decoding.
- Integer counters/byte fields must match exactly as integers.
- Other numeric fields are compared as numeric values, not raw strings;
  `32` and `32.0` are equivalent. Reference per-request times and cache
  capacity values are exact numeric comparisons.
- Aggregate averages and percentages are calculated from unrounded totals,
  then formatted to two decimal places for presentation. Do not round
  intermediate sums or truncate `cache_used_KiB`.
- CSV quoting style and CRLF/LF differences are ignored. The expected files
  themselves are not modified.

The reference run uses 102,400 bytes and 5 ms hit latency. Expected summaries:

| Policy | Hits / misses | Request hit rate | Origin traffic | Average response |
| --- | ---: | ---: | ---: | ---: |
| FIFO | 3 / 12 | 20.00% | 421,888 B | 95.33 ms |
| LRU | 3 / 12 | 20.00% | 403,456 B | 92.33 ms |
| LFU | 4 / 11 | 26.67% | 370,688 B | 84.33 ms |

Python support: **Python 3.11 or newer**, as declared by `pyproject.toml`.


## 7. Reference-derived byte and client metrics

The reference request trace contains 512,000 requested bytes in total. Its
byte-hit numerator counts every hit's resource size, including repeated hits:

| Policy | Hit bytes | Total request bytes | Byte hit rate |
| --- | ---: | ---: | ---: |
| FIFO | 90,112 B | 512,000 B | 17.60% |
| LRU | 108,544 B | 512,000 B | 21.20% |
| LFU | 141,312 B | 512,000 B | 27.60% |

Each reference client makes five requests. The following values are calculated
from the per-request trace (not by averaging the global metrics or the other
clients' averages):

| Policy | Client | Hits / requests | Request hit rate | Average response |
| --- | --- | ---: | ---: | ---: |
| FIFO | student-01 | 1 / 5 | 20.00% | 111.00 ms |
| FIFO | student-02 | 2 / 5 | 40.00% | 55.00 ms |
| FIFO | student-03 | 0 / 5 | 0.00% | 120.00 ms |
| LRU | student-01 | 2 / 5 | 40.00% | 87.00 ms |
| LRU | student-02 | 1 / 5 | 20.00% | 70.00 ms |
| LRU | student-03 | 0 / 5 | 0.00% | 120.00 ms |
| LFU | student-01 | 2 / 5 | 40.00% | 87.00 ms |
| LFU | student-02 | 1 / 5 | 20.00% | 70.00 ms |
| LFU | student-03 | 1 / 5 | 20.00% | 96.00 ms |

These additional values are checked by `tests/test_reference_validation.py`.

## 8. Formal experiment result files

The formal experiments are produced by `d_experiments/` and written under
`data/results/`. All CSV files are UTF-8 with a header row and LF line endings.
Numeric values are decimal text. Hit-rate, byte-hit-rate, and fairness inputs
are stored as fractions in `[0, 1]`, not as `12.5` for 12.5%; the ablation
`percent_change` columns are percentage points, so `0.205` means `+0.205%`.
Byte counts are exact integers unless the column name says otherwise.
`capacity_KiB` is `capacity_bytes / 1024`.

The committed result set contains the aggregated tables, the manifests, and
the six PNG figures. Per-seed `summary.csv`, `clients.csv`, `events/`, and
generated input files are reproducible working files and are not all
committed. The paths below use the layout written by `d_experiments/run_all.py`.

### 8.1 Per-seed `summary.csv` and `clients.csv`

`src/cache_simulator/experiments.py` writes one `summary.csv` and one
`clients.csv` per seed directory (`seed_<seed>/`) through `run_seeds()`.
`summary.csv` has one row per workload, scale, seed, capacity, and policy:

| Column | Meaning | Unit / convention |
| --- | --- | --- |
| `workload` | Workload family | `repeated`, `sequential`, or `mixed` |
| `scale` | Workload size label | `small`, `medium`, or `large` |
| `seed` | Formal workload seed | Integer |
| `capacity_bytes` | Cache capacity | Bytes; exact integer |
| `capacity_KiB` | Same capacity for display | KiB; bytes / 1024 |
| `policy` | Replacement policy | `FIFO`, `LRU`, `LFU`, `GDSF`, or `CUSTOM` |
| `requests` | Requests processed | Count |
| `hits`, `misses` | Cache hits and misses | Counts; `hits + misses = requests` |
| `request_bytes` | Sum of requested resource sizes, counting repeats | Bytes |
| `hit_bytes` | Sum of sizes of hit requests, counting repeats | Bytes |
| `origin_bytes` | Sum of sizes fetched on misses | Bytes |
| `request_hit_rate` | `hits / requests` | Fraction; empty if no requests |
| `byte_hit_rate` | `hit_bytes / request_bytes` | Fraction; empty if zero request bytes |
| `average_response_ms` | Request-weighted mean response time | Milliseconds; empty if no requests |
| `total_response_ms` | Sum of response times | Milliseconds |
| `resources_sha256` | SHA-256 of the exact resource CSV | Hex digest |
| `requests_sha256` | SHA-256 of the exact request CSV | Hex digest |
| `events_file` | Relative path to the per-request event CSV | Relative to the seed output directory |

`clients.csv` has one row per client within a seed, workload, scale,
capacity, and policy:

| Column | Meaning | Unit / convention |
| --- | --- | --- |
| `workload`, `scale`, `seed` | Same condition labels as `summary.csv` | As above |
| `capacity_bytes` | Cache capacity | Bytes |
| `policy` | Replacement policy | As above |
| `client_id` | Client identifier from the request trace | String |
| `requests` | Requests made by this client | Count |
| `hits`, `misses` | Hits and misses for this client | Counts |
| `request_hit_rate` | `hits / requests` for this client | Fraction; empty if no requests |
| `average_response_ms` | Mean response time for this client's requests | Milliseconds; empty if no requests |

The global average response time is request-weighted. Do not average the
per-client means to obtain it. A policy run always starts from a fresh, empty
cache for its condition; no warm-up requests are discarded.

### 8.2 `main_table.csv` (aggregated over seeds)

One row per workload, capacity, and policy, averaged over the five formal
seeds. The committed file uses `n_seeds = 5`:

| Column | Meaning |
| --- | --- |
| `workload` | Workload family |
| `capacity_KiB` | Capacity in KiB |
| `policy` | Replacement policy |
| `n_seeds` | Number of seeds in the aggregation |
| `average_response_ms_mean`, `average_response_ms_std` | Per-seed average response time, then mean and sample standard deviation across seeds |
| `request_hit_rate_mean`, `request_hit_rate_std` | Per-seed request hit rate, then mean / sample standard deviation |
| `byte_hit_rate_mean`, `byte_hit_rate_std` | Per-seed byte hit rate, then mean / sample standard deviation |
| `origin_bytes_mean`, `origin_bytes_std` | Per-seed origin traffic, then mean / sample standard deviation |

The standard deviation uses denominator `n - 1`. The mean of a metric is
computed on the per-seed values; it is not a pooled average over requests.

### 8.3 `per_client.csv`

One row per workload, capacity, policy, and client. The committed file covers
the `mixed` workload and uses `LRU` as the comparison baseline:

| Column | Meaning |
| --- | --- |
| `workload`, `capacity_KiB`, `policy`, `client_id` | Condition identifiers |
| `n_seeds` | Number of seeds contributing to the row |
| `hit_rate_mean` | Client request hit rate, averaged over seeds |
| `avg_response_ms_mean` | Client average response time, averaged over seeds |
| `delta_vs_baseline_ms` | `avg_response_ms_mean` minus the same client's mean for the baseline policy at the same capacity; negative means faster than the baseline; empty when the baseline cell is absent |

`d_experiments/analyze_fairness.py --baseline <policy>` selects the baseline;
the committed table uses the default `LRU`.

### 8.4 `fairness.csv`

One row per workload, capacity, and policy. For each seed, the script computes
Jain's index over the clients' request hit rates, then aggregates over seeds:

| Column | Meaning |
| --- | --- |
| `workload`, `capacity_KiB`, `policy` | Condition identifiers |
| `n_seeds` | Number of seeds with client rows for the condition |
| `jain_mean`, `jain_std` | Mean and sample standard deviation of the per-seed Jain index over client request hit rates |
| `worst_client_ms_mean` | For each seed, the maximum per-client average response time; then the mean across seeds |
| `worst_client_id` | Client most often attaining that per-seed maximum; ties are resolved by lexicographic order |

Jain's index is in `[1/n, 1]` for `n` clients; 1 means equal client hit rates.
If every client hit rate is zero, the index is undefined and stored as `nan`.
A client with an inherently low hit rate lowers the index for every policy, so
compare policies at the same capacity rather than reading the absolute index
as a quality score.

### 8.5 Half-life tuning (`h-tuning/`)

`h-tuning/summary.csv` uses the same per-seed schema as section 8.1 and was
generated with the tuning seed `31415`, not a formal seed. Its policy names
include `RWCSF_H5`, `RWCSF_H20`, `RWCSF_H100`, `RWCSF_H500`, plus `FIFO`,
`LRU`, `LFU`, and `GDSF`.

`h-tuning/h_choice.json` records the pre-registered selection rule and result:

| Field | Meaning |
| --- | --- |
| `protocol` | Selection rule: mean over capacities per workload, then mean over the three workloads of `average_response_ms`; smallest wins, ties prefer the smaller half-life |
| `candidates` | Candidate half-lives tested: `[5, 20, 100, 500]` |
| `seed` | Tuning seed `31415` |
| `scores_ms` | Score for each candidate, keyed by candidate value |
| `chosen_half_life` | Selected half-life; the committed run selected `20` |
| `source_sha256` | SHA-256 of the experiment source used for the tuning run |

The formal seeds are `20261111` through `20261115`; the tuning seed must not
appear in formal runs.

### 8.6 Ablation (`ablation/`)

The ablation removes one ingredient of RW-CSF at the fixed half-life:

| Variant | Change from `CUSTOM` |
| --- | --- |
| `ABL_NO_LATENCY` | Replace the latency benefit `dT` with 1; score becomes `F / s` |
| `ABL_NO_SIZE` | Remove size normalization; score becomes `F * dT` |
| `ABL_NO_DECAY` | Half-life becomes infinity; frequency stops decaying |

`ablation/ablation_table.csv` has `variant`, then one column per workload
(`repeated`, `sequential`, `mixed`). Each cell is the percent change in mean
average response time of the variant relative to the full policy, first
averaging over capacities, then over seeds. Positive means the variant is
slower, so the removed ingredient helped.

`ablation/ablation_by_capacity.csv` has columns `variant`, `workload`,
`capacity_KiB`, `full_ms`, `variant_ms`, and `percent_change`; it keeps the
per-capacity values used by the summary table.

### 8.7 Hotspot drift (`drift/`)

The drift experiment is a supplementary, pre-registered check described in
`d_experiments/DRIFT_PREREGISTRATION.md`; it is not used to choose the
half-life. It uses one client, 1,440 requests in three 480-request phases, 12
resources (four per phase), a 4-resource hot group per phase (85% of requests),
and five fixed capacities (32, 128, 256, 512, 1,024 KiB).

`drift/drift_runs.csv` has one row per seed, capacity, and policy with columns
`seed`, `capacity_KiB`, `policy`, `average_response_ms`, `request_hit_rate`,
`byte_hit_rate`, and `origin_bytes`.

`drift/drift_table.csv` aggregates those rows over seeds: `capacity_KiB`,
`policy`, `n_seeds`, `average_response_ms_mean`, `average_response_ms_std`,
`request_hit_rate_mean`, `byte_hit_rate_mean`. The policies are `FIFO`, `LRU`,
`LFU`, `GDSF`, `CUSTOM` (RW-CSF at H=20), and `NO_DECAY` (H=infinity).

### 8.8 Manifests and generated-input metadata

Every `manifest.json` produced by `run_suite()` records at least:

| Field | Meaning |
| --- | --- |
| `schema_version` | Manifest schema version |
| `command` | Entry point that produced the run |
| `seed`, `counts` | Seed and per-scale request counts |
| `capacities_bytes`, `capacity_unit` | Exact capacities and unit convention |
| `hit_latency_ms` | Hit latency used for every run |
| `initial_state` | Empty cache, no warm-up |
| `policies`, `policy_parameters` | Policies and constructor parameters (for example `CUSTOM.half_life`) |
| `code_version` | Tested Git revision when available |
| `source_sha256` | SHA-256 of the simulator source used for the run |
| `experiment_source_sha256` | SHA-256 of the `d_experiments/` scripts used for the run |
| `dependency_versions` | Python and package versions |
| `planned_runs`, `completed_runs` | Planned and completed run counts |
| `runs` | Per-condition records |
| `status` | Overall run status |

Each `runs` item records `workload`, `scale`, `capacity_bytes`, `policy`,
relative paths to the resource/request/metadata inputs and event output,
SHA-256 hashes of both input CSVs, and `status`. A failed run also records an
`error` message. The drift manifest additionally records its `design`,
`seeds`, `half_life`, `capacities_KiB`, sizes and latencies per slot,
`input_sha256`, `preregistration`, `failed_runs`, `sizes_KiB_per_slot`,
`latencies_ms_per_slot`, and the command.

Each generated workload metadata JSON records these fields:

| Field | Meaning |
| --- | --- |
| `kind`, `scale` | Workload family and size label |
| `seed`, `condition_seed` | Top-level generator seed and the seed for this workload/scale condition |
| `request_count` | Requests in the trace |
| `client_count` | Distinct clients |
| `resource_count` | Catalogue resources, including oversized resources |
| `active_resource_count` | Resources actually used by the trace |
| `active_resource_bytes` | Total bytes of active resources, counting each resource once |
| `active_fitting_resource_bytes_at_1_MiB` | Active bytes that fit a 1,024 KiB cache |
| `resource_sizes_bytes` | Resource sizes in catalogue order |
| `requests_file`, `resources_file` | Relative input filenames |
| `generator_command` | Command that generated the inputs |
| `reference_files_modified` | Whether instructor reference files were touched (must be `false`) |
| `sequential_repeat_probability` | Sequential-workload parameter; `null` for other kinds |
| `mixed_oversized_interval` | Mixed-workload oversized-resource interval; `null` when unused |

These fields describe the input, not performance results.

### 8.9 `run_all.json`

`d_experiments/run_all.py` writes `run_all.json` in its output directory. It
records `output_dir` (absolute path of the local run), `seeds`,
`drift_seeds`, `scale`, `half_life_override`, `drift_half_life`, the
`stages` list with each stage name and return code, and
`chosen_half_life` / `half_life_used`. It is an orchestration log, not a
committed result table; absolute paths in it are machine-specific.

## 9. Aggregation, dispersion, and fairness conventions

For observations `x_1, ..., x_n`, the arithmetic mean is `sum(x_i) / n`.
Reported dispersion is the sample standard deviation

`s = sqrt(sum((x_i - mean)^2) / (n - 1))`

with denominator `n - 1`, not `n`. For repeated seeds, first compute the
metric within each seed for the same workload/capacity/policy condition, then
report the mean and sample standard deviation of those per-seed values. Do not
pool requests across seeds for the response-time mean, and do not treat a
per-client mean as a substitute for the global request-weighted mean.

For client fairness, Jain's index over non-negative client values `x_i` is

`J = (sum(x_i))^2 / (n * sum(x_i^2))`.

The committed fairness table uses each client's request hit rate as `x_i`,
computes `J` per seed, and averages over seeds. If all `x_i` are zero, the
denominator is zero and the value is undefined (`nan` in CSV, `N/A` in the
report); do not silently replace it with 0 or 1. The worst client is the
client with the largest per-client average response time in that seed; the
reported `worst_client_id` is the client most often worst across seeds, with
lexicographic tie-breaking. The exact implementation is in
`d_experiments/analyze_fairness.py`.
