# C segment — 2-minute demonstration script

**Topic:** Standard replacement policies and one-command reference validation
**Slot in the 10-minute video:** 4:00–6:00
**Target duration:** 2:00 (record 1:55–2:05)
**Status:** Prepared script. Record against the integrated branch after the
final run command and output paths are confirmed (see the note at the end).

Pacing target: about **100 words per minute**, 202 narration words in total.
Screen actions (typing the command, switching slides) are covered by the
non-speaking gaps in each block. See the pacing check in section 2.

## 1. Narration and screen cues

**0:00–0:30 — The three standard policies** (45 words)

"This part covers the three standard policies and how we prove they are
correct. The engine owns the cache, the byte accounting and the
oversized-object rule. A policy answers one question only: which resident
object to evict next. All three policies share that one engine."

**Screen:** a three-column slide, one row per policy, with the rule, what a hit
updates, and the tie-break. Keep an "output is insertion order" label visible.

**0:30–1:05 — The rules** (67 words)

"FIFO evicts whatever entered the cache earliest, and a hit does not change
that order. LRU evicts whatever was accessed longest ago, so every hit
refreshes its position. LFU evicts the object with the fewest accesses since
insertion; ties go to the least recently accessed one, and a re-inserted object
starts again at one. In the output, the cache-contents column is always
insertion order, never eviction priority."

**Screen:** the same slide; highlight one row at a time while it is described.

**1:05–1:35 — One-command validation, run live** (48 words)

"Correctness is not an opinion. One command runs all three policies on the
reference trace, from an empty cache, at exactly 102,400 bytes and 5
milliseconds, and compares every field with the instructor's expected files. A
mismatch names the policy, the request and the field, then exits non-zero."

**Screen:** terminal, typed on camera:

```
python -m cache_simulator.reference_validation
```

Let the three PASS lines appear (FIFO, LRU, LFU), then show the exit code:

```
echo $?        # Linux/macOS;  echo %ERRORLEVEL%  on Windows
```

**1:35–1:52 — What the numbers say** (31 words)

"FIFO and LRU hit three times out of fifteen; LFU hits four. Average response
time falls from 95.33 to 92.33 to 84.33 milliseconds, and origin traffic from
421,888 to 370,688 bytes."

**Screen:** results table beside the terminal: policy, hits, request hit rate,
byte hit rate, origin traffic, average response time.

**1:52–2:00 — Personal contribution** (11 words)

"My contribution was these semantics, their tests, and the one-command
comparator."

**Screen:** repository tree: `data/reference/` (inputs unchanged), the
comparator module, and the comparator's own tests.

## 2. Pacing check

| Block | Time | Words | Words per minute |
| --- | --- | ---: | ---: |
| 1 Policies overview | 0:00–0:30 | 45 | 90 |
| 2 The three rules | 0:30–1:05 | 67 | 115 |
| 3 Live validation | 1:05–1:35 | 48 | 96 (part of the block is typing, not speech) |
| 4 The numbers | 1:35–1:52 | 31 | 109 |
| 5 Contribution | 1:52–2:00 | 11 | 83 |
| **Total** | **2:00** | **202** | **101** |

If the recording runs long, cut block 2's last sentence (insertion order) first,
then block 1's last sentence; do not cut block 3's failure description, which is
the point of the segment.

## 3. Recording checklist

- Record at 1920×1080 (or 1280×720), 30 fps, MP4/H.264; one continuous take is
  fine, the editor will cut the pauses.
- Zoom the terminal and the table so they are readable at 1080p; no personal
  paths, no unverified numbers on screen.
- If the validator output changes before recording, update the numbers in this
  script and in the report section — do not read the older values.
- Deliver `clips/C_standard_policies_2min.mp4` plus one line for the
  contribution slide, e.g. "C — standard policies, reference validation,
  mixed-workload evidence, clean-environment reproduction, video editing".
- Upload/hand-off by 11/30 so editing can finish on 12/01.

## 4. Note on the demo

The command and the PASS lines are the only required demo content; the runner
documents its own failure format, so do not fake a failing run on camera. If a
live demo is risky on the recording machine, record the successful run and
paste the validator's failure example as a still image instead.
