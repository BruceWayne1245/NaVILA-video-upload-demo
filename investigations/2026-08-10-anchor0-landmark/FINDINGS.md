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

## Status / next steps

The mechanism itself (place + repeatedly re-check) works correctly end to
end. Whether it can ever be useful depends on resolving hypothesis 3 above
-- unconfirmed. Not pursued further this session; a broader batch (5 more
episodes, `code/run_anchor0_landmark_smoke_ep386_fixed.sh`'s pattern
generalized) was queued next to see whether ep386's zero-recognition result
generalizes or was episode-specific.

**Safety boundary maintained:** no runtime integration beyond Route 2's own
reference copy of `round_trip_eval.py`, no change to `route_agent.anchors`
or any real decision path, no modification of
`navila-route2-v11-core-20260801`'s other consumers.
