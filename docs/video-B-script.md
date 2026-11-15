# B segment — 2-minute demonstration script

**Topic:** Input data, metrics/output, and reproducibility  
**Target duration:** about 2 minutes  
**Status:** Prepared script. Record against the integrated branch after the final run command and output paths are confirmed.

## Narration and screen cues

**0:00–0:25 — Input data**

“My part focuses on how the simulator turns input data into reliable,
comparable results. We use two CSV files: a resource catalogue and a request
trace. A resource is identified by its full scheme, host, and path. The
parser validates the input, handles standard CSV quoting, and stably sorts
requests by timestamp. If timestamps tie, the original file order is kept,
so each request receives a deterministic sequence number.”

**Screen:** Show the two reference CSV headers and the resource key fields.
Briefly point to stable sorting and input validation.

**0:25–0:55 — Metrics and output**

“After each request, the engine emits one event, and the metrics accumulator
consumes that event exactly once. We report request hit rate, byte hit rate,
average response time, and origin traffic. Request hit rate counts requests,
while byte hit rate weights each request by the requested object size. We
also report hit rate and average response time for each client. The
ten-column event CSV preserves eviction order and cache insertion order,
along with cache usage, response time, and cumulative counters.”

**Screen:** Show the ten-column output header and one or two event rows.
Highlight bytes versus KiB and the per-client summary.

**0:55–1:25 — Reproducibility**

“For batch experiments, each policy is run from a fresh cache using the
same generated input files for a given workload and capacity. The runner
records the seed, exact capacity in bytes, input hashes, source version,
dependency versions, and run status. The summary and per-client CSV files
can therefore be traced back to their inputs and configuration.”

**Screen:** Show the experiment manifest and the headers of
`summary.csv` and `clients.csv`. Do not present unverified result values.

**1:25–1:50 — Reference validation**

“We also validate the standard policies against the instructor-provided
reference outputs. The validator checks headers, row counts, and fields,
compares numeric values numerically, and reports the exact policy, request,
and field when a mismatch occurs. This confirms the reference behavior
before we interpret the larger experiment results.”

**Screen:** Run `python -m cache_simulator.reference_validation` and show
the FIFO, LRU, and LFU PASS lines. Use the integrated branch.

**1:50–2:00 — Contribution**

“My contribution covers the metrics accumulator, CSV output, reference
validation, data dictionary, and the input-and-metrics material for the
technical report. These pieces make the results consistently defined and
traceable.”

## Recording checklist

- Record only after the integrated branch is available and the team confirms
  the final run commands and output paths.
- Run the full test suite and reference validation before recording.
- Show the exact CSV headers and manifest fields; avoid tiny unreadable text.
- Do not state which policy performs best until D's final four-policy results
  have been checked.
- If CUSTOM/GDSF are shown in the CLI, make clear they are the additional
  policy choices; do not imply they have passed the full experiment unless
  the final batch run confirms it.
