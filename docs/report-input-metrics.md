# Report material — Inputs, metrics, and experiment method

## 1. Input data and event processing

The simulator reads two UTF-8 CSV inputs. The resource catalogue contains
eight fields: `scheme`, `host`, `path`, `status_code`, `content_type`,
`size_bytes`, `origin_latency_ms`, and `cache_control`. A resource is
identified by the complete `(scheme, host, path)` key, rather than by its
path alone. The request trace contains six fields: `timestamp`,
`client_id`, `method`, `scheme`, `host`, and `path`. Each request
must be a GET for a resource in the catalogue.

The parser uses standard CSV handling, so quoted fields may contain commas.
Requests are stably sorted by timestamp; requests with equal timestamps
retain their original file order. The parser then assigns a one-based
sequence number, which provides deterministic ordering for policy updates.
Malformed rows, duplicate resource keys, unknown resource references,
invalid sizes/latencies, and invalid timestamps are rejected with contextual
validation errors.

## 2. Cache simulation and output

The cache is shared across clients and starts empty for each independent
run. Capacity and object sizes are represented in bytes; displayed cache
usage in KiB is calculated as bytes / 1,024. A hit uses the configured hit
latency and contributes no origin traffic. A miss uses the resource's origin
latency and adds the full object size to origin traffic. A resource larger
than total cache capacity is fetched but bypasses admission and does not evict
resident objects.

The per-request output contains ten fields: step, resource ID, client ID,
HIT/MISS result, eviction order, resident cache contents in insertion order,
cache usage in KiB, response time in milliseconds, cumulative origin bytes,
and cumulative hits. The metrics accumulator consumes each event once; the
serializer reads the resulting snapshots and does not update counters again.

## 3. Performance metrics

For N requests, H hits, requested resource size s_i, hit indicator h_i, and
response time t_i, the project reports:

- **Request hit rate:** H / N.
- **Byte hit rate:** sum(h_i × s_i) / sum(s_i).
- **Average response time:** sum(t_i) / N.
- **Origin traffic:** sum(s_i for every miss).

Repeated requests count each time in the byte denominator and, when they
hit, in the hit-byte numerator. Oversized-resource misses also contribute
their full size to request bytes and origin traffic. The global average
response time is request-weighted; it is not calculated by averaging
per-client averages. Per-client hit rate and average response time use that
client's own request count as the denominator. Undefined ratios are reported
as N/A in the report rather than dividing by zero.

For fairness analysis, client-level performance must be shown together with
each client's request count. A difference in client hit rates should not be
interpreted without considering the amount and pattern of work assigned to
each client. The exact fairness index, worst-client definition, and final
machine-readable fields will follow the team's agreed implementation and
verified experiment output.

## 4. Experiment reproducibility

The current batch-runner scaffold generates repeated, sequential, and mixed
workloads at small, medium, and large scales. It records the random seed,
cache capacity in exact bytes, hit latency, selected policies and policy
parameters, input-file hashes, source hash or Git revision when available,
dependency versions, and a per-run status manifest. Every policy condition
starts from a fresh cache and uses the same generated input pair for a given
workload/scale condition.

The current scaffold writes an overall `summary.csv`, a `clients.csv`,
per-run event CSVs, input metadata JSON, and `manifest.json`. The overall
mean response time is computed from total response time divided by total
request count. The manifest and input hashes allow each result to be traced
to the exact input files and run configuration.

## 5. Reference validation

The reference validator compares parsed CSV headers, row counts, and fields.
Text and integer values are checked exactly; numeric fields are compared
numerically, so equivalent representations such as 32 and 32.0 do not cause
false mismatches. Valid CSV quoting and CRLF/LF differences are ignored.

On the instructor's reference trace, with a 102,400-byte cache and 5 ms hit
latency, FIFO, LRU, and LFU produce 3, 3, and 4 hits respectively. Their
average response times are 95.33 ms, 92.33 ms, and 84.33 ms. These are
reference-validation results, not conclusions about the generated workloads
or the CUSTOM/GDSF policies.

*Final experimental comparisons, fairness results, and conclusions will be
inserted only after the integrated four-policy experiment has completed and
the result files have been verified.*
