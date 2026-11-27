# B — Two-minute video segment (#16)

Suggested three slides; coordinate final sequence with C. Read aloud and time before recording.

## Slide 1 — Input processing (0:00–0:35)
Visual: resources.csv + requests.csv -> parser -> shared cache. Show scheme/host/path and timestamp/client ID.

“My contribution focuses on input processing, performance metrics, output, and validation. The simulator reads two CSV files: a resource catalogue containing object sizes and origin latencies, and a request trace containing timestamps and client IDs. Resources are identified by scheme, host, and path together. The parser validates the data, rejects unknown resources and malformed rows, and sorts requests by timestamp while preserving the order of ties. This ensures each replacement policy receives the same deterministic input.”

## Slide 2 — Metrics and output (0:35–1:15)
Visual: four metrics and a terminal screenshot. Demo command:
```sh
python -m cache_simulator --resources data/reference/resources.csv --requests data/reference/requests_reference.csv --capacity 102400 --hit-latency 5 --policy LFU
```
“Each cache event contributes exactly once to our statistics. We measure request hit rate, byte hit rate, average response time, and total origin traffic. A hit takes five milliseconds in our experiments, while a miss uses the object's origin latency and transfers its full size. The CSV output records each request, eviction order, cache usage, response time, and cumulative counters. For example, the instructor's reference LFU trace has four hits out of fifteen requests and an average response time of 84.33 milliseconds.”

## Slide 3 — Validation and fairness (1:15–2:00)
Visual: mixed 512 KiB CUSTOM vs LRU; 73.97 vs 81.78 ms, media +21.32 ms, Jain 0.8766 vs 0.9507.

“I also checked the consistency of our experiment tables and reviewed the fairness calculations. At 512 KiB on the mixed workload, CUSTOM reduces average latency from 81.78 to 73.97 milliseconds compared with LRU. However, the media client's response time increases by 21.32 milliseconds, while the byte hit rate falls and origin traffic rises. The Jain index also decreases, indicating less equal client hit rates. This shows why a higher request hit rate does not necessarily mean lower bandwidth consumption or better performance for every client. Our evaluation therefore reports both global and per-client metrics.”

Do not state that a fresh raw-event replay passed unless it actually has. Numbers: data/results/main/main_table.csv, fairness.csv, per_client.csv. Reference: data/reference/reference_trace_answer_key.md.
