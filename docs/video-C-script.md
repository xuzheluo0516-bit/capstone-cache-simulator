# C segment — 2-minute demonstration script

**Topic:** Standard replacement policies and one-command reference validation
**Slot in the 10-minute video:** 4:00–6:00
**Target duration:** 2:00 (record 1:55–2:05)
**Status:** Prepared script. Record against the integrated branch after the
final run command and output paths are confirmed (see the note at the end).

## Narration and screen cues

**0:00–0:25 — The three standard policies**

"This part covers the three standard replacement policies and how we prove that
they are correct. All three policies share one engine: the engine owns the
cache contents, the byte accounting and the oversized-object rule, and a policy
only answers one question — which resident object should be evicted next.

FIFO evicts whatever entered the cache earliest, and a hit does not change that
order. LRU evicts whatever was accessed longest ago, so every hit refreshes its
position. LFU evicts the object with the fewest accesses since it was inserted;
when two objects tie, the least recently accessed one goes first, and an object
that is re-inserted starts its count again from one."

**Screen:** A three-column slide, one row per policy: rule, what a hit updates,
tie-break. Keep the cache-contents column visible to show that the output is
always insertion order, not eviction priority.

**0:25–0:45 — One-command validation, run live**

"Correctness is not an opinion here. One command runs all three policies on the
instructor's reference trace, from an empty cache, at exactly 102,400 bytes and
5 milliseconds, and compares the output field by field with the three expected
CSV files."

**Screen:** Terminal, typing the command:

```
python -m cache_simulator.reference_validation
```

Let the three PASS lines appear (FIFO, LRU, LFU), then show the exit code:

```
echo $?        # 0 on Linux/macOS; use  echo %ERRORLEVEL%  on Windows
```

"The validator also checks the summary and the per-client numbers, and if
anything were wrong it would name the policy, the request number, the field and
both values, and exit non-zero — so this is a gate, not a printed claim."

**0:45–1:15 (while the run stays on screen) — the numbers**

"On this trace FIFO and LRU both hit three times out of fifteen, and LFU hits
four times. Average response time falls from 95.33 milliseconds for FIFO to
92.33 for LRU and 84.33 for LFU, and origin traffic falls from 421,888 bytes to
370,688 bytes. FIFO's byte hit rate is lower than its request hit rate because
the objects it manages to keep are the small ones."

**Screen:** Results table on screen next to the terminal output: policy, hits,
request hit rate, byte hit rate, origin traffic, average response time.

**1:05–1:30 — Why this matters for the comparison**

"Three things follow. First, the two later stages — the custom policy and the
batch experiments — are compared against a baseline that is verified, not
assumed. Second, the same command is the regression test: any change to the
engine, the metrics or a policy must leave it passing. Third, the differences
at 100 kilobytes and fifteen requests are deliberately too small to rank
policies, so the ranking argument is made on the generated workloads instead."

**Screen:** Switch to the repository tree: `data/reference/` (inputs never
modified), `src/cache_simulator/reference_validation.py` (the comparator), and
`tests/` (the comparator's own tests, including deliberately corrupted
expected files that must be detected).

**1:30–2:00 — Personal contribution and handoff**

"My contribution in this milestone was the standard-policy side of this gate:
the policy semantics and their tests, and the comparator that turns the
reference trace into a single pass/fail command, including the tests that
corrupt a hit, an eviction order and a cumulative value to make sure the
comparator actually catches them. My next steps are the review of the custom
policy, the evidence that the mixed workload really causes cache competition,
and the clean-environment reproduction before the final internal check. That
is where the custom policy comparison picks up."

## Recording checklist

- Record at 1920×1080 (or 1280×720), 30 fps, MP4/H.264; one continuous take is
  fine, the editor will cut the pauses.
- Zoom the terminal and the table so they are readable at 1080p; no personal
  paths, timestamps of today, or unverified numbers on screen.
- If the validator output changes before recording, update the numbers in this
  script and in the report section — do not read the older values.
- Deliver `clips/C_standard_policies_2min.mp4` plus one line for the
  contribution slide, e.g. "C — standard policies, reference validation,
  mixed-workload evidence, clean-environment reproduction, video editing".
- Upload/hand-off by 11/30 so editing can finish on 12/01.

## Note on the demo

The command and the PASS lines are the only required demo content; the runner
documents its own failure format, so do not fake a failing run on camera. If a
live demo is risky on the recording machine, record the successful run and
paste the validator's failure example as a still image instead.
