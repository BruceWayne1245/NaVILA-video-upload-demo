# Anchor V3 active integration + anchor0-landmark V1.1 reuse (2026-08-10)

Continues [`2026-08-10-anchor-v3-self-driven-stuck-belief-bug`](../2026-08-10-anchor-v3-self-driven-stuck-belief-bug/) and
[`2026-08-10-anchor0-landmark`](../2026-08-10-anchor0-landmark/). This session: (1) fixed and live-validated the self-driven
wiring bug, (2) designed and implemented a new `--anchor_v3_active` mode where Anchor V3 fully replaces Anchor V2's
`AnchorTransitionControllerV2` as the real promotion/hold/recovery authority, (3) corrected three design deviations in the
anchor0-landmark mechanism (V1.1 reuse, trigger band, default-on descriptor capture), and (4) launched the first 30-episode
prospective batch combining both. All code changes are in
`navila-route2-v11-core-20260801/runtime_candidate/scripts/round_trip_eval.py` (local dev sandbox, not yet its own commit
history — see `code/round_trip_eval.py` in this folder for the full file as of this writeup).

## 1. Self-driven wiring bug: fixed and live-confirmed

Root cause (see the linked FINDINGS.md above): the self-driven shadow path passed `additional_anchors=()` to the
relocalizer, so `AnchorV3OnlineAdapter` could only ever select from `{believed_current, believed_next}` -- structurally
unable to promote. Fix: a new module-level `_bounded_anchor_probe_indices(available_indices, current_idx, next_idx)`
mirrors `AnchorV2FullActiveController._bounded_probes`' own offset recipe (+1/+2/-1/-2 from current, forward-first,
direction inferred from next vs. current) as a standalone function with no dependency on Anchor V2's controller state,
and the self-driven path now uses it to give V3 real forward-looking candidates every attempt.

**Live smoke test (ep386, `--anchor_v3_shadow --anchor_v3_shadow_self_driven`):** belief pair genuinely advanced three
times over ~3000 env-steps / 375 shadow decisions before being stopped early (goal already met) --
`(4,3)` at step 1175 -> `(3,2)` at step 1514 -> `(2,1)` at step 1674, confidence 0.95-0.99 throughout, matching the real
system's own `requested_pair` direction. Zero shadow-inference failures. Directly refutes the pre-fix behavior (0/684
promotes, frozen at starting pair in 3/3 episodes).

## 2. Design decision: what does "V3 replaces V2" actually mean

Starting position (user): Route2 exists to stop needing hand-written recovery logic the way Route1 does; V2 is a small
classifier wrapped in ~450 lines of hand-coded state machine
(`anchor_transition_runtime/full_active_controller.py`'s `AnchorTransitionControllerV2` -- `progress_threshold`,
`recovery_threshold`, `confirmations_required`, `pair_suspect_threshold`, `probe_rounds_required`,
`max_unconfirmed_holds`, and a `normal -> pair_suspect -> probing -> no_lock` state machine with hand-written branches
for which anchor to trust). V3 has no such external machinery -- `AnchorV3OnlineAdapter` is a straight
tensorize -> forward -> argmax pipeline; its temporal reasoning lives inside the model's own causal-Transformer window.

**Verified against the repo before implementing anything** (a fork research pass, not assumption):
- "Avoid Route1's hardcode trap" is **not documented anywhere** as V3's or Route2's founding rationale -- it's the
  user's own framing. V3's actual stated motivation (`2026-08-08-anchor-v3/PROGRESS.md`) is narrower: V2 has no
  temporal/missing-state mechanism and no re-anchoring when ICP evidence goes untrusted for the tracked pair.
- The master roadmap (`2026-08-02-route2-full-plan-anchor-v2-active/重点-ROUTE2-完整系统改进方案.md`) explicitly reserves
  a **permanent** "不可改变的权责边界" (immutable authority boundary): "Anchor V2 full-active decides promotion/hold/
  recovery itself; deterministic code is responsible for index/topology legality, schema/artifact integrity, bounded
  recovery execution, oscillation protection, kill-switch, and safe-fail" -- and the pipeline diagram's last layer is
  literally "deterministic safety executor." This is not a temporary scaffold to be torn down once a model proves itself.
- V3's `SKIP`/`ROLLBACK`/`REBASE` labels are genuinely oracle-grounded (`teacher.py`'s `transition_teacher`/
  `corrective_teacher`, built from real ground-truth anchor-index deltas, not imitating V2's own output) -- but
  test-set recall is very uneven: `rebase` 89.5% (n=57), **`rollback` 0% (n=4, "too few examples, not treated as a real
  failure yet")**, `skip` doesn't appear in the per-class breakdown at all. V3's own documented "4/6 V2 failures
  resolved" milestone is attributed to the hysteresis/confidence-calibration fix, not to SKIP/ROLLBACK firing correctly.

**Landed on:** V3 gets full promotion/hold/recovery decision authority, replacing `AnchorTransitionControllerV2`
entirely -- but the deterministic layer's *cheap, non-decision-competing* pieces stay (topology/adjacency legality,
kill-switch, a hard **+-2-anchor bound** on any single recovery move). Everything else the roadmap's boundary lists
(schema/artifact integrity, oscillation protection via `max_unconfirmed_holds`, safe-fail) turned out on inspection to
be a few lines each and not real decision logic -- they don't compete with the model's judgment, so keeping them isn't
the kind of hand-coding the roadmap or the user were worried about. The one substantive constraint kept is the +-2
bound, chosen specifically because it lands on V3's least-validated capability (rollback).

## 3. Implementation: `--anchor_v3_active`

New controller function `_evaluate_anchor_v3_active_controller(**proposal)` in `round_trip_eval.py`, registered as
`anchor_transition_full_active_controller` when `--anchor_v3_active` is set (mutually exclusive with
`--anchor_transition_guard_mode`, which must be `off`). Reads V3's per-attempt `AtomicDecision` (stashed via
`anchor_v3_active_pending_decision`, computed by the relocalizer earlier in the same `update_relocalization()` call).

Branches:
- `decision.current_anchor == real_current and decision.next_anchor == real_next` -> hold (`anchor_v3_keep`).
- `decision.current_anchor == real_next` -> plain forward promotion (`execute_promotion=True`). **No external
  multi-attempt confirmation gate** -- deliberately, since that temporal robustness is supposed to live inside V3's own
  8-frame window, not be bolted back on externally.
- Anything else (rollback/skip/rebase to a probe anchor) -> a **bounded recovery redirect**
  (`recovery_requested=True`, `support_current_index`/`support_next_index`), never an immediate commit. This reuses
  `RouteMemoryAgent.sequential_target_anchor_pair()`'s existing support/guidance-index mechanism unchanged -- it only
  redirects what pair gets probed on the *next* attempt, and only becomes a real promotion once V3 confirms the same
  redirected pair through the plain-promotion branch on a later attempt. No new state machine was written; the +-2
  bound is structural, not policed here -- `decision.current_anchor`/`decision.next_anchor` are only ever drawn from
  this attempt's candidate pool, which `_bounded_anchor_probe_indices` already capped.
- Defensive validation before ever setting `recovery_requested`: the pair must be adjacent (`abs(diff)==1`) and its
  local direction must match the real current/next pair's direction. Violations are logged
  (`anchor_v3_direction_mismatch_ignored` / `anchor_v3_invalid_pair_ignored`) and treated as hold -- never raises into
  the real episode.
- Kill-switch: reuses the existing `--anchor_transition_guard_kill_switch_path` file-sentinel mechanism.

Candidate-pool generation for the real (non-self-driven) relocalization call was also changed under `--anchor_v3_active`:
instead of `route_agent.sequential_probe_anchors()` (which only Anchor V2's own controller populates, via a directive
field that -- found while implementing this -- only actually updates on `recovery_requested` attempts, not every
attempt), the relocalizer now computes a fresh `_bounded_anchor_probe_indices` result from the real current/next pair
every single attempt, independent of promotion/hold/recovery history.

New flags: `--anchor_v3_active` (requires `--anchor_v3_shadow`, forbids `--anchor_v3_shadow_self_driven`, requires
`--anchor_transition_guard_mode=off`), `--anchor_v3_active_armed` (second explicit arm, mirrors the existing
`--anchor_transition_guard_active_armed` pattern). Startup validation raises loudly if the V3 adapter failed to load --
shadow mode silently no-ops on a load failure (safe, since it never influences anything); active mode must not, since a
silently-`None` adapter would make the controller abstain every attempt (anchor never promotes) with no visible error.

New per-episode log `anchor_v3_active.jsonl` (since `anchor_transition_guard.jsonl` only exists when
`--anchor_transition_guard_mode != "off"`, which active mode requires to be `off`) -- every attempt's V3 decision plus
the resulting directive, for offline analysis.

## 4. Live smoke test: ep386, clean, one real promotion, safety net proven live

**First attempt hung.** 22+ minutes at ~100% CPU / 0% GPU, zero new log lines, no stack trace obtainable (no sudo for
py-spy). Added heartbeat logging (`[hb] attempt-start / icp-call-start / icp-call-end / v3-infer-start / v3-infer-end /
controller-start / controller-end`, gated behind `--anchor_v3_active`) around every stage of the per-attempt pipeline.
**Re-run with identical code and episode did not reproduce the hang** -- ran cleanly for ~29 min real time with
continuous heartbeat progress (ICP calls 4.1-4.3s each, in normal range) until ending via the pre-existing, unrelated
"robot stayed in same location for 1000 steps" bug (documented historically for ep408/ep367/ep5). Not proven to be a
one-off environment stall rather than a rare bug in this code -- only one clean re-run exists. Worth watching for
recurrence at batch scale.

**Result (394 attempts):**
- 1 real `execute_promotion=True` fired: `(4,3) -> (3,2)`, confirmed via the directive log and the pair-transition
  trace. (Its `executed_action` label reads `anchor_v3_keep`, not `anchor_v3_promote` -- a cosmetic-only issue: V3's
  action-classification head said "keep" while its separate pair-selection head still picked the shifted position, the
  same phenomenon already seen in the self-driven test. The `execute_promotion` boolean itself was correct.)
- 13 defensively-rejected proposals, all `anchor_v3_direction_mismatch_ignored`, all the exact same pair:
  `(current=3, next=4)` while the real pair was `(3, 2)` -- i.e. V3 repeatedly, confidently proposed reconsidering back
  toward the anchor it had just correctly left.
- **Checked the underlying raw ICP evidence directly (not V3's output) for this window** (`covisibility_records` in the
  episode's measurement JSON, attempts 93-101): anchor 2 and anchor 4 both consistently `match_class=clean_full_pose`,
  confidence 0.86-1.0, zero near-tie basins, **and anchor 2's evidence was objectively better** (overlap 0.91-0.97 vs.
  0.84-0.90, distance 0.39-0.43m vs. 0.93-1.02m). This rules out "confidently wrong ICP"/aliasing as the explanation --
  the raw evidence was clean and correctly favored anchor 2 throughout. The flip is a V3 pair-selection-head artifact,
  not an evidence-quality problem. Across all 394 attempts, V3 only ever produced 3 distinct (current, next) outputs
  total: `(3,2)` x319, `(4,3)` x62 (pre-promotion), `(3,4)` x13 -- no other noise.
  - This is empirical, live confirmation of the pre-flagged concern from Section 2: V3's rollback-type output is its
    least-validated capability, and it manifested here almost immediately.
- **All 13 were caught cleanly by the direction-consistency check, zero exceptions.** Structurally, this specific
  failure shape (`d_current == real_current`, `d_next` = the anchor behind, not ahead) can never pass either the plain-
  promotion branch (`d_current` would need to equal `real_next`) or the direction check -- it is harmless by
  construction under this design, not merely harmless by luck this one time.

## 5. anchor0-landmark: three corrections

User-flagged deviations from intent, all fixed this session (`round_trip_eval.py`):

1. **V1.1 must be the real system's own V1.1, not a separately-hardcoded one.** Previously landmark loaded its own
   `PortableV11Bundle`/`V11ShadowJsonlSession` from hardcoded default paths
   (`/home/teambruce/navila-reliability-v1_1-anchor-support-recovery-20260728/...`). Now it requires
   `--reliability_v11_online_shadow` and loads from the SAME `--reliability_v11_runtime_root` /
   `--reliability_v11_portable_artifact` the run actually uses. **Still a separate `V11ShadowJsonlSession` instance**,
   not literally the same object -- checked `CausalV11FeatureBuilder` (`reliability/v11_runtime.py`) and found it keeps
   per-`(episode_key, anchor_index)` rolling temporal history; landmark's outbound checks query real `anchor_index=0`
   every 5 steps throughout outbound, which would pollute that stream's temporal features before the real system's own
   anchor-0 query near arrival if the object were shared. Same weights/thresholds, independent temporal state.
   `--anchor0_landmark_v11_runtime_root`/`--anchor0_landmark_v11_portable_artifact` flags removed (now unused).
2. **Placement trigger changed from a bare upper bound to a band.** Was "first V1.1-trusted reading `<= 3.0m`" (could
   fire anywhere in `[0, 3.0]`). Now `[--anchor0_landmark_trigger_min_distance_m=2.5,
   --anchor0_landmark_trigger_distance_m=3.0]` -- only the OUTBOUND placement trigger; the RETURN-phase recognition
   check is unchanged (still a bare `<=3.0m`, not requested to change). Purpose: the landmark should consistently
   represent roughly the arrival-radius boundary, not an arbitrary position anywhere inside it.
3. **`--route_memory_capture_start_anchor_descriptor` default flipped `False -> True`** (new
   `--no_route_memory_capture_start_anchor_descriptor` companion flag to opt back out, matching the existing
   `--no_vio_bridge` pattern). Without this, anchor 0 has no real descriptor and both the landmark mechanism and the
   terminal A1/A0 sequential pair silently no-op -- this was the actual root cause of the 08-09 10-episode batch's 0
   placements.
4. **(Found while validating #2) Outbound check interval lowered `25 -> 5` env-steps.** At the ~0.075m/step pace
   observed live, 25 steps covers ~1.9m -- enough to skip clean over the new 0.5m-wide trigger band entirely (confirmed
   directly: a live test episode passed through the band at 2.67m with the one 25-step-spaced check landing there, but
   `pose_trusted=False` on that specific reading -- no other check ever landed inside the band for the rest of
   outbound). 5 steps (~0.375m) keeps at least one check geometrically inside the band on approach; matches
   `--route_relocalization_interval_updates`'s existing cadence.

**Isolation live-verified (separate 1-episode test, `--reliability_v11_online_shadow --anchor0_landmark_shadow
--route_memory_multiframe_anchor_symmetric_enabled`, no `--anchor_v3_active`):** `[anchor0-landmark] initialized`
printed with no warning (real-artifact load path resolved correctly); landmark's own score log
(`anchor0_landmark_v11_scores.jsonl`) and the real system's own (`reliability_v11_shadow.jsonl`) grew as two fully
independent files throughout outbound and into return; real V1.1 began scoring real attempts immediately and normally
once return started (`attempt=1` at step 1175, 2 candidate outputs, continuing normally). No landmark placement
occurred in that specific episode (outbound never had a trusted reading land inside the narrowed band) -- a real,
expected consequence of narrowing the window, not a bug; worth watching triggering rate across the batch below.

## 6. Flag-parity check against the most recent real Route2 batch

Before launching the 30-episode batch, programmatically diffed the full flag set against
`/home/teambruce/run_route2_anchor_recovery10_20260804.sh` (2026-08-04, the most recent real Route2 batch script, more
current than `anchor_v2_full_active_batch49_20260802` which this batch's episode cohort is otherwise modeled on). Confirmed
the only differences are exactly the intended ones (V2 controller flags removed, V3-active/landmark flags added). One
real gap found and fixed: `REQUIRE_GPU_CLEAN_BETWEEN_EPISODES=1`/`EPISODE_CLEANUP_WAIT_SECONDS=300`/
`GPU_FREE_MIN_MIB=22000` (added between 08-02 and 08-04, present in recovery10, absent from batch49 and initially
missing from this batch's launcher too) -- added to match current practice.

## 7. Batch launched, outcome not yet known

`anchor_v3_active_30ep_20260811`, launched 2026-08-10 ~21:24 BST via `systemd-run --user` (survives session/SSH
disconnect, confirmed via cgroup path under `user@1006.service`), local launcher
`/home/teambruce/run_anchor_v3_active_30ep_20260811.sh`. First 30 of the same 49-episode locked-order cohort used by
`anchor_v2_full_active_batch49_20260802` (`87 88 134 310 678 4 187 994 680 579 539 367 5 89 351 264 95 962 1040 647 276
658 484 581 961 1038 646 764 268 844`) -- directly comparable to that prior Anchor V2 result (66.7% actual return
success, 10/15, on a smaller completed subset) on identical scenes/episodes. `--reliability_v11_core_mode=active` (real
enforcement, not shadow) confirmed active in the first episode's startup log
(`[v11-shadow] initialized features=249 decision_shadow=False consumer_core=active enforcement=True`).

Results land in `NaVILA-Bench/batch_logs/anchor_v3_active_30ep_20260811/summary.tsv`. **Outcome unknown as of this
writeup** -- check for a follow-up investigations folder with the actual result before treating anything above as
validated beyond the single ep386 smoke test.

## Open threads for whoever picks this up next

1. **Batch result itself** -- return-success rate, whether the ep367/ep88-style lag pattern (V3 under-reacts to rapid
   true-anchor movement, flagged in the 08-08 handoff) recurs, whether recovery_requested ever actually fires at scale
   (0/394 in the smoke test), whether the hang from Section 4 recurs.
2. **`anchor_v3_keep` promotion-label cosmetic issue** (Section 4) -- low priority, easy fix if revisited.
3. **Landmark placement rate at scale** -- did the narrower band + 5-step interval combination produce a reasonable
   placement rate across 30 episodes, or does it need further tuning (band width, interval, or both)?
4. **`recovery10`'s own outcome is still unknown** (queued 2026-08-04, see
   `2026-08-04-route2-anchor-recovery-state-machine`) -- unrelated to this session's work but still the single oldest
   dropped thread in the project as of this writing.
