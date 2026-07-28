# 2026-07-28 — Modification plan for mechanisms A–G (see `FINDINGS.md`)

**Status update (same day, later session)**: the parallel "line 1" track mentioned below is no longer just scoped — see sibling folder `../2026-07-28-promotion-quarantine-controller-model/`. Summary: a dwell-history-aware promote/quarantine/wait classifier was trained on 288 episodes / 96,206 rows (exceeds the 0.84 single-reading AUC ceiling — promote/quarantine AUC 0.95 — because it sees the whole dwell, not one reading), validated out-of-fold against this document's own mechanism-A/B/C episodes (100% recall on both fully-frozen mechanism-C episodes, ep276 and ep646; ~1.0 recall on mechanism-A episodes 19/88/95/427), and Phases 0-2 of its integration plan (bundle format, causal online feature builder, shadow-mode CLI flag + `round_trip_eval.py` wiring, 18 unit tests, zero regressions on the existing 350-test suite) are implemented but **not yet run live** (GPU occupied by another job at implementation time). This line-2 plan (below) is unaffected by that and should proceed independently — the two tracks target overlapping but not identical failure modes (line 1 currently owns only the promotion/quarantine decision itself; mechanisms D/E/F/G below are entirely outside its scope regardless of how well it performs).

Goal: close the seven mechanism gaps found in the 16-episode return-failure audit, without touching the two confirmed confidently-wrong cases (ep539/671 — out of reach for any heuristic fix; see `2026-07-21-icp-reliability-signal/FINDINGS.md`'s 0.84 AUC ceiling). This plan covers the "line 2" (fix-the-existing-framework) track; a parallel "line 1" track (a learned decision function that ingests the same per-attempt diagnostics and directly outputs promote/quarantine/wait, replacing `candidate_promote` + `_record_next_anchor_trend` + Injection A's `bad_fraction` wholesale) is being scoped separately and is not covered here.

Every flag below defaults **off**, per this project's established convention — no validated batch's behavior changes until deliberately turned on. **Offline-replay every change against saved `covisibility_records` before any live run** (no Isaac/VLM needed — same method as `2026-07-15`/`2026-07-21`'s validations): replay the 16 episodes in this audit plus the broader ~470-episode `eval_results/` history, and confirm (a) no regression on the 8 episodes that already round-trip successfully within this batch's neighborhood, (b) a measured recovery on the mechanism-A–E episodes, before considering a live A/B.

---

## Phase 0 (quick win — do first)

### 0.1 — Diagnose mechanism D's ep205 discrepancy (pure diagnostics, no code change)

Before touching `stop_gate.py`'s corroboration logic, find out *why* `anchor_route_remaining_m > r_in and d > r_out` (both apparently true from this audit's offline reconstruction) produced `deferred` instead of `vetoed` at ep205's step≈2836. Add temporary debug logging of the exact `anchor_route_remaining`, `d`, `r_in`, `r_out` values `ReturnStopGate.check()` sees at every VLM-issued-stop attempt (not just on decision), re-run ep205 (or replay it offline against saved records if the corroboration inputs are already serialized — check `route_relocalization_diagnostics`/`phase_events` first, may not need a live re-run at all), and confirm whether this is a real bug in how `anchor_route_remaining_m` is populated at that instant, or an artifact of this audit's attempt→step timestamp approximation (which used linear interpolation between logged attempt numbers, not exact step alignment). **Do not write a fix for D until this is resolved** — the fix differs completely depending on which it is.

### 0.2 — Implement `--sequential_pair_evict_unreliable_current` (mechanism B, closes a gap planned 2026-07-21 and never built)

Per `2026-07-21-icp-reliability-signal/MODIFICATION_PLAN.md` §2 ("Injection point B"), never implemented:

- **(i) Gate the closure-reject veto on `current` being reliable.** In `_select_sequential_pair_relocalization`, only let `closure_reject_reason` force `candidate_promote = False` when `current_est`'s own reliability is above threshold (reuse `_reading_unreliability`/`reliability_quarantine_threshold`, same signal Injection A/C already use). A disagreement against an already-unreliable `current` is not evidence against `next`.
- **(ii) Explicit current eviction.** Track how many consecutive attempts `current` has been `_current_persistently_unreliable` (this bookkeeping already exists via `sequential_pair_reliability_demote_current`'s `_current_reliability_history`). Once that streak exceeds `current_evict_stall_attempts` (new, default 30 — shorter than the general 200-attempt stall-relief valve, since this is a targeted escape not a fallback), force-advance: re-seed `_target_anchor_index` to whichever of `{current, next}` has the better `_reading_reliability` score right now, skipping the normal `close_enough`/`trend_ok` promotion gates (we are not trying to confirm smooth geometric progress here, we are trying to escape a state that has already been degenerate for 30+ attempts). Prune `_promotion_distance_history`/`_promotion_score_history`/`_promotion_vote_history` for the evicted index exactly as the existing promotion path already does.
- **(iii) Extend `_record_next_anchor_trend` with the same `current_unreliable` bypass `quality_ok` already has.** When `_current_persistently_unreliable(current_idx)` is true, either skip the trend-quarantine disagreement check for this attempt entirely, or (matching (i) above) downgrade a disagreement-based quarantine vote the same way a disagreement-based promotion veto gets downgraded.

New flag: `--sequential_pair_evict_unreliable_current` (off by default). Reuses all bookkeeping already added for `sequential_pair_reliability_demote_current`/`sequential_pair_reliability_distrust_downstream` — no new signal, just a new consumer of it.

**Expected effect**: directly targets ep344/355's root cause (current poisoned from attempt 1, `_record_next_anchor_trend` treats it as ground truth for 150+ attempts). This is the single highest-confidence fix in this plan — the failure mode is fully reproduced and understood, and the fix was already designed (just not built) six days after the bug that motivates it was first found.

---

## Phase 1 (contained changes, existing infrastructure)

### 1.1 — Wire the existing ambiguity gate into promotion (mechanism A)

`current_confidence_ambiguity_gate_enabled` already exists and already computes "is this reading's `best_to_second_score_ratio` above `current_confidence_ambiguity_gate_threshold` (default 0.75)" — today it only caps the *reported* confidence for downstream consumers (`stop_gate`/`hint_action_arbiter`), it never feeds back into `candidate_promote`. Add: when the ambiguity gate is enabled and a candidate's ratio is at or above threshold, `candidate_promote` cannot be `True` for that attempt regardless of `quality_ok`/`close_enough`/`trend_ok` — an ambiguous single attempt cannot cast a "promotable" vote (it can still be recorded as a "no" vote in `_record_promotion_vote`'s bookkeeping, same convention as the closure-mismatch override in Phase 0.1's sibling fix from `CANONICAL_CONFIG.md`'s existing closure-precheck note).

Also gate on absolute `confidence`, not just `match_class`/`ratio`: require `estimate.confidence >= sequential_pair_promotion_min_confidence` (new, default 0.35 — matching the existing `min_relocalization_confidence` default so this doesn't tighten anything beyond what the rest of the pipeline already considers "has a basis to trust"). This directly targets ep95's promotions at conf 0.45–0.49 and ep19's `partial_pose_degenerate` promotion.

New flags: `--sequential_pair_promotion_ambiguity_gate` (reuses `current_confidence_ambiguity_gate_threshold`), `--sequential_pair_promotion_min_confidence` (default 0.35). Both off by default.

### 1.2 — Split `hint_action_arbiter`'s stop-veto power from its direction-override power (mechanism E)

In `HintActionArbiter.check()`, before the single `relocalization_confidence < min_relocalization_confidence → return override=False` early exit, add a *separate* branch specifically for `vlm_kind == "stop"`: if distance is clearly beyond `success_radius` by a safety margin (reuse `stop_gate`'s own anchor-corroboration idea — `anchor_route_remaining_m > r_in` from the *static*, not noisy, anchor-distance-from-start — rather than re-deriving a new signal), suppress the stop (`override=True`, `replacement_output` = a forward-toward-anchor command) even when `relocalization_confidence` is below the 0.90 direction-override bar. Keep the existing 0.90 bar untouched for actual direction overrides — this only adds a second, independently-gated action.

New flag: `--hint_action_arbiter_stop_veto_min_confidence` (default lower than 0.90, e.g. 0.5, matching `stop_gate`'s own `min_confidence`) — off by default, folds into existing arbiter config when enabled.

**Note**: this overlaps with mechanism D (`stop_gate`'s own anchor-corroboration veto). They are two different components (arbiter runs before the VLM command is finalized; gate runs after, on the executed output) with the same intent — worth checking after Phase 0.1 resolves D whether both are still needed or one subsumes the other in practice.

---

## Phase 2 (needs care — false-positive tradeoffs)

### 2.1 — Graduated boundary for Injection C's veto-suppression threshold (mechanism G)

Do **not** simply lower `reliability_quarantine_threshold` (2.5) — per `2026-07-21-icp-reliability-signal/FINDINGS.md`'s GBDT operating points, moving this knob trades recall for precision project-wide (90% recall costs 69% precision; 76% precision only buys ~50% recall), and this threshold is shared across Injection A/B/C, so tightening it to catch ep366-class near-misses will also increase false quarantines/evictions elsewhere (interacting with Phase 0.2 and Phase 1.1's new consumers of the same signal).

Instead: add a **near-miss corroboration requirement** specifically to Injection C's veto-suppression path (not the shared threshold) — when U is within a band just below 2.5 (new `reliability_near_miss_band`, default 2.5 − 0.7 = 1.8 to 2.5) rather than clearly low (U < 1.8), don't suppress the veto on a single attempt; require the same near-miss band to repeat for 2 consecutive attempts before treating the distance authority as low-reliability. This is a cheap interim heuristic — it will not resolve every near-miss (ep366's U sequence 1.85/2.01/2.11 does repeat above 1.8 for several consecutive attempts, so this specific case should catch), and it is exactly the kind of soft, graduated decision a learned function (the parallel "line 1" track) should eventually replace outright.

New flag: `--sequential_pair_reliability_near_miss_corroboration` (off by default).

---

## Explicitly out of scope for this plan

### Mechanism C (oscillating readings, ep276/ep646)

No confident heuristic fix is proposed here. A bounded "oscillation timeout" (force a decision one way or the other after N attempts stuck in a bad_fraction gray-zone, using whichever side `_record_next_anchor_trend`'s own closer-half/farther-half comparison leans toward) was considered but is a low-confidence stopgap dressed up as a threshold — it would need the same kind of offline-replay validation as everything else here, and it is precisely the failure mode most likely to be better solved by a model with access to the full dwell-window sequence rather than another hand-tuned counter (see the parallel line-1 track). Not recommending a Phase-3 heuristic attempt at this without first checking whether the line-1 model track's first iteration already handles it — duplicating effort here is the specific risk to avoid.

### Mechanism F (ep89, VLM never stops)

Zero anchor/relocalization signal implicated (final confidence 0.91, error 1.65 m — correct and confident). This is a return-phase instruction/prompt/route-hint-content investigation, unrelated to anything in `route_memory_agent.py`/`stop_gate.py`/`hint_action_arbiter.py`. Needs its own dated investigation folder, not a subsection here.

---

## Validation checklist (all phases)

1. Offline replay against saved `covisibility_records` for all 16 episodes in `FINDINGS.md` + the broader `eval_results/` history where available (episode-grouped, per `2026-07-21`'s methodology — no reading from a test episode leaks into a "training"/tuning pass for any threshold above).
2. Confirm zero regression on episodes that already round-trip successfully in the same batch/scene neighborhood.
3. Only after a clean offline replay: a live, single-variable A/B per phase (mirroring `2026-07-15`'s and `2026-07-21`'s already-established practice), not a combined all-phases-at-once launch — if something regresses live, a single-variable A/B is the only way to know which phase caused it.
4. Unit tests per new gate (mirroring the 7-test pattern `2026-07-15`'s `quarantine_next_quality` used) before any live run.
