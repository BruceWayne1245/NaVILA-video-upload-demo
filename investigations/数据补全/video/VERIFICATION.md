# Phase 2 verification — expected vs actual

All 11 clips are sourced from footage that already existed on disk under
`NaVILA-Bench/eval_results/.../videos/output_*.mp4` (produced automatically by
every `round_trip_eval.py` run — this was missed by the initial Phase 0 pass,
which only searched `batch_logs/`, not `eval_results/`). **No new simulator
runs were launched for this video.** Per-step structured data (hint,
arbitration, stop_gate, distance) comes from the sibling
`trajectories/output_*.jsonl` files, one JSON record per control step.

## Fallback substitution: episode 1119 → episode 1256

The spec's matrix specified episode 1119 for Seg 2 (Oracle hint alone,
expected: return fails) and Seg 3 (Oracle hint vs Oracle hint-action, same
episode, expected: hint-only fails / hint-action succeeds).

Checking the real recorded outcome: **episode 1119 under Oracle hint alone
actually returned successfully**, contradicting the spec's expected "fail."
Episode 1119 under Oracle hint-action was never successfully run (VLM server
port conflict, exit_code=98, no video/measurement produced).

The spec provides no listed fallback for this specific cell. Scanning all 93
completed pairs common to both the `pure_oracle_hint_highsuccess100ep_20260811`
and `pure_oracle_hint_action_highsuccess100ep_20260812` batches for episodes
where hint-alone fails and hint-action succeeds (both with real video+logs)
found 23 candidates. **Episode 1256** (batch idx 733) was selected: hint-alone
drifts 12.77 m and fails; hint-action recovers to 0.35 m and succeeds. Neither
value appears elsewhere in the matrix, so it does not collide with any other
segment's episode.

**Segment captions and episode numbers in the spec must be updated: replace
1119 with 1256 in Seg 2 and Seg 3.**

## Expected vs actual, all 11 clips

| Episode | Configuration | Used in | Expected | Actual | Distance (expected → actual) | Video |
|---|---|---|---|---|---|---|
| 1006 | baseline (language-only) | Seg 1, Seg 5 | return fails | return fails ✅ | 21.03 m → 21.03 m (diff 0.00) | present |
| 1006 | online (proposed) | Seg 5 | return succeeds | return succeeds ✅ | 1.98 m → 1.98 m (diff 0.00) | present |
| 1256 *(replaces 1119)* | Oracle hint | Seg 2, Seg 3 (left) | return fails | return fails ✅ | — → 12.77 m | present |
| 1256 *(replaces 1119)* | Oracle hint-action | Seg 3 (right) | return succeeds | return succeeds ✅ | — → 0.35 m | present |
| 33 | Oracle hint-action | Seg 4 (left) | return fails | return fails ✅ | 3.79 m → 3.787 m (diff 0.003) | present |
| 33 | Oracle hint-action-stopgate | Seg 4 (right) | return succeeds | return succeeds ✅ | 1.69 m → 1.69 m (diff 0.00) | present |
| 1378 | Oracle hint-action | Seg 4 insert | return fails | return fails ✅ | 0.20 m → 0.205 m (diff 0.005) | present |
| 428 | online | Seg 5 | return fails; gate withholds ~100% of return steps | return fails ✅; gate withholds **99.5%** (216/217 return-phase steps) — not exactly 100%, flagged | — | present |
| 1439 | online | Seg 5 contrast | return succeeds; gate withholds ~0% of return steps | return succeeds ✅; gate withholds **0.0%** (0/207 return-phase steps) — confirmed exact | — | present |
| 1154 | baseline | Closing | return succeeds | return succeeds ✅ | — | present |
| 1154 | online | Closing | return fails | return fails ✅ | — | present |

**10/11 cells match their spec-predicted outcome outright; the 11th (1119) did
not reproduce and was replaced with 1256, which does.** All values above come
directly from each run's own `measurements/*.json` and `trajectories/*.jsonl`
— never mixed across different runs of the same episode.

## One correction to the spec's own narrative (episode 1378)

The spec describes Seg 4 as "premature termination prevents arrival" and
inserts ep1378 as a second example of the same mechanism (STOP proposed →
vetoed by a human-legible gate). The trajectory data shows this is **not**
what happens in 1378: `terminal_state` is empty for the entire episode — the
VLM never proposes STOP. It ends at 0.205 m simply because the outbound+return
step budget runs out while the robot is still mid-turn. This is a **timeout**,
not a premature-termination-then-veto case. It still supports the spec's
point ("still judged a failure" despite being 20 cm from home) but the
caption should say "runs out of steps while still approaching" rather than
implying a STOP/veto event occurred.

## Segment caption text (for Phase 4)

- **Seg 1** (1006, baseline, ~40 s): "Baseline return: the robot walks 21.03 m
  from a route it has just traversed outbound. No route memory, no hint —
  language instruction alone." Label: language-only baseline.
- **Seg 2** (1256, Oracle hint, ~50 s): "Perfect position information is not
  enough. The hint anchor is correct throughout this return; the policy
  repeatedly disagrees with it. Return fails at 12.77 m." Label: `ground-truth
  pose` (oracle).
- **Seg 3** (1256, Oracle hint | Oracle hint-action, ~50 s): "Constraining the
  action instead of only suggesting it: same episode, same hint. Left: hint
  advisory only, return fails (12.77 m). Right: hint-action arbiter enforces
  the hint when the VLM disagrees, return succeeds (0.35 m)." Label:
  `ground-truth pose` on both sides.
- **Seg 4** (33, Oracle hint-action | Oracle hint-action-stopgate, ~60 s;
  insert 1378): "Premature termination presents as trajectory failure. Left:
  the VLM proposes STOP at 3.79 m from home; nothing blocks it, episode ends,
  judged a failure. Right: the same STOP proposal is vetoed by the stop-gate
  at step 2480 (`decision=vetoed`); execution continues; the episode goes on
  to arrive at 1.69 m. Insert (ep1378): the opposite failure mode — no STOP is
  ever proposed, the step budget simply runs out 20 cm from home." Label:
  `ground-truth pose` on both sides.
- **Seg 5** (1006 baseline|online; then 428; contrast 1439, ~60 s): "The
  online system and its cost. 1006: baseline fails (21.03 m), the proposed
  online system succeeds (1.98 m). ep428: the bearing-reliability gate
  withholds the hint on 99.5% of return steps — hint bar stays grey almost
  the entire return, the arbiter never gets a usable signal, return fails.
  Contrast, ep1439: gate never withholds (0% of steps), hint stays live
  throughout, return succeeds." Label: online configuration (no oracle pose).
- **Closing** (1154, baseline | online, ~20 s): "Regression: baseline
  succeeds here, the proposed system fails here. 4 of 49 episodes regressed
  this way." Label both sides with their configuration.

## Deviation from spec's overlay-camera description

The spec calls for "egocentric RGB as a small picture-in-picture" and
third-person as primary. The source footage instead has them concatenated
side-by-side (egocentric left, third-person-chase right), burned in by
`round_trip_eval.py` itself at capture time — this is the only camera
composition available in the recorded footage (re-recording was avoided since
Phase 0/2 found matching footage already existed with correct outcomes).
Phase 4 should treat this side-by-side layout as the base plate and add the
Phase 3 CSV overlays on top of it, rather than attempting to re-derive a PiP
layout from raw camera streams.

## Phase 4 render notes

Rendered with `code/overlay_lib.py` + `code/render_segments.py` (cv2 overlay
pass, native 10fps, native resolution — writes `_raw/*.mp4`) followed by
`code/compose_final.py` (ffmpeg: real per-segment speed-up, scale/pad to
1920x1080, title cards, concat — writes `segments/*.mp4` and `final.mp4`).

**True source resolution**: source clips are 1024x512 (ego-left +
third-person-right, each 512x512) plus a 110px overlay text panel = 1024x622
for single clips, 2048x622 for side-by-side pairs. The spec's "1080p" is
satisfied at the *output* canvas level only (1920x1080 H.264, scaled up with
letterbox/pillarbox bars) — nobody should read the final file's 1080p tag as
native-resolution footage; it's 10fps, ~512px-per-camera source upscaled.

**Actual speed multipliers burned into each segment** (spec's "8×" was
illustrative, not literal — computed per-piece from native duration ÷ target
duration):

| Piece | Native duration | Target | Multiplier |
|---|---|---|---|
| Seg 1 (1006 baseline) | 143.2s | 40s | 3.6x |
| Seg 2 (1256 hint) | 96.2s | 50s | 1.9x |
| Seg 3 (1256 pair) | 96.2s | 50s | 1.9x |
| Seg 4 main (33 pair) | 58.4s | 35s | 1.7x |
| Seg 4 insert (1378) | 133.2s | 25s | 5.3x |
| Seg 5 part 1 (1006 pair) | 143.2s | 30s | 4.8x |
| Seg 5 part 2 (428) | 69.2s | 15s | 4.6x |
| Seg 5 part 3 (1439) | 49.2s | 15s | 3.3x |
| Closing (1154 pair) | 131.2s | 20s | 6.6x |

**Sync method for side-by-side pairs**: paced by the *longer* side's own
frame timeline (both start at control-step 0 from the same episode); each
frame looks up the nearest-`step` frame on the shorter side and holds that
side's last frame once it runs out. No cropping/trimming was applied to
either side.

**Final assembled duration: 5m 15.6s** (315.6s) — this exceeds the spec's
top-level "3–4 minute" target. The per-segment lengths in the spec's own
Phase 4 table (40/50/50/60/60/20s = 280s) already sum past 4 minutes before
title cards are even added; 6 title cards (mix of 3–5s each, ~23s total) push
it further. This render followed the spec's explicit per-segment lengths
literally rather than the vaguer top-level minute target — if the 3–4 minute
figure is the harder constraint, segments 4 and 5 (currently the longest, at
67.5s and 70.0s) are the ones to cut from, matching the spec's own guidance
that "if length must be cut, take it from segments 1 and 2, not from 4" (so
after 1/2, seg 5's three-part structure is the next place to trim, e.g. by
dropping the 1006 pair recap since seg 1 already establishes the baseline
failure and seg 5 already restates it).

**Two real bugs hit and fixed during rendering**, worth knowing about before
re-running the scripts: (1) OpenCV's Hershey font (`cv2.putText`) cannot
render the CSV's unicode glyphs (`→ · °`) — they printed as `??`; fixed with
an ASCII-substitution pass in `overlay_lib._ascii_safe`. (2) ffmpeg's
`drawtext` filter silently drops any text line containing a literal `%`
(neither `\%` nor `%%` escaping worked reliably) — fixed by spelling out
"percent" instead of using the `%` character in title-card text.

Not yet done (out of scope for this pass): audio (source clips are silent,
final.mp4 has no audio track), and no attempt was made to compress the
~50-word raw baseline instruction text shown in Seg 1/Seg 5's left panel —
it's legible but dense; a shorter paraphrase would read better at 3.6x-6.6x
speed.

## Trimmed cut (`final_trimmed.mp4`, `segments_trimmed/`)

Built by `code/compose_final_trimmed.py`, reusing the same `_raw/*.mp4`
overlaid pieces (no re-render of the cv2 overlay pass). Applies the cut plan
this file already recommended above: shrink Seg 1 (40s->20s) and Seg 2
(50s->30s) per the spec's own "cut from 1 and 2 first" guidance, leave Seg 3
and Seg 4 untouched (spec's most valuable segments), drop Seg 5's ep1006-pair
recap sub-part entirely (Seg 1 already establishes the baseline failure and
Seg 5 already restates it via the ep428/ep1439 online contrast), leave the
mandatory Closing untouched.

**Result: 4m 03s (243.0s)** — 3 seconds over the nominal 4-minute ceiling,
effectively at the spec's "3-4 minute" target. Per-segment durations (with
title cards): seg1=23.0s, seg2=33.0s, seg3=53.0s, seg4=67.5s, seg5=37.5s (was
94.5s in the untrimmed cut, now only the ep428/ep1439 pieces), closing=29.0s.
Speed multipliers changed accordingly (seg1 7.2x, seg2 3.2x; seg3/seg4/closing
unchanged from the untrimmed cut since their target lengths didn't move).

Spot-checked a Seg 1 content frame at the new 7.2x speed: overlay text
(`language-only baseline` label, `7.2x speed` badge, `(no route hint,
language-only)` config line, `VLM: forward`, `d = 12.44 m` + radius indicator)
all render correctly and stay legible at the higher speed.

Both cuts are kept side by side for comparison — `final.mp4`/`segments/`
(untrimmed, 5m16s, follows the spec's literal per-segment lengths) and
`final_trimmed.mp4`/`segments_trimmed/` (4m03s, follows the spec's top-level
minute target). Neither overwrites the other.
