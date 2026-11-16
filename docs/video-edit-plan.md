# Video editing plan — 5-person, 10-minute demonstration (#16)

Owner: C (editing). Scripts due 11/26, recording 11/30, editing 12/01, upload
12/02, link handed to #17 before the internal final check.

This file is the editing contract: what each person delivers, in which format,
and in which order the pieces are assembled. It does not change anyone's
content — each speaker owns their own two minutes.

## 1. Structure and timing

| Time | Speaker | Content | Source clip |
| --- | --- | --- | --- |
| 0:00–2:00 | A | Project overview, engine and command-line design, live run on the reference trace | `clips/A_overview_2min.mp4` |
| 2:00–4:00 | B | Input parsing, metrics and output, comparison with the reference output | `clips/B_inputs_metrics_2min.mp4` |
| 4:00–6:00 | C | Standard policies and the one-command validation demonstration | `clips/C_standard_policies_2min.mp4` |
| 6:00–8:00 | D | Custom policy design, comparison with FIFO/LRU/LFU, the trade-off it introduces | `clips/D_custom_policy_2min.mp4` |
| 8:00–10:00 | E | Workloads and experiment framework, one key experiment finding | `clips/E_workloads_2min.mp4` |

Total 10:00 for five speakers at 2:00 each, which is the course requirement for
a five-person group. Every speaker must state their own contribution inside
their segment; no separate credits-only segment is added, because that would
push the total past ten minutes.

Scripts already prepared in the repository: `docs/video-B-script.md` (B, PR #25)
and `docs/video-C-script.md` (this PR). A, D and E add their own files in the
same directory so the editor can cut against the intended wording.

## 2. Delivery requirements for each clip

- Length 1:55–2:05. Anything longer is cut by the editor, so keep the most
  important sentence in the first 1:50.
- Video: MP4/H.264, 1280×720 or 1920×1080, 30 fps, landscape. Phone recordings
  are acceptable if they are landscape and the screen is readable.
- Audio: single track, no music, no clipping. Record in a quiet room; the
  editor normalizes loudness to about −16 LUFS and will ask for a re-record
  only if speech is unintelligible.
- Screen content: terminal font large enough to read at 1080p, no personal
  absolute paths, no unverified numbers, no windows with private information.
- Camera presence is not required by the course; slides plus voice are fine.
- Deliver by 11/30 through the agreed channel (check the shared folder the team
  settles on), not as a chat attachment.

## 3. Editing sequence (12/01)

1. Ingest all five clips, label them, check length and audio levels.
2. Build the timeline in the fixed order above; add a 2-second title card,
   then straight cuts between segments.
3. Add lower-third for each speaker: name, and their contribution in one line.
4. Add chapter markers or a short agenda card at 0:00 so a viewer can jump to
   2:00 / 4:00 / 6:00 / 8:00.
5. Check that the numbers spoken on camera match the report and `results/`:
   the reference values (FIFO 3 hits, LRU 3, LFU 4; 95.33 / 92.33 / 84.33 ms)
   and any custom-policy result quoted by D or E.
6. Trim to exactly 10:00 or slightly under; verify total duration, not the sum
   of the raw clips.
7. Audio pass: consistent loudness, no clicks, no long silences over 1.5 s.
8. Export one file at 1080p and one at 720p, keep the project file and the
   per-segment clips until submission is confirmed.

## 4. Upload and handover (12/02)

- Upload to YouTube as **Unlisted** (not Private, not Public).
- Title: course section + team + "cache simulator demonstration";
  description: five names with their contribution lines and the GitHub URL.
- Open the link in a private/incognito window with no logged-in account and
  confirm it plays and is not age-restricted or blocked.
- Post the link in #16 and hand it to #17 for submission; record the upload
  date, duration and the incognito check result in #16.

## 5. Open items for the team to confirm

- Editor: proposed C (this plan). Confirm in #16.
- Final submitter and reviewer for #17: proposed A submits, B reviews.
- Report editor for #15: proposed B.
- Whether everyone records their own screen, or the shared demo computer is
  used for A and C so the terminal looks the same in both segments.
- Whether the edited video is also archived in the submission ZIP (the course
  asks for the link; archiving the file is optional and adds file size).
