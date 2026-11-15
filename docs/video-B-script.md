# B segment — 2-minute demonstration script

**Topic:** Input parsing, metrics/output, and reference-output comparison  
**Target duration:** about 2 minutes  
**Status:** Draft; record after the relevant PRs are integrated and the team confirms the final demo command.

## Narration and screen cues

**0:00–0:25 — Inputs**

“ My part focuses on how the simulator turns input data into reliable,
comparable results. We start with two CSV files. The resource file describes
each object, including its URL key, size in bytes, and origin latency. The
request file records the timestamp, client, method, and requested resource.
The parser validates the columns and resource references, accepts standard
CSV quoting, and sorts requests stably by timestamp. Equal timestamps keep
their original order, so every request gets a deterministic sequence number.”

**Screen:** Show the headers of `data/reference/resources.csv` and
`data/reference/requests_reference.csv`; briefly point to the parser's
validation and stable ordering.

**0:25–1:05 — Metrics and output**

“After the engine processes each request, it emits one event. The metrics
accumulator consumes each event exactly once. We calculate request hit rate,
byte hit rate, average response time, and origin traffic. These metrics answer
different questions: request hit rate counts requests, while byte hit rate
weights each request by object size. We also calculate hit rate and average
response time separately for each client. The CSV output contains ten fields,
including the result, evictions, cache contents, cache usage, response time,
and cumulative counters.”

**Screen:** Show the ten-column output header and one or two rows. Highlight
that cache usage is in KiB while internal capacity and object sizes are in
bytes; show the per-client summary if available.

**1:05–1:45 — Reference comparison**

“To make sure the implementation is correct, we compare the generated
results against the instructor-provided reference CSVs. The validator checks
the header, row count, and each field. It compares numeric values as numbers,
so harmless differences such as 32 versus 32.0 do not cause false failures.
It also reports the policy, request step, field, expected value, and actual
value when a mismatch occurs.”

**Screen:** Run `python -m cache_simulator.reference_validation` and show
the FIFO, LRU, and LFU PASS lines. Use the final integrated branch when
recording.

**1:45–2:00 — Contribution**

“My contribution was the metrics accumulator, the ten-column CSV output,
the reference-validation support, and the data-dictionary documentation.
Together, these make the simulator's results traceable and ensure that
different policies are evaluated using consistent definitions.”

## Recording checklist

- Use the final integrated project branch, not an outdated stacked branch.
- Run the test and reference-validation commands successfully before recording.
- Keep the instructor-provided reference files unchanged.
- Make the ten output column names readable on screen.
- Do not show experimental CUSTOM/GDSF conclusions until D's final results
  have been verified.
