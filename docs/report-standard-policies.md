# Report material — Standard policies and reference validation

Section 3 of the technical report (#15). Owner: C. Budget: about 0.25 page.
Every number below comes from the repository's own reference files and the
command in Section 2; nothing here depends on the generated experiment data.

## 1. Replacement rules

FIFO evicts the object that entered the cache earliest, and a hit does not
change insertion order. LRU evicts the object with the oldest last access, so
every hit refreshes its position. LFU evicts the resident with the fewest
accesses since it was inserted; ties go to the least recently accessed object,
and an object that is evicted and re-inserted restarts at one. The three
policies choose a victim and nothing else: the shared engine owns residency,
byte accounting, oversized-object bypass and repeated eviction, and the
cache-contents column of the output is always insertion order, never eviction
priority.

## 2. One-command validation

`python -m cache_simulator.reference_validation` runs FIFO, LRU and LFU from an
empty cache at the required 102,400 B capacity and 5 ms hit latency, then
compares all ten fields of all 15 requests with the three instructor-provided
expected CSVs, together with the summary and per-client values. A mismatch
reports the policy, request number, field, expected value and actual value and
exits non-zero; a fully matching run exits 0. The comparison is semantic, so
legal CSV quoting, line endings and numeric formatting (`32` versus `32.0`) do
not produce false failures, while a changed hit, eviction order or cumulative
value does.

## 3. Reference results

| Policy | Hits / requests | Request hit rate | Byte hit rate | Origin traffic | Average response time |
| --- | ---: | ---: | ---: | ---: | ---: |
| FIFO | 3 / 15 | 20.00% | 17.60% | 421,888 B | 95.33 ms |
| LRU | 3 / 15 | 20.00% | 21.20% | 403,456 B | 92.33 ms |
| LFU | 4 / 15 | 26.67% | 27.60% | 370,688 B | 84.33 ms |

## 4. What these numbers establish

Because all three policies agree with the reference trace field by field, every
later comparison rests on a verified baseline instead of on untested code. The
same trace already separates the policies: LFU keeps the small, repeatedly
requested objects, gains one extra hit and therefore lowers origin traffic to
370,688 B and average response time to 84.33 ms. FIFO's byte hit rate (17.60%)
is below its request hit rate (20.00%) because the objects it does hit are small
relative to the 512,000 requested bytes, while the requests it misses are the
large ones; LRU falls between the two. At 100 KiB and 15 requests these
differences are too small to rank the policies, so they are used here to prove
semantic correctness, and the ranking argument is made on the generated
workloads in Section 6.

Supporting detail, including the eviction order at each step and two
hand-computed sequences that the custom policy can reuse, is in
[standard-policy-validation.md](standard-policy-validation.md).
