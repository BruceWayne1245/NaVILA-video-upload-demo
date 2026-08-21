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

## v2 revision (`final_v2.mp4`, `segments_v2/`, 2026-08-21)

Three fixes requested by the user after watching the original cuts:

1. **Dropped Seg 1 and Seg 2** (ep1006 baseline alone, ep1256 oracle-hint
   alone). A single failing episode with nothing to compare against reads as
   unclear on its own; the video now opens on the old Seg 3 (renumbered to
   Segment 1). Segment numbering in title cards was shifted accordingly:
   old Seg3→"Segment 1", Seg4→"Segment 2", Seg5→"Segment 3", Closing
   unchanged.
2. **Fixed the canvas fill.** The original pair segments concatenated two
   full 1024-wide (ego+third-person) panels into a 2048-wide frame, which
   padded to huge black bars top/bottom once fit into 1920x1080 (aspect
   3.29:1 vs the 16:9 canvas). `render_segments_v2.py` now crops each side of
   a pair to third-person-only (512 wide) before pairing, bringing the
   combined frame back to 1024 wide — the same aspect as a single-clip
   segment. `compose_final_v2.py` also switched the ffmpeg scale/pad step to
   scale-up-then-crop (`force_original_aspect_ratio=increase` +
   `crop=1920:1080:0:in_h-1080`), filling the canvas completely with zero
   black bars, cropping only off the top of the frame so the bottom overlay
   text panel is never clipped.
3. **Added pause + highlight at divergence moments.** The four pair segments
   (ep1256 hint/hint-action, ep33 hint-action/stopgate, ep1006
   baseline/online, ep1154 closing) now freeze both sides for ~1.5s with a
   growing yellow highlight oval drawn over whichever side's overlay text row
   just changed, at each detected divergence: an arbitration override firing,
   or a terminal state (STOP proposed → vetoed / executed) newly appearing.
   Detection and pause insertion happen in `overlay_lib.render_pair_side_by_side`
   (see its docstring); events are found on the *resolved* per-frame sequence
   actually shown to the viewer, not on raw CSV steps, since the two sides'
   CSVs sit on only-approximately-aligned step grids and mapping an event
   step from one side onto the other can land one row short of where its own
   text actually changes (hit this bug once during development on ep33's
   STOP/veto moment — the second pause fired but drew no circle until fixed).
   Each piece's ffmpeg speed-up factor is intentionally left unchanged from
   the original NATIVE/TARGET values, decoupled from the fact that the raw
   file is now longer — this is what makes each freeze land at ~1.5 real
   seconds regardless of the segment's own speed multiplier (1.7x-6.6x); see
   `render_segments_v2.py`'s module docstring for the derivation. Single-clip
   segments (ep1378 insert, ep428, ep1439) are unchanged — there is no
   left/right divergence to flag on a clip with only one side.

The circle is drawn over the overlay text row that changed (arbitration or
terminal-state line), not over the robot's on-screen position — the frame
overlay data doesn't track the robot's screen-space pixel coordinates, and
guessing at that would risk pointing at the wrong spot; circling the exact,
known text location keeps the highlight honest.

**Result: 3m 56s (236.1s)** — shorter than either prior cut, within the
spec's original 3-4 minute target without needing any explicit length
trimming (dropping Seg 1/2 alone did it). Per-segment durations (with title
cards): seg3(now "Segment 1")=59.0s, seg4("Segment 2")=70.5s,
seg5("Segment 3")=73.0s, closing=33.5s — each ~1.5-4.5s longer than the v1
cut's own TARGET value for that piece, accounted for entirely by the new
pause events (1 pause on seg4, 1 on seg5, 3 on closing, 4 on seg3 — capped
per-segment via `max_events` in `render_segments_v2.py`).

`final.mp4`/`segments/` and `final_trimmed.mp4`/`segments_trimmed/` are left
untouched on disk and in git history — `final_v2.mp4`/`segments_v2/` is a
third, separate cut, not a replacement.

### v2 follow-up (same `final_v2.mp4`/`segments_v2/`, later same day)

Three more requests after watching the first v2 cut:

1. **Captions on the pause events.** Each freeze now also shows a short,
   data-driven one-liner in a new band below the data panel (e.g. "Stop-gate
   vetoes the STOP -- the robot keeps moving", "VLM wanted 'turn right' --
   arbiter executes 'right' instead"). Generated by `overlay_lib.event_caption`
   directly from the same logged fields the panel already shows (arbitration
   text, terminal_state, distance) — not hand-authored per segment, so it
   stays accurate if the underlying run ever changes. Text is measured with
   `cv2.getTextSize` and binary-searched down to fit the panel width exactly
   (a fixed chars-per-width budget first tried here overflowed the narrower
   512px pair panels — Hershey glyph widths vary too much for that to be
   reliable).
2. **Dropped the ep1378 insert** from Segment 2 (old Seg 4) entirely — it
   demonstrated a second, different failure mode (step-budget timeout, not a
   veto) that diluted the segment's one point (STOP proposed → executed vs
   vetoed) rather than reinforcing it.
3. **Two closing figure cards**, appended after the results text card:
   `arrival_vs_success` (the full Oracle-ladder + online results, bar form —
   directly extends the results card's numbers) and
   `failure_distance_distribution` (box+strip plot of how far short each
   configuration's failures land — adds a distribution the results card's
   single percentages can't show). Sourced from
   `final_data2/figures/*.pdf`, rasterized at 400dpi to
   `video/figures_raster/*.png` (the repo's checked-in `*_preview.png` files
   are lower-res, not print-quality) via `pdftoppm`. Rendered on a white
   card (matching the figure's own white background, distinct from the black
   title cards) by the new `image_card()` in `compose_final_v2.py`.

**Result: 3m 38s (217.6s)**, shorter than the first v2 pass (dropping the
ep1378 insert outweighed the ~1.5s pauses and the two 5s figure cards added
elsewhere). Segment durations (with title/figure cards): seg3="Segment
1"=59.0s, seg4="Segment 2"=42.0s (was 70.5s with the insert), seg5="Segment
3"=73.0s, closing=43.5s (was 33.5s, +10s for the two figure cards).

### v2 second follow-up: mini-map + direction arrows (same day, same files)

Two more requests:

1. **Top-down mini-map**, top-left corner of every segment (all 4 pairs plus
   the 2 remaining singles, ep428/ep1439), trailing the robot's real
   trajectory as the episode plays (blue = outbound, orange/red = return,
   red dot = current position). Built by reusing the exact USD-mesh
   occupancy extraction from `final_data2/code/plot_figure2_hint_trajectory_effect_20260818.py`
   (`scene_world_triangles`/`triangle_is_floor`/`build_occupancy`), factored
   into a new offline script `code/build_topdown_maps.py` — needs `pxr`
   (USD), only available in the system miniconda `base` env, not the
   `vlnce-isaac` env the rest of the render pipeline uses. Run it first:
   `/home/teambruce/miniconda3/bin/python build_topdown_maps.py`, writing
   `video/topdown_maps/ep<N>_{occupancy.png,meta.json}` (gitignored,
   regenerate from source — same convention as `_raw/`/`figures_raster/`;
   takes ~7s total for all 6 episodes, no GPU/Isaac Sim needed). For a
   paired episode (e.g. ep1256 hint vs hint-action) both sides render onto
   an *identical* background map — crop bounds are the union of both
   configs' trajectories — for a fair side-by-side comparison; each side
   still gets its own `Minimap` instance so the two trails accumulate
   independently. `overlay_lib.Minimap` draws the trail incrementally onto a
   persistent canvas (one new line segment per frame) rather than replotting
   the whole path every frame.

   **Real bug hit and fixed**: the map was placed too close to the top edge
   (y=34) and got up to 39% cropped off in the final 1920x1080 output —
   `compose_final_v2.py`'s scale-up+crop (added in the first v2 pass to kill
   the black bars) crops up to 92px off the top of a paired piece's frame
   (the tallest case: camera + data panel + caption band). Fixed by moving
   the mini-map's default placement to y=100, clearing the worst case with
   margin — verified by computing the exact crop math for both frame heights
   (668px pairs / 622px singles) and re-checking extracted frames from the
   final composed output, not just the pre-crop raw render.

2. **Direction arrows** during override-event pauses, when the hint's own
   bearing and the VLM's proposed action genuinely disagree (>=12 degrees
   apart — many overrides share the same coarse direction, the arbiter is
   substituting a more precise turn rather than reversing the robot, and
   arrows for near-identical angles would just clutter the frame). Per user
   direction (2026-08-21): the hint's bearing is the "correct" reference
   direction, the VLM's own proposal is what it chose instead. Green arrow =
   hint bearing, red arrow = VLM's proposal, both drawn from the bottom of
   the camera region (0 deg = straight up/away from the chase camera).
   Verified correct by measuring the actual rendered arrow pixel spans on a
   frame where hint=137 deg (right/behind) vs VLM=45 deg (right/ahead) — both
   arrows landed within 1 degree of their intended angle.

Frame counts and segment durations are unchanged from the previous pass
(217.6s total) — both features are pure overlay drawing, no new pause events
or timing changes.
