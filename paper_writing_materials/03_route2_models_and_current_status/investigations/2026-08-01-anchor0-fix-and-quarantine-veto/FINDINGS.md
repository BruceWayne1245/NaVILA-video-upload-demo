# 2026-08-01 — promotion_active_promote_30ep_20260731 forensics, anchor0 empty-point-cloud fix, quarantine-veto (model-as-AND-gate) implementation

Author: Claude (Route 1). Continues directly from
`2026-07-31-promotion-controller-phase3-active-promote` (Phase 3 promote/wait
active enforcement, quarantine_threshold 0.65->0.85, the overnight
`promotion_active_promote_30ep_20260731` smoke/data batch queued behind
Route 2's `unified_shadow50_retry4`). That batch's outcome was unknown as of
the 07-31 writeup; this investigation opens with checking it.

## 0. Batch actually started 2026-08-01, not overnight

The queue watcher (`navila-active-promote-30ep-queue-20260731`) had been
polling since 07-31 19:38 but Route 2's job didn't free the GPU until the
morning of 08-01; the 30-episode batch itself ran 07:14-11:39.

## 1. Batch yield: 19/30 episodes produced a valid outcome, and a real infra bug ate the other third

`summary.tsv`: 4 `round_trip_success=True` (ep4, ep134, ep205, ep268), 10
`False` (ep89, ep187, ep381, ep408, ep409, ep420, ep430, ep488, ep498, ep500),
1 timeout (ep5, exit_code=124), 3 "exit=0 but blank" (ep295, ep367, ep368 —
same already-documented final-measurement-write-failure pattern as
0731's ep708/ep994/ep4; jsonl/trajectory data intact, just not summarized),
and **11 episodes (ep647/671/678/680/688/708/974/994/1038/1040/1058) crashed
before ever starting**, all with `exit_code=98` (`start_vlm_server` timeout)
in ~20s each.

Root cause, confirmed from `ep647_vlm.log`:

```
OverflowError: bind(): port must be 0-65535.
...
Timed out waiting for VLM server on port 65647
```

`run_promotion_active_promote_30ep_20260731.sh` hardcoded `PORT_BASE=65000`
(the generic driver's own default is 59000; `reliable30v3` used 63000). Port
= `PORT_BASE + episode_idx`; once `episode_idx > 535`, the port exceeds
65535 and `vlm_server.py`'s `socket.bind()` raises. Every one of this batch's
episode_idx values above 535 failed identically. This is specific to this
run's launcher, not a `reliable30v3`/driver bug — confirmed by diffing
`PORT_BASE` between the two launcher scripts. (ep354's exit=98 is unrelated:
a one-off `transformers` import error, `too many values to unpack (expected
0)` — a flaky/transient environment issue, not port-related, did not recur.)

**Consequence**: 4 of `reliable30v3`'s 7 known-successful episodes on this
same episode set (ep647, ep671, ep688, ep1040) never got a chance to be
re-tested under active-promote at all. Per explicit user direction, re-running
those 11 was deprioritized this session in favor of root-causing the return
failures first; the fix (PORT_BASE=63000) is folded into today's new launcher
(Section 6).

## 2. Direct episode-by-episode comparison vs `reliable30v3` (shadow-only baseline): 2 flips failure->success, 0 regressions

Of the 30 episode_idx values, 13 have a valid `round_trip_success` in *both*
`promotion_active_promote_30ep_20260731` and `reliable30v3`:

| episode | reliable30v3 (shadow-only) | active-promote (this batch) |
|---|---|---|
| ep134 | False | **True** |
| ep205 | False | **True** |
| ep268 | True | True |
| ep89, ep187, ep381, ep408, ep409, ep420, ep430, ep488, ep498, ep500 | False | False |

2 improvements, 0 regressions, on episodes where both batches actually
produced a comparable outcome. (ep4 succeeded here but has no valid
`reliable30v3` baseline — all 3 of that batch's ep4 attempts crashed with
exit 143/143/124 — so it isn't counted either way.)

## 3. Ground-truth verification of the promotion model's promote calls (real anchor/robot world positions, not the system's own belief)

Methodology: `icp_replay_dataset/anchors.json`'s `world_pose` (anchor ground
truth) and `trajectories/*.jsonl`'s `position` (robot ground truth) are the
same coordinate frame (verified exactly, byte-for-byte, on anchor0/step0 for
two different episodes). For every `promotion_shadow_score` attempt in
`promotion_controller_shadow.jsonl`, computed the true straight-line distance
from the robot's real position to the real position of the `next` candidate
anchor (`output.anchor_idx`), and used the code's own
`promotion_close_radius_m=0.75m` as ground truth for "should this have
promoted by now".

Across the 5 episodes with outbound success (ep4/89/134/187/205), the
model's promote decisions beat the heuristic's on precision+recall in 4/5:

| ep | heuristic precision/recall | model precision/recall |
|---|---|---|
| ep4 | 0.22 / 0.67 | 0.30 / 1.00 |
| ep89 | 0.50 / 0.33 | 0.43 / 1.00 |
| ep134 | 0.50 / 0.17 | 0.68 / 0.72 |
| ep187 | 0.67 / 0.07 | 0.94 / 1.00 |
| ep205 | 0.50 / 0.16 | 0.86 / 1.00 |

Specifically checked every "model overrides heuristic's wait into promote"
event against ground truth: ep187 28/29 (96.6%), ep205 26/26 (100%), ep134
20/26 (77%) were within the 0.75m close-radius at that exact moment; ep89's 5
overrides were weaker (2/5 strict, 5/5 within 1.5m) but not egregious. The
heuristic's own historically-low recall (misses 83-93% of genuine
close-enough moments in 3/5 episodes) is exactly the "mechanism gap" this
model was built to fix (see `2026-07-28-promotion-quarantine-controller-model`)
— now confirmed against ground truth, not just offline training-set metrics.

## 4. The "model promotes -> system believes it arrived -> confidence collapses" hypothesis: investigated and retracted

Initial pattern-match: in the two originally-failed episodes (ep89, ep187),
right after a sustained model-only promote override, `hint_action_arbiter`
logged `reason=target_too_close`, and the system's own `distance_to_start`
belief was significantly biased (14-15m believed vs ~10-11m true) for a
while afterward. Read as "model forces a bad promotion, system briefly
believes it arrived home, then confidence craters."

Two corrections, in order:

1. **The same signature appears in the successful episodes too** (ep134:
   19-attempt override run, belief 15.8m vs true 8.6m; ep205: 26-attempt run,
   belief 12.3m vs true 8.4m) — so it does not discriminate success from
   failure by itself.
2. **`target_too_close` does not mean "believes it arrived home".**
   `hint_action_arbiter.py:220-233`: `distance` here is `distance_to_anchor_m`
   (to the *current* anchor, threshold `min_anchor_distance_m=0.35m`), not
   `distance_to_start_m`. And `sequential_target_anchor_pair()`'s own
   docstring: "current" at the instant return starts *is* the return-start
   point by construction (the last outbound anchor, appended exactly there).
   So `target_too_close` firing right at return-start is a structural
   artifact of anchor-pair initialization, present on every return
   regardless of promotion model activity — not evidence of any false
   "arrived home" belief. The original framing was wrong and is retracted.

The `distance_to_start` overestimate itself is real and reproducible, but
appears in both successes and failures with similar magnitude and gradually
converges — a known characteristic of the anchor-chain distance composition,
not something this investigation ties to promote/quarantine specifically.

## 5. Root cause of all 4 outbound-success/return-failure episodes (ep89, ep187, ep420, ep498)

Confirmed via `summary.tsv` directly: these 4 are the *only* episodes with
`outbound_success=True, return_success=False` in this batch.

- **ep89**: `stuck_recovery.py`'s own recovery mechanism (not the VLM
  "choosing" to spin) correctly detected a physical wedge (`wedge_detected`
  at step1401, 8 consecutive no-progress queries) and scripted a 180 deg
  reverse-turn. The robot *did* rotate (~186 deg net, confirmed from
  `yaw_deg` trace, including one direction-flip at step1701 per the
  documented "can't-rotate-this-way" detector), but at only ~15-20 deg
  actual rotation per query against a `turn_step_deg=45` command — a
  ~2.5-3x undershoot of what `max_recovery_queries=16`'s budget assumes —
  so the recovery attempt (1st of 5 allowed) timed out
  (`recovery_exhausted` at step2376) just short of completing, and the
  episode force-ended via `stop_gate`'s anchor-corroboration path one query
  later before a 2nd attempt could ever trigger. A locomotion/tuning gap in
  `stuck_recovery`, unrelated to promote/quarantine (heuristic and model
  were in full agreement, "wait", at the point of failure).
- **ep187**: return genuinely progressing (true distance 11.0m->7.4m,
  belief converged to near-accurate by the second half). Ends because the
  VLM issues a false "I think I've finished" stop at 7.5m; `stop_gate`
  correctly vetoes it once (`decision=vetoed`, high confidence, d>r_out),
  but the VLM repeats the same claim and this time the reading's confidence
  is 0.2 -> `stop_gate.py`'s Injection C (`distance_authority_low_reliability`
  / low-confidence branch, 2026-07-21, explicitly designed to defer to the
  VLM rather than veto on an untrusted "far" reading, per the documented
  ep680 regression it was built to fix) returns `deferred`, and the false
  stop goes through. A pre-existing, deliberately-designed heuristic
  tradeoff, unrelated to promote/quarantine (no model override was active
  anywhere near this moment).
- **ep420**: heuristic and model in full agreement ("wait", >97% confidence)
  for the entire critical window (steps 4300-4480) -- no promotion,
  active or heuristic, happened here at all; the only state changes were
  heuristic-only trend/reliability quarantines (anchor3, then anchor2,
  unrelated to the model). The failure is a `distance_to_start` belief
  swinging from a persistent *overestimate* to a persistent *underestimate*
  (3.39m -> 2.21m in one update, while true distance barely moved) —
  a single-anchor ICP-reading bias, the same "confidently wrong" class this
  project has chased since 2026-06/07, now biased short instead of long.
  The sustained underestimate satisfies `stop_gate`'s anchor-corroboration
  forced-stop path while the robot is still genuinely ~3.4m out. Not
  attributable to the new active-promote/quarantine-veto mechanisms.
- **ep498**: see Section 6 below (the most actionable finding this session).

## 6. ep498 deep dive: heuristic quarantine cascade exhausts every candidate down to a structurally-unmatchable anchor0

`promotion_controller_shadow.jsonl` stops emitting `promotion_shadow_score`
events entirely after step2519/attempt130 — `PromotionFeatureBuilder.
build_attempt` needs >=2 candidate indices and stops getting them.
Simultaneously, `trajectories/*.jsonl`'s `route_memory.distance_to_start_m`
and `.relocalization_confidence` freeze at **exactly** the same bit-for-bit
value (`4.318878320585844` / `0.2`) for 19 consecutive queries (~475 steps),
while the robot's true position keeps changing (confirmed via
`icp_replay_dataset` point-cloud density staying normal, 7900-9600 points,
ruling out a sensor dropout). `hint_action_arbiter` is stuck on
`low_relocalization_confidence` the whole time, so the VLM gets no
correction and walks the robot from 3.9m true distance to 5.5m, away from
home, before falsely declaring the instruction finished.

Root cause chain, confirmed:

1. `icp_replay_dataset/anchors.json`: **anchor0 has `n_points=0`** —
   empty local map. (Confirmed general, not ep498-specific: ep4's anchor0
   is `null` too.) `RouteMemoryAgent.__init__` calls
   `self._append_anchor(descriptor=None, metadata={"event": "start"})`
   before the environment has produced a single sensor frame — anchor0 is
   permanently unmatchable by construction.
2. `existing_heuristic_decision` in the shadow log (the real, currently
   deployed `_record_next_anchor_trend` mechanism, unrelated to the
   promotion model) shows three genuine, real quarantines in a row:
   anchor3 (step2454), anchor2 (step2484), anchor1 (step2519).
   `_next_candidate_index` skips quarantined anchors, so "next" cascaded
   3 -> 2 -> 1 -> **0**, the one anchor that can never produce a match.
3. Ground-truth check on whether 1/2/3 "deserved" quarantine: the robot's
   true distance to each, at quarantine time, was 1.69m/2.52m/3.23m, and
   its *closest approach to each anchor over the entire rest of the return*
   was barely better (1.63m/2.47m/3.16m) — these anchors genuinely were
   never revisited closely on this episode's actual return path (it
   diverged geometrically from the outbound anchor chain by 1.6-3.2m).
   Whether the heuristic's specific *trend* judgment (ICP reading quality
   degrading) was independently correct could not be confirmed from this
   session's available logs (raw ICP confidence/inlier features aren't
   written to the shadow log) — would require an offline ICP replay against
   `icp_replay_dataset`'s raw point clouds, not attempted this session.
4. **The model's own contemporaneous classification was "wait" (not
   "quarantine") on all three** (quarantine proba 0.29/0.23/0.02,
   well under the 0.85 threshold) — i.e. it had no independent evidence
   these anchors were bad. Since the model's quarantine class has zero
   authority over `_quarantined_anchor_indices` by design (2026-07-31
   Phase 3 decision), this more-cautious judgment had no effect on the
   outcome.

## 7. Fix 1: anchor0 descriptor backfill

`route_memory_agent.py`, `update_outbound_motion`: the first time a real
descriptor is available, backfill `anchors[0].descriptor` with it (identity
— `pose_from_start=[0,0,0]`, `distance_from_start_m=0.0` — untouched, only
the descriptor moves from `None` to real point-cloud data). Verified with a
standalone smoke test: descriptor is `None` before the first
`update_outbound_motion` call, gets backfilled on the first call with a
descriptor, is *not* overwritten on subsequent calls, and identity fields
are unchanged. `py_compile` clean. See `code/route_memory_agent_20260801.patch`.

This makes anchor0 a normal, matchable anchor like any other — the Section 6
cascade can no longer terminate at a permanently-empty dead end (it can
still terminate at anchor0 if genuinely quarantine-worthy, but now with a
real chance of producing a match instead of guaranteed zero).

## 8. Fix 2 (design decision, explicit user sign-off): quarantine-veto — model as an additional AND-gate, not full authority

User's question after Section 6: should the model get full authority over
both promote *and* quarantine, and should this be validated with a fresh
30ep batch? Recommendation given and accepted: **not full quarantine
authority** — this repo's own 2026-07-31 offline validation
(`2026-07-31-promotion-controller-phase3-active-promote/FINDINGS.md`
section 3) measured the model's quarantine-class precision at only
**0.246-0.327** — i.e. 2/3 to 3/4 of any quarantine call the model made on
its own initiative would be wrong, and quarantine is irreversible for the
rest of an episode. Handing initiation authority to a ~30%-precision
classifier is a worse risk profile than the failure it would be fixing.

Instead, implemented **veto-only** authority (`--sequential_pair_promotion_
model_quarantine_veto`, off by default): the existing heuristic mechanisms
(`_record_next_anchor_trend`/`_quality`/`_reliability`/`_stability`) remain
the *only* thing that can ever add to `_quarantined_anchor_indices`; the
model's classification (reusing the same per-attempt scoring call as
active-promote, no extra inference) can only *block* that add, and only
when the model's own decision is *not* "quarantine" (i.e. it has no
independent evidence backing the heuristic's call). This is structurally
identical to Phase 3's original "Option 2" (safest of the three integration
options considered 2026-07-31: model as an additional AND-gate) applied to
quarantine instead of promote — it can only lower quarantine's
false-positive rate, never raise it, and does not touch the model's own
weak quarantine-class precision at all (uses only its already-validated
promote/wait judgment, Section 3). Applied to ep498's three real
quarantines retrospectively: the model's contemporaneous "wait" calls would
have vetoed all three.

Code changes (`route_memory_agent.py`, `round_trip_eval.py`):
new `sequential_pair_promotion_model_quarantine_veto` constructor param +
`_active_quarantine_veto_decision` transient field (same
set-once-per-attempt-by-round_trip_eval.py convention as `_active_promotion_
model_decision`) + `_quarantine_vetoed_by_model()` helper, guarding all 4
`_quarantined_anchor_indices.add(idx)` call sites. `round_trip_eval.py`
reuses the exact same `active_decision` classification already computed for
active-promote to also set the veto signal — no second model call.
`py_compile` clean on both files; unit-tested the veto helper directly
(flag off -> never vetoes; flag on + no decision this attempt -> fail-open,
does not veto; flag on + model says "quarantine" -> does not veto,
heuristic proceeds; flag on + model says "wait"/"promote" -> vetoes).
See `code/route_memory_agent_20260801.patch` and
`code/round_trip_eval_20260801.patch` — both verified byte-for-byte against
the live deployed files via `diff`+`patch` round-trip.

## 9. Follow-up batch queued

`run_promotion_quarantine_veto_30ep_20260801.sh`: same 30 episode_idx values
as `reliable30v3`/`promotion_active_promote_30ep_20260731` (three-way
comparison), `PORT_BASE` fixed to 63000 (Section 1), both anchor0 fix and
`--sequential_pair_promotion_model_quarantine_veto` active alongside the
already-validated `--sequential_pair_promotion_model_active_promote`.

Queued behind Route 2's currently-running
`navila-route2-anchorv2-terminal50-resume1-20260801.service` (a proper
systemd unit, not a bare session-scope process this time) via
`wait_for_route2_then_run_quarantine_veto_30ep_20260801.sh`, itself launched
under a new transient systemd unit
`navila-quarantine-veto-30ep-queue-20260801` (`systemd-run --user`).
Verified independent of any interactive session: cgroup is
`user.slice/user-1006.slice/user@1006.service/app.slice/navila-quarantine-
veto-30ep-queue-20260801.service`, distinct from this session's own
`session-*.scope`; `loginctl show-user teambruce` confirms `Linger=yes`. Will
survive a disconnect. Outcome not yet known as of this writing — check
`NaVILA-Bench/batch_logs/promotion_quarantine_veto_30ep_20260801/summary.tsv`
and `journalctl --user -u navila-quarantine-veto-30ep-queue-20260801.service`
next session.

## 10. Open items not addressed this session

- `stuck_recovery`'s turn-rate/query-budget mismatch (Section 5, ep89) —
  the 16-query cap assumes closer to the commanded 45 deg/query than the
  ~15-20 deg/query actually observed.
- No floor/backstop against a quarantine cascade exhausting the *entire*
  remaining candidate pool in general (anchor0's fix removes the specific
  guaranteed-zero dead end, but a route with no anchor0 fix and heavy
  quarantining could in principle still empty the pool down to a real but
  very poor anchor).
- `promotion_controller_shadow.jsonl` still only logs the model's raw
  per-attempt decision, not whether `closure_reject_veto`/short-baseline
  withhold subsequently canceled it — an auditing gap noted mid-session,
  not fixed.
- ep498's heuristic trend-quarantine judgment on anchor1/2/3 was checked
  against ground-truth *position* only; whether the underlying ICP-reading
  *quality* trend it acted on was itself accurate remains unconfirmed
  (would need an offline replay against `icp_replay_dataset`'s raw frames).

---
No credential, private token, model binary, or simulator log bundle is
stored in this investigation.
