# Report material — Section 2: Inputs and metrics

## Inputs and event processing

The simulator reads two UTF-8 CSV files. The resource catalogue has eight
columns: `scheme`, `host`, `path`, `status_code`, `content_type`,
`size_bytes`, `origin_latency_ms`, and `cache_control`. A resource is
identified by the complete `(scheme, host, path)` key. The request trace has
six columns: `timestamp`, `client_id`, `method`, `scheme`, `host`,
and `path`. Requests must be GET requests referencing known resources.
They are stably sorted by timestamp; original order is preserved for ties,
and each request receives a one-based sequence number. Standard CSV parsing
handles quoted fields, including commas.

## Performance metrics

For N requests, H hits, resource size s_i, hit indicator h_i, and response
time t_i, we report:

- **Request hit rate:** H / N.
- **Byte hit rate:** sum(h_i × s_i) / sum(s_i).
- **Average response time:** sum(t_i) / N.
- **Origin traffic:** sum(s_i for every miss).

Repeated requests are counted each time. A hit contributes its resource size
to hit bytes; a miss contributes its full size to origin traffic. Global
average response time is calculated over requests, not by averaging client
averages. Per-client hit rate and average response time use that client's own
request count as the denominator. Undefined ratios are reported as N/A rather
than dividing by zero.

## Output and validation

Each request produces a ten-column CSV row containing the request step,
resource/client IDs, HIT/MISS result, evictions, cache contents in insertion
order, cache usage in KiB, response time, cumulative origin bytes, and
cumulative hits. Capacity and object sizes are stored in bytes; KiB is
calculated using 1 KiB = 1,024 bytes. The serializer reads metric snapshots
and does not count events again.

The reference validator compares parsed CSV headers, row counts, and fields.
It checks text and integer values exactly, compares numeric values
numerically, and ignores valid quoting and line-ending differences. On the
reference trace (102,400-byte capacity and 5 ms hit latency), FIFO, LRU, and
LFU produce 3, 3, and 4 hits respectively; their average response times are
95.33 ms, 92.33 ms, and 84.33 ms.

*This section describes the reference-trace validation only. Experimental
results and conclusions for CUSTOM/GDSF will be added from the final,
verified experiment outputs, not inferred from the reference trace.*
