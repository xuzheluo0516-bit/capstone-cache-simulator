# Repository guidance

This repository implements the shared web cache simulator described in README.md.
The language and build tooling have not been chosen yet; follow the actual project
configuration when it is added. Do not invent build or test commands.

## Code Review Rules

Report actionable defects introduced by the pull request. Explain the triggering
input, affected behavior, and consequence; anchor each finding to the smallest
relevant changed lines. Prefer Chinese explanations while retaining code identifiers.
Use README.md and data/reference/ as the repository's current specification. Do not
flag missing future milestones or optional HTTP features as regressions.

### Cache behavior
- Flag changes that break the documented standard policies: FIFO hits preserve
  insertion order; LRU tracks last access; LFU counts accesses since insertion,
  breaks ties by least recent access, and resets frequency on reinsertion.
  Evict repeatedly until a cacheable resource fits. Oversized resources must be
  fetched from origin without admission or evicting existing entries.
- This is an offline simulation with an initially empty shared cache. All requests
  are cacheable GETs, resources do not change, and expiry/Cache-Control are ignored
  for the course's core simulation. Do not require production HTTP semantics.

### Metrics and reference compatibility
- Check byte-based capacity and accounting, including 100 KiB = 102400 bytes.
  Hits use the configured hit latency (5 ms for the reference trace), misses use
  the resource's origin latency and add its full size to origin traffic.
  Distinguish request hit rate from byte hit rate, and preserve per-client metrics.
- For changes to parsing, policies, or metrics, check against the existing reference
  inputs and expected FIFO/LRU/LFU outputs when runnable. Resource identity is
  (scheme, host, path); CSV parsing must handle quoted commas. Reference cache
  contents are displayed in insertion order, independently of eviction priority.
  Describe a concrete mismatch; never claim a test passed unless it was run.

### Experiment validity
- Flag comparisons that give strategies different workloads, capacities, initial
  states, or latency assumptions, or unintentionally reuse mutable cache state
  across runs. Seed stochastic workloads when reproducibility is required.
  A custom policy need not beat every baseline; assess it against its stated goal.
