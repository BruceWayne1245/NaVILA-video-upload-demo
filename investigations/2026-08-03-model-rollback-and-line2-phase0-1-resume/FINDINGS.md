# 2026-08-03 — Route1 abandons the promotion/quarantine model; resumes the abandoned "line 2" hard-coded fix plan (Phase 0-1 implemented, tested, offline-validated)

**This is the current Route1 direction as of today: the promotion/quarantine controller model (`promotion_controller_v2_2026-07-28_isaacenv.pkl`) is no longer used on Route1. Route1 reverts to a fully hard-coded architecture and resumes `investigations/2026-07-28-downgrade-batch-mechanism-failure-classification/MODIFICATION_PLAN.md`'s "line 2" plan, which was written the same day the model track ("line 1") was scoped and then never touched again once Route1 pivoted to the model. Phase 0 and Phase 1 of that plan are now implemented, unit-tested, and offline-replay-validated against real historical episodes. A live smoke test is the next step, currently blocked on GPU availability (occupied by Route2).**

---

## 1. Why the model is being dropped

Route2 (Codex track) is pursuing a fully-model architecture (Anchor-V2). With Route2 already covering the "go full ML" direction, Route1 doing a half-measure (model owns only the promote/wait decision, heuristics own everything else) added complexity without a differentiated purpose, and a same-session investigation found the model provides **no real detection immunity** to this project's oldest, hardest problem ("confidently-wrong" ICP / anchor identity aliasing) anyway:

- The model's own feature schema (`promotion_controller_runtime.py::FEATURE_NAMES`) is built entirely from `cur_*`/`next_*` **internal ICP-quality signals** (confidence, inlier_count, match_class, best_to_second_score_ratio, near_tie_basin_count) plus a rolling `cur_bad_fraction_hist` — the same signal class the hard-coded heuristic already used. None of these can distinguish "a clean fit to the correct anchor" from "a clean fit to the wrong-but-structurally-similar anchor" — that is definitionally what "confidently wrong" means. Giving a learned model more authority over the same blind features doesn't add information, it just relocates the same blind decision to a different executor.
- A concrete case from this session (ep498 of `promotion_quarantine_veto_30ep_20260801`): the model actively promoted (proba 0.56-0.92) against a **unanimous heuristic "wait"** across attempts 5-9, exactly coinciding with a real anchor-identity divergence onset (current jumped from correct to 3 anchors behind truth in ~90 steps and never recovered). This is not proof the model is worse than the heuristic in general, but it demonstrates the model is not immune to the same failure class.
- Architecturally, the model was only ever authorized for two narrow roles: (a) fully replace the `bounded_evidence` promote/wait vote (Phase 3, 2026-07-31), wrapped by two hard-coded veto layers (`closure_reject_veto`, short-baseline withhold) that still apply on top; (b) veto-only (never initiate) a heuristic-proposed quarantine call (2026-08-01) — and in the most recent 30ep batch, that veto authority **never fired once** (heuristic and model never disagreed on a quarantine call across 12 episodes / thousands of attempts). Expanding the model's scope to "fully manage current and next" was considered and explicitly rejected this session: current's identity-recovery problem (below) needs an independent signal, not more decision authority over the same one.

See section 4 for what a ground-truth investigation into current/next tracking actually found, which further informed this call.

## 2. 07-22 architecture vs. today — correcting a misconception

Before making this call, we checked whether the last ~2 weeks of accumulated fixes had made the system meaningfully more complex than 2026-07-22 (the day of the best-ever round-trip result, 12/19 = 63%), which was recalled as having a single, simple failure story ("everything is confidently-wrong ICP").

**That recollection was wrong.** `investigations/2026-07-22/FINDINGS.md`'s own words: "The 8 return failures are NOT one problem." Breakdown: 3 confidently-wrong, 2 control/wall-wedge, 1 VLM turn-oscillation, 1 VLM wrong-navigation, 1 near-miss — only 3/8 (37.5%) were confidently-wrong. The "~97% confidently-wrong" figure people remembered is from a **different, later investigation** (2026-07-24, larger/different sample) — not comparable to 07-22's own number. Also notable: even at 07-22, all 9 clean successes ended via `stop_gate`'s forced/deferred backstop, never a clean VLM-initiated stop the gate merely approved — "success carried by layered redundancy, not accurate tracking" is not a new phenomenon from the last two weeks, it was already true on the best day this project has had.

**The actual flag/mechanism diff between 07-22's config and today (model flags stripped) is small** — most of what's now considered "current architecture" (`bounded_evidence`, `alias_aware`, `quarantine_mode=trend`, `closure_check`, `stop_gate_anchor_corroboration`, the `reliability_quarantine`/`demote_current`/`distrust_downstream` family) was **already** in the 07-22 config. Only 5 things were genuinely added since then:

| New since 07-22 | Purpose |
|---|---|
| `--reliability_quarantine_shared_trend_budget` | Caps trend-quarantine's chain length via Injection A's shared budget |
| `--stuck_recovery` | Return-phase locomotion supervisor for physical wedge/oscillation |
| `--sequential_pair_loftr_rear_yaw_check` | Vision-based rear-view yaw cross-check |
| `--sequential_pair_vision_disagreement_mode=downgrade` | Stage-2 camera-yaw fix: downgrade confidence on vision/ICP disagreement |
| anchor0 descriptor backfill (code fix, 2026-08-01) | Prevents anchor0's empty descriptor from freezing relocalization |

**Conclusion: the "growing complexity" feeling was mostly the model layer (now removed) plus investigation/diagnostic overhead, not a ballooning hard-coded core.** The core architecture is close to what it was on the best day this project has had.

## 3. Ground-truth accuracy of current/next anchor tracking

A rigorous ground-truth check (not naive per-anchor `distance_from_start_m`, which carries real accumulated-odometry bias — built instead from the dense outbound trajectory's true positions via fine arc-length matching, validated against the logged `distance_to_start_m` field to <3cm) against `promotion_quarantine_veto_30ep_20260801` (n=4442 relocalization events, 13/24 valid episodes):

- **Current-anchor exact-match: 12.9% pooled, 17.9% even in the 7 successful episodes.** This is `bounded_evidence`'s **designed** lag (trading instantaneous accuracy for anti-overshoot safety), not a defect — lead/overshoot (the failure mode it exists to prevent) stayed rare (4.9%).
- **Next-anchor accuracy (correct if `|shadow_next - true_next| < 3`): 71.3% pooled, but 87.7% in the 7 success episodes vs. 52.7% in the 5 known return-failures — a 35-point gap.**

**Initial verdict (later revised, see §4): promotion/quarantine mechanism looked fine on aggregate, no urgent redesign justified.**

## 4. Per-episode causal reconstruction — the aggregate verdict was too optimistic

A deeper, per-episode reconstruction of the same 5-episode failure group (367, 368, 498, 994, 1040) revealed the aggregate number in §3 undersold the problem:

- **ep367**: accurate at step 1925, collapsed to 4-anchor-behind by step 2299 (~374 steps later), never recovered — ~92% of the entire return phase ran on a badly wrong identity. Plausible primary driver of the episode's oscillating-5-8m navigation failure that never reached a stop decision.
- **ep368**: diverged to 4-behind by step 3139, still wrong at the terminal forced-stop (step 3276). **Critically: the "anchor corroboration" stop_gate trusted at that moment was computed relative to the SAME wrong anchor** — the two signals (anchor's own fixed distance, live reading) agreed specifically BECAUSE both were anchored to the same mistaken identity, not because they were genuinely independent. This means a self-consistent wrong-identity reading isn't a noisy one, so simple reliability-based fixes (§6) don't help this specific failure mode.
- **ep498**: diverged in ~90 steps. In that exact window, **the model promoted against a unanimous heuristic "wait"** (see §1) — a concrete, evidenced case of the model's override coinciding with the divergence onset.
- **ep994**: the one clean case — briefly drifted, self-corrected back to exact truth by episode end. This failure is purely downstream (stop/confidence), confirming not every failure is anchor-related.
- **ep1040**: already wrong at the very first observed event — true onset predates the visibility window, unresolved.

**Revised verdict: 4 of 5 failures have a real, large (3-4 anchor) identity drift STILL ACTIVE and NEVER RECOVERED at the moment of terminal failure — not just statistically correlated with failure, causally implicated.** The real gap is not promotion accuracy, it's the **absence of any recovery path once a bad drift has already happened** — this directly motivated resuming the line-2 plan's Phase 0.2 (below), which turns out to have been designed for exactly this gap back on 2026-07-21.

## 5. Stop-gate causal classification (17 return-failure instances, 4 pooled batches)

Pooled every outbound-success/return-failure instance across `promotion_shadow_reliable30v3_20260731`, `promotion_active_promote_30ep_20260731`, and `promotion_quarantine_veto_30ep_20260801`(+resumes) — config-verified identical `stop_gate` settings across all four, so pooling is valid. Classified into 3 buckets using ground-truth trajectory data (not log text): **Category 1** (stop_gate alone could have saved it, robot was truly close at some point) = 3; **Category 2** (stop_gate implicated but robot still needed real navigation) = 7; **Category 3** (unrelated to stop_gate, pure navigation/timeout) = 7.

Category 2 splits into two distinct sub-mechanisms: **(a)** failure-to-veto a premature VLM stop under low confidence (3 instances — this is exactly mechanism D from the 2026-07-28 line-2 plan, still unresolved 3+ weeks later) and **(b)** the anchor-corroboration FORCE path firing on a stale/wrong reading (3 instances: r30v3-ep678, qv-ep368, qv-ep498) — root-caused this session to a real code gap: **neither of `stop_gate.py`'s two FORCE paths (confidence-based, anchor-corroboration) ever checks the existing `distance_authority_low_reliability` signal**, which is already wired into the VLM-issued-stop veto/defer branch (Injection C, 2026-07-21) but was never extended to FORCE. Category 1 also surfaced a standalone new finding: **r30v3-ep678's stall was mild, but r30v3-ep500 showed a distance estimate frozen bit-for-bit for ~3400 steps driving 35 consecutive wrong vetoes** — a distinct "stuck relocalization update" bug, flagged for its own future investigation, not addressed here.

## 6. The recovered "line 2" plan

`investigations/2026-07-28-downgrade-batch-mechanism-failure-classification/` (`FINDINGS.md` + `MODIFICATION_PLAN.md`) is a full hard-coded fix plan for 7 named mechanism gaps (A-G), found the same day the model ("line 1") was scoped, explicitly designed to run **independently** of the model track. Confirmed via code grep: **none of it was ever implemented** — Route1 fully pivoted to the model and line 2 was never touched again. It is now being resumed.

| Bug | Episodes | Root component | Status before today |
|---|---|---|---|
| A — `candidate_promote` never checks absolute confidence/ambiguity | 19, 88, 95, 427 | `_select_sequential_pair_relocalization` | Never built |
| B — trend-quarantine has no `current_unreliable` escape hatch | 344, 355 | `_record_next_anchor_trend` | Planned 2026-07-21 (Injection B part ii/iii), never built |
| C — oscillating readings defeat both promotion and quarantine | 276, 646 | `bounded_evidence` + `bad_fraction` | Out of scope (needs a model, ironically — deferred) |
| D — `stop_gate` anchor-corroboration veto doesn't fire when it should | 205, 276, 368, 427, 646 | `stop_gate.py` | Root cause unresolved |
| E — `hint_action_arbiter` uses one confidence bar for two different-risk actions | 368 (+ background) | `hint_action_arbiter.py` | Never built |
| F — VLM never issues a stop at all | 89 | prompt/decision layer | Out of scope, separate track |
| G — Injection C's hard 2.5 threshold has no graduated near-miss band | 366 | reliability gating | Calibration question, deferred (Phase 2) |

## 7. What was implemented today (Phase 0 and Phase 1; Phase 2 deferred)

All new flags default **OFF** — zero behavior change to any already-validated batch until explicitly enabled, per this project's established convention.

### Phase 0.1 — diagnose Bug D (diagnostic only, no behavior change)

Added `anchor_progress_role` (`"next"`/`"current"`/`None`) + the already-existing `anchor_route_remaining` to `RelativeStartProgress` (route_memory_agent.py) and `GateDecision` (stop_gate.py), threaded through `_anchor_progress()`'s two branches and every `GateDecision(...)` return site, and into the `[stop_gate]` print line. Purely observational.

**Root-cause candidate found for ep205's Bug D discrepancy**: `--sequential_pair_report_next_anchor` (on in every recent batch) makes `_anchor_progress()` prefer the **NEXT** role's estimate over CURRENT's when building the progress object stop_gate/hint_arbiter both consume. Direct data check confirmed the 2026-07-28 FINDINGS.md's cited "anchor7, route_remaining=7.05m" for ep205 actually **was** the next role (anchor10, route_remaining=10.08m, was current) — a real role substitution that wasn't distinguished before. This does not fully explain the exact `gate_authority_d` value logged at the failure step (still open), but the new diagnostic fields make this immediately checkable next time.

### Phase 0.2 — `--sequential_pair_evict_unreliable_current` (+ `--current_evict_stall_attempts`, default 30)

Part (i) of the original 2026-07-21 Injection B design (gate `closure_reject_veto` on current's own reliability) was **already shipped**. This implements the two missing parts:

- **(ii) Explicit eviction**: tracks a consecutive-attempt streak of `_current_persistently_unreliable(current_idx)`; once it reaches `current_evict_stall_attempts`, force-advances `_target_anchor_index` to whichever of `{current, next}` is currently more reliable (by `_reading_unreliability`, missing data = maximally unreliable), bypassing `close_enough`/`trend_ok` — applied *after* every other gate/veto in `_select_sequential_pair_relocalization`, since those are exactly what a poisoned current can keep tripping forever.
- **(iii) `_record_next_anchor_trend` bypass**: when current is persistently unreliable and the new flag is on, the trend-quarantine disagreement check is skipped entirely for that attempt — this is Bug B's actual root cause (a bad current cannot be used as ground truth to judge next's trend; ep344 had this poison a chain of 10 false `NEXT_SKIP` quarantines).

### Phase 1.1 — `--sequential_pair_promotion_ambiguity_gate` (+ `--sequential_pair_promotion_min_confidence`, default 0.35)

Wires the existing (previously report-only) ambiguity signal into `candidate_promote` itself: a candidate whose `best_to_second_score_ratio >= current_confidence_ambiguity_gate_threshold` (reused, no new threshold) or whose own `confidence < sequential_pair_promotion_min_confidence` can no longer cast a promotable vote, regardless of `quality_ok`/`close_enough`/`trend_ok` (mirrors the existing closure-mismatch override convention — still recorded as a "no" vote, not skipped).

### Phase 1.2 — `--hint_action_arbiter_stop_veto` (+ `_stop_veto_min_confidence`=0.5, `_stop_veto_anchor_remaining_min_m`=3.0)

`hint_action_arbiter.py`: splits stop-suppression from direction-override, which previously shared one 0.90 confidence bar (below it the arbiter went silent on BOTH). A `stop` VLM output now gets its own, independently-gated suppression path using a lower confidence bar and the anchor's own static route-remaining (mirrors `stop_gate`'s own anchor-corroboration idea) — engages *before* the existing 0.90 bar, which is otherwise completely unchanged.

## 8. Testing

32 new unit tests: 9 (eviction) + 4 (ambiguity gate) added to `tests/test_reliability_gating.py` alongside the pre-existing Injection A/B/C tests; 7 in new `tests/test_hint_action_arbiter_stop_veto.py`. Full suite via `PYTHONPATH="scripts:$PYTHONPATH" python3 -m unittest discover -s tests -p "test_*.py"` (base conda env, no pytest installed — plain `unittest` works): **362 tests, 1 pre-existing unrelated failure (`test_loftr_matching`, missing `cv2` in this shell, documented pre-existing gap), 14 pre-existing skips, zero new regressions.**

## 9. Offline-replay validation against real historical episodes

Reused real `covisibility_records` + `icp_replay_dataset/anchors.json` (real `world_pose` ground truth — used to build the *exact* real anchor edge geometry via `_append_anchor(..., anchor_pose=, anchor_distance_m=)` overrides, not a straight-line approximation, which was tried first and changed behavior enough to be untrustworthy) from `vision_disagreement_ab_50ep_20260726_downgrade`'s ep344/355/19/88/95/427/205 (still present locally, not yet re-verified as pushed to this repo).

- **Ambiguity gate (1.1) — confirmed directly.** ep95 attempt 152's real ambiguous reading (conf=0.334-0.390, ratio=0.89-0.91) promotes with the gate off and is correctly blocked with it on.
- **Arbiter stop_veto (1.2) — confirmed directly.** ep205's exact real numbers at the documented failure step (d=10.76m, conf=0.200): without the flag, `low_relocalization_confidence` (silent — matches the bug); with it, `stop_veto_anchor_far` (suppressed) — robust to either candidate anchor's route_remaining value. A genuinely-close anchor (remaining=1.2m) was confirmed NOT falsely suppressed.
- **Eviction (0.2) — quarantine-bypass half confirmed, eviction-firing half could not be confirmed from this data.** Replay showed 0 false quarantines vs. 4 in baseline (matching Bug B's core claim directly). But the eviction condition itself never got to fire in the replay: **the captured `covisibility_records` only contain ICP matches for whichever anchor the ORIGINAL (buggy) live run actually queried as "next" at that moment** — once the fix (correctly) stops the original run's premature quarantine cascade, the counterfactual "next" (anchor 12) has no further captured ICP data past ~14 attempts, because the original run itself stopped querying it around then. Eviction's 30-attempt streak can never accumulate against real sensor data within this trace. **This is an inherent limitation of passive offline replay against a trace whose own behavior is what's being changed, not evidence against the fix.**

## 10. Current status / next steps

- Phase 0 and Phase 1 are implemented, tested, and offline-validated to the extent this dataset allows. Phase 2 (mechanism G's graduated near-miss band) is not started.
- **Next step: a live single-episode (or small batch) smoke test**, ideally one flag at a time per the plan's own validation checklist ("a single-variable A/B per phase... if something regresses live, a single-variable A/B is the only way to know which phase caused it") — this is specifically needed to confirm the eviction mechanism (0.2 part ii) actually fires and rescues a real live episode, which offline replay could not settle.
- **Blocked as of this writing: GPU occupied (Route2's Anchor-V2 work).** Resume once available.
- All code changes live in the dev sandbox (`NaVILA-Bench/scripts/route_memory_agent.py`, `round_trip_eval.py`, `stop_gate.py`, `hint_action_arbiter.py`, `tests/test_reliability_gating.py`, `tests/test_hint_action_arbiter_stop_veto.py`) — see `code/` in this folder for the two small fully-modified files (`stop_gate.py`, `hint_action_arbiter.py`) and both test files. `route_memory_agent.py`/`round_trip_eval.py` are too large and already carry a huge unrelated pre-existing uncommitted diff to include in full here — every new block is quoted in sections 7 above with enough context (function names, flag names) to locate and reapply directly.
