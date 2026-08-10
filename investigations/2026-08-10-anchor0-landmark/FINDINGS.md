# Anchor0-landmark stop-gate idea: root cause of the silent 08-09 batch, fix, and a persistent-rejection finding (2026-08-10)

## Origin

User's idea (2026-08-09, same session as
[LIVE_SHADOW_SMOKE_TEST_20260809.md](../2026-08-08-anchor-v3/LIVE_SHADOW_SMOKE_TEST_20260809.md)):
during OUTBOUND, continuously ICP-match the robot's own local map against
anchor 0's (home's) point cloud; the moment the estimated distance crosses
`<=3m`, drop a one-off "landmark" descriptor at the robot's current pose
(never inserted into `route_agent.anchors`, never touches real decisions).
During RETURN, every relocalization attempt additionally tries to
re-recognize this landmark; recognizing it is meant to signal re-entry into
the stop radius. Motivation: sidesteps the anchor-0-never-labeled-in-training
gap found for the unrelated Anchor V3 Transformer model in
`LIVE_SHADOW_SMOKE_TEST_20260809.md`, by using a real captured descriptor
instead of a learned model that has never seen anchor 0.

Implemented same-day as `--anchor0_landmark_shadow` (default off) in Route
2's own reference copy of `round_trip_eval.py`
(`navila-route2-v11-core-20260801/runtime_candidate/scripts/round_trip_eval.py`
-- still untracked/local-only, not part of this repo). Fully isolated: own
`{}` diagnostics dict, own independent `V11ShadowJsonlSession`, try/except
wrapped, never touches `route_relocalization_diagnostics` or real decisions.
See `code/round_trip_eval_diff_snippets.py` for the exact added code.

## 2026-08-09: the 10-episode combo batch produced almost no data

User picked episodes 386, 4, 88, 367, 5 (retest vs. the plain
`--anchor_v3_shadow` batch), 95, 680, 1040 (real confidently-correct
high-confidence positives), 89, 226 (real-failure low-confidence negative
controls), run combined with `--anchor_v3_shadow --anchor_v3_shadow_self_driven`,
launched serially via `systemd-run --user`. See
`code/run_anchor0_landmark_combo10_20260809_original_broken.sh` for the exact
command.

- ep386 ran to full completion (~40 min) but the landmark mechanism never
  fired even once: `anchor0_landmark_v11_scores.jsonl` contained only a
  single `v11_shadow_session_start` event, zero scored records;
  `anchor0_landmark.jsonl` (the placed/recognized event log) was never even
  created.
- ep4, ep88, ep367, ep5, ep95 each "started" only ~4 minutes apart (vs.
  ep386's ~40 min for a real episode) and produced zero output files --
  each crashed/errored almost immediately.
- ep680, ep1040, ep89, ep226 never even got a "starting" notification -- the
  batch stalled entirely around the ep95 mark, coinciding with the
  session's own Claude Code API connection failing (~10:17 BST onward,
  unrelated to the batch process itself, which runs independently under
  `systemd-run`).
- The machine was rebooted the following morning, so no further log
  forensics on the ep4/88/367/5/95 crashes was possible.

Net effect: of 10 planned episodes, only 1 produced a full run, and it
recorded zero landmark activity. The idea was implemented but effectively
untested as of end of day 08-09.

## 2026-08-10: root cause of the zero-trigger bug

The outbound landmark check (see `code/round_trip_eval_diff_snippets.py`)
gates all its logic behind:

```python
anchor0 = next((a for a in route_agent.anchors if int(a.index) == 0), None)
if anchor0 is not None and anchor0.descriptor is not None:
    ...  # ICP + V1.1 scoring only happens past this point
```

`route_memory_agent.py`'s synthetic anchor A0 is created in `__init__` with
`descriptor=None` and stays that way for the entire episode **unless** the
evaluator separately calls `route_agent.initialize_start_anchor_descriptor(...)`
-- gated behind a completely different, unrelated flag,
`--route_memory_capture_start_anchor_descriptor` (added 2026-07-27 for a
different purpose: giving the terminal A1/A0 sequential pair two real ICP
candidates). Default off.

**The 08-09 combo batch's launch command did not include
`--route_memory_capture_start_anchor_descriptor`.** So `anchor0.descriptor`
was `None` for the entire episode, and the outbound check's guard condition
silently blocked every single interval check (every 25 env steps) for the
whole episode -- no exception, no log line. This exactly reproduces the
ep386 observation from the day before (only `v11_shadow_session_start`,
zero scored records) and applies deterministically to all 10 episodes,
independent of whichever separate issue killed ep4/88/367/5/95 early.

Fix: add `--route_memory_capture_start_anchor_descriptor` to the launch
command. This is an existing, previously-vetted flag (07-27), not new code.

## 2026-08-10: fixed smoke test (ep386) -- mechanism works, but recognition never fires

Re-ran ep386 with the fix (`code/run_anchor0_landmark_smoke_ep386_fixed.sh`).
Result: `exit=0 outbound_checks=7 landmark_placed=1 landmark_recognized=0`.

- Landmark placed at outbound step 150 (`estimated_distance=0.120m`),
  confirming the fix works.
- Episode ended via the same pre-existing, unrelated bug as the 08-09 run of
  the same episode ("Robot has stayed in the same location for 1000 steps"),
  not caused by this instrumentation.
- 414 return-phase recognition attempts fired (one per real relocalization
  update, every 5 env steps). Estimated distance to the landmark frequently
  dropped well under the 3m trigger (closest: 0.65m), but
  **`pose_trusted` was `false` in all 414 attempts -- zero recognitions.**

### Why: V1.1's own pose-trust classifier, not a code bug

The V1.1 portable model (`reliability_v1_1_portable_shadow.json`) is a
frozen gradient-boosted classifier with per-head trust thresholds:
`pose` head trusted iff `p_pose_bad <= 0.3017`. Across the 414 return
attempts, `p_pose_bad` had mean 0.965 (first half 0.982, second half 0.948)
and never dropped meaningfully -- nowhere close to the threshold at any
point in the episode.

Two hypotheses checked:

1. **Temporal-history staleness -- ruled out.** Worried the 08-09 code
   restarts the landmark's "identity" every call (a fresh `RouteAnchor`
   object is constructed each return-phase check). Checked directly:
   `temporal_history_count_including_current` and `temporal_role_age`
   increment cleanly 1 -> 414 across the return phase exactly as expected;
   the causal feature builder's temporal windows (w4/w8/w16/w32 mean/std/
   slope) are populated correctly by the second half of the episode. Not
   the cause.

2. **Multi-frame descriptor richness gap -- ruled out for this run.**
   Hypothesized the landmark (a single frame captured at outbound step 150)
   might be a lower-quality descriptor than a "real" anchor, which could
   optionally be built from several merged frames
   (`--route_memory_multiframe_anchor_window` /
   `--route_memory_multiframe_anchor_symmetric_enabled`). Checked the
   launch command: neither flag was set (defaults: window=1, symmetric
   disabled), so real anchors 1-5 in this exact run are *also*
   single-frame. Not a landmark-specific handicap in this configuration.

3. **Leading, still-unconfirmed hypothesis: proximity-to-home is itself
   out-of-distribution for V1.1's own training data**, echoing the already-
   documented Anchor V3 (unrelated Transformer model) finding in
   `LIVE_SHADOW_SMOKE_TEST_20260809.md` that `oracle_current_anchor == 0`
   never appears in that model's training corpus, because anchor 0's
   point-cloud capture was broken for the entire period that corpus was
   recorded. If V1.1's own historical training episodes have the same
   scarcity of genuine close-to-home matches, the classifier may have
   learned a systematic distrust of the geometric signature of "near home"
   independent of match quality. Raw ICP features (`overlap_ratio`
   ~0.72 vs. ~0.84+ for the one successful outbound match,
   `corridor_degeneracy_ratio` steady at 0.561) are persistently
   different from the trusted case and do not improve over the 414
   attempts -- consistent with a systematic distributional gap rather
   than transient noise, but not yet confirmed against V1.1's actual
   training data.

## 2026-08-10 (continued): 5-episode follow-up batch -- only 2/5 ran, both confirm the finding, hypothesis 3 revised down

A follow-up batch (`code/run_anchor0_landmark_smoke_ep386_fixed.sh`'s pattern
generalized to 5 episodes) was launched via a plain `systemd-run --user`
(no linger configured). It only reached **2 of 5 planned episodes** (ep95,
ep680) before the batch died -- no crash in the eval process itself: a
desktop session/X-server restart (visible in `journalctl` as a new
`systemd --user` instance replacing the old one, ~13:38-13:46) killed
whatever was running in the old session scope, since this launch wasn't
set up to survive it. The remaining 3 episodes never started, and the
launch script itself was in a session-scoped scratchpad that no longer
exists, so the original episode list can't be recovered. Not re-run
further this session (explicit user instruction: analyze what already ran,
don't launch more).

| ep | landmark placed | return_checks | `pose_trusted=true` | closest distance | basin_1 overlap_ratio (min/max/mean) |
|---|---|---|---|---|---|
| 386 (smoke) | 1 | 414 | 0 | 0.65m | ~0.72 typical |
| 95 (killed by the wrapper's own 43-min timeout, unrelated to this instrumentation) | 1 | 202 | **0** | 0.52m | 0.31 / 0.55 / 0.45 |
| 680 (cut off by the session-restart interruption above) | 1 | 67 | **0** | 0.78m | 0.55 / 0.75 / 0.62 |

**Across all 3 episodes tested to date, `pose_trusted` was true in zero of
683 combined return-phase attempts**, even at sub-1m distance. This
strengthens the finding from "one episode" to "reproduced 3/3" and rules out
it being ep386-specific.

### Revised root cause: raw match quality, not (primarily) V1.1 distributional bias

Digging into the raw feature values behind these numbers changes the
diagnosis from hypothesis 3 above. `reliability_v11_portable_runtime.py`
(the actual runtime used here) is a pure sklearn-free tree-evaluator with
**no OOD/eligibility gating at all** -- that logic only exists in the
offline `reliability/bundle.py` (`ReliabilityBundle.predict_features_many`,
used for training/replay, not shadow inference). So `pose_trusted=False`
here is a direct, raw threshold comparison (`p_pose_bad <= 0.3017`), not an
abstain-gate artifact -- confirmed by inspecting full output records: all
three heads (`bearing_trusted`, `distance_trusted`, `pose_trusted`) reject
consistently, and `basin_1_overlap_ratio` never exceeds ~0.75 across any of
the 683 attempts (mean 0.45-0.62), well under the ~0.84+ overlap seen on
matches this project treats as genuinely trusted elsewhere. Even at the
closest approach in ep95 (0.52m, `estimated_anchor_dtheta_deg` near 0deg --
i.e. the yaw estimate was essentially correct), overlap still capped at
0.45. **This is not primarily a "V1.1 has never seen anchor-0 examples"
distributional-bias effect (hypothesis 3, previously leading) -- the raw
ICP overlap between the landmark and the return-phase local map is
genuinely mediocre, and V1.1 is correctly declining to trust it.**

Root cause: the landmark descriptor is a **single, un-merged frame**
captured at whatever heading the robot had at one instant during outbound
(`anchor0_landmark_state["descriptor"] = route_descriptor`, single frame,
no multi-view merge). A single-frame, ego-centric local map only covers a
limited angular slice of the scene; matching it against a return-phase
frame captured from a different position/heading yields only partial
overlap regardless of distance. This is the exact same limitation this
project already discovered and fixed for real waypoint anchors via
`--route_memory_multiframe_anchor_window` /
`--route_memory_multiframe_anchor_symmetric_enabled` (backward+forward
frame accumulation, merged via `RouteMemoryAgent._merge_point_frames`) --
that machinery was simply never applied to the landmark.

## 2026-08-10/11: multiframe merge fix implemented (not yet live-tested)

Implemented in the same untracked local file
(`navila-route2-v11-core-20260801/runtime_candidate/scripts/round_trip_eval.py`).
See `code/round_trip_eval_multiframe_landmark_diff.py` for the exact added
code. Summary:

- **Not** a call into `route_agent._begin_pending_anchor`/
  `_finalize_pending_anchor` (the real-anchor pending-window state machine)
  -- that machine has a single shared `route_agent._pending_anchor` slot
  also used by real outbound anchor placement, and its finalize path always
  calls `_append_anchor`, inserting into `route_agent.anchors`, which the
  landmark must never do (breaks the isolation invariant this whole feature
  is built around).
- Reuses only the pure, stateless merge primitive
  `RouteMemoryAgent._merge_point_frames(frames, target_pose)` plus the data
  already being passively collected in
  `route_agent._outbound_symmetric_frame_buffer` (populated whenever
  `--route_memory_multiframe_anchor_symmetric_enabled` is on, independent of
  whether any real anchor uses it).
- The landmark now keeps its own local pending-window bookkeeping
  (`anchor0_landmark_state["awaiting_merge"/"pending_trigger_distance_m"/
  "pending_trigger_pose"/"pending_backward_frames"/"pending_updates"]`),
  entirely separate from `route_agent._pending_anchor`.
- One subtlety required a second fix: `route_agent`'s own buffer-pruning
  logic freezes its cutoff reference at `route_agent._pending_anchor`'s
  trigger distance *only while a real anchor is pending* -- otherwise it
  prunes relative to the still-advancing current distance, which would
  silently evict the landmark's own pre-trigger (backward) frames before
  its forward window finished accumulating, since the landmark's pending
  state is invisible to that logic. Fixed by **snapshotting the backward
  half of the window immediately at trigger time** (before any further
  pruning can touch it) and only re-reading the forward half fresh from the
  buffer at finalize time.
- Falls back to the old single-frame behavior automatically if
  `--route_memory_multiframe_anchor_symmetric_enabled` is off (keeps
  existing runs reproducible), and to the single-frame fallback descriptor
  if the merge itself returns `None` for any reason.

**Not yet smoke-tested or run live** -- this is implemented but unverified
code, same status the original landmark idea was in after 08-09 before its
own smoke test. Next step: a 1-episode smoke test (e.g. ep386 again) with
`--route_memory_multiframe_anchor_symmetric_enabled` added to the launch
command, to confirm `basin_1_overlap_ratio` actually improves and check
whether `pose_trusted` starts flipping true.

## Status / next steps

Mechanism confirmed working (placement) but never recognizing (0/683
attempts) across 3 real episodes -- root-caused to single-frame overlap
being capped well under this project's trusted-match threshold, not
primarily a V1.1 near-home training gap. A multiframe fix reusing existing,
already-vetted merge infrastructure is implemented but not yet tested live.

**Safety boundary maintained throughout:** no runtime integration beyond
Route 2's own reference copy of `round_trip_eval.py`, no change to
`route_agent.anchors` or `route_agent._pending_anchor`, no modification of
`navila-route2-v11-core-20260801`'s other consumers.
