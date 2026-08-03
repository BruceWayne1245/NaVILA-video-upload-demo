# 2026-07-28 — Full-trajectory audit of `vision_disagreement_ab_50ep_20260726_downgrade`'s 16 return failures: confidently-wrong vs. mechanism-gap classification, and seven distinct broken mechanisms (A–G)

## 0. Context and method

Starting point was the `vision_disagreement_ab_50ep_20260726_downgrade` arm of the 2026-07-26/27 vision-disagreement A/B (see `2026-07-28-vision-ab-50ep-infra-failure` sibling investigation for the batch's infra-loss problems, which are unrelated to this document). Of 50 episodes, 27 produced a valid measurement, 24 of those had `outbound_success=True`, and **16 of those 24 failed the return leg**. This document is a full-trajectory forensic pass over all 16 (episode_idx 19, 88, 89, 95, 205, 276, 344, 355, 366, 368, 420, 427, 539, 646, 658, 671) — not a snapshot at the failure moment, but a step-by-step reconstruction of `current`/`next` anchor state across the whole return phase for each.

**Data sources used** (all already present in `eval_results/.../measurements/*.json`, no new runs needed):
- `route_relocalization_diagnostics.covisibility_records` — per-attempt ICP diagnostics (`confidence`, `inlier_count`, `icp_best_to_second_score_ratio`, `icp_near_tie_basin_count`, `match_class`) for both the `current`-role and `next`-role candidate at every relocalization attempt (`--route_relocalization_interval_updates=5`).
- `icp_replay_dataset/anchors.json` — ground-truth world pose of every outbound anchor, letting every reading be checked against the true anchor-to-robot distance at the same step (same auto-labeling method as `2026-07-21-icp-reliability-signal`).
- `trajectories/output_*.jsonl` — per-step ground-truth robot pose, used to build a `current`/`next` transition timeline by diffing `anchor_index` across consecutive covisibility-record attempts (grouping records by `attempt`, taking the two highest anchor indices present as `current`/`next`).

**Key correction made mid-session**: `route_memory`'s externally-reported `target_anchor_index` is `next` (`current − 1`), not `current`. Earlier framing of this problem (see prior session commentary, not written up here) mis-attributed `next`'s movement to `current` promoting; the corrected reconstruction — grouping covisibility records by attempt and tracking the two live anchor roles independently — is what this document is based on.

## 1. Confidently-wrong vs. mechanism-gap split

Definition used: a reading counts as **confidently wrong** iff `confidence ≥ 0.7`, `match_class == clean_full_pose` (not flagged `ambiguous_high_confidence` / `partial_pose_degenerate`), and the reading disagrees with ground truth by a sustained, meaningful margin (>1.5 m or equivalent). Everything else — low/moderate confidence, or a reading the system's own `match_class`/`ratio` already flagged as ambiguous — counts as a **mechanism gap**: the system had an honest low-trust signal available and the surrounding decision logic didn't act on it correctly.

| ep | classification | evidence |
|---|---|---|
| 539 | **confidently wrong** | `current`=5 conf=1.00, `clean_full_pose`, ratio 0.3–0.44 (decisive), reports ~0.87 m to anchor for ~30 consecutive attempts while true distance is a flat 2.37 m |
| 671 | **confidently wrong** | `current`=7 conf=1.00, `clean_full_pose`, ~20 attempts (~100 steps) while true distance grows 1.16→3.47 m before confidence finally drops |
| 658 | confidently-wrong (borderline) | promotion conf=0.79, `clean_full_pose`, ratio=0.83 (borderline), true error 3.53 m |
| 420 | confidently-wrong (borderline) | conf 0.64–0.72 (moderate, not clearly "high"), `clean_full_pose` label but ratio fluctuates into 0.82–0.95 |
| 19, 88, 89, 95, 205, 276, 344, 355, 366, 368, 427, 646 | **mechanism gap (12/16)** | see §2 |

**12 of 16 (75%) are mechanism gaps, not confidently-wrong ICP.** The system's own signals (low confidence, `ambiguous_high_confidence`/`partial_pose_degenerate` labels, near-tied `ratio`) were, in nearly every one of these, already honestly reporting distrust — the failure is in what the surrounding promotion/quarantine/stop-gate/hint-arbiter logic did (or didn't do) with that signal.

## 2. Seven distinct broken mechanisms (A–G)

### A — `candidate_promote` never checks absolute confidence or ambiguity flags
Episodes: 19, 88, 95, 427.

```python
quality_ok = current_unreliable or next_quality >= 0.85 * current_quality or no_current
candidate_promote = quality_ok and (close_enough or trend_ok or no_current)
```
(`route_memory_agent.py::_select_sequential_pair_relocalization`, ~line 1868–1880). `quality_ok` is purely *relative* (next vs. current); `close_enough`/`trend_ok` are purely geometric self-consistency on `next`'s own distance history. **Neither checks `confidence`, `match_class`, nor `best_to_second_score_ratio` directly.** Confirmed promotions that got through on this gap:
- ep19 step~2463: `match_class=partial_pose_degenerate` (explicitly flagged degenerate), promoted anyway.
- ep88 attempt205 (3→1): `match_class=ambiguous_high_confidence`, ratio=0.98 (near-tied), promoted anyway; true anchor error 3.72 m.
- ep95 attempts 188/199: conf=0.45–0.49 (the system's own confidence was already low), promoted anyway.
- ep427 attempts 226/239: `ambiguous_high_confidence`, conf=0.55, ratio=0.86–0.91, promoted anyway; true error 4.3–5.5 m.

### B — trend-quarantine's cross-check has no `current_unreliable` escape hatch (Injection B was only half-built)
Episodes: 344, 355.

`_record_next_anchor_trend` (the active quarantine mode in this batch — `sequential_pair_quarantine_mode=trend`) judges every `next` candidate purely by disagreement against `current`'s own reading, with **zero reference anywhere in the function to `_current_persistently_unreliable`**. Meanwhile the *promotion* gate's `quality_ok` explicitly has a `current_unreliable` bypass (2026-07-21 Injection B). The bypass was only wired into one of the two places that read `current` as ground truth.

Confirmed: ep344's `current` (anchor 13) at attempt 1 (the very first reading, before the robot has moved at all) already reports conf=0.44, `match_class=ambiguous_high_confidence`, ratio=0.99 (near-perfect tie) — a self-registration error of 2.54 m against an anchor the robot is standing on top of. This poisoned reference then drives 10 `NEXT_SKIP` quarantine events across the rest of the episode (anchors 12→11→10→9, then 7→6→5→4, then 3→2→1→`None`), while `current` itself only genuinely promotes twice (13→8, 8→4) — both of which are large multi-anchor jumps that just catch `current` up to wherever the skip-chain had already run. ep355 shows the identical signature (attempt-1 conf=0.75, ratio=0.93) plus a downstream physical wedge (`stuck_recovery` `wedge_detected`, never resolved).

Separately confirmed: **`--sequential_pair_evict_unreliable_current` — the fix for exactly this gap, "Injection point B" part (ii) in `2026-07-21-icp-reliability-signal/MODIFICATION_PLAN.md` — was never implemented.** `grep` for `evict_unreliable_current` across `route_memory_agent.py`/`round_trip_eval.py` returns nothing. What shipped instead (`sequential_pair_reliability_demote_current`) only relaxes the promotion `quality_ok` comparison; it does not touch `_record_next_anchor_trend` and does not evict/force-advance a bad `current` the way the original plan specified.

### C — oscillating (neither-consistently-good-nor-bad) readings fall through both promotion and quarantine
Episodes: 276, 646.

Both episodes: `current`/`next` never change **once**, for the entire return phase (231 attempts, ~1150 steps) — despite the robot genuinely moving (ep276: 6.2 m of real progress; ep646: 2.9 m in the wrong direction). `current`'s own confidence honestly and smoothly degrades over the episode (ep276: 1.00→0.58; ep646: 1.00→0.56) as its geometric error grows — it is never falsely confident, ruling out "confidently wrong" for these two. The `next` candidate's own distance readings bounce: ep276 touches 0.05 m at attempt 51 (would satisfy `close_enough` in isolation) then rebounds to 3.48 m by attempt 171; ep646 touches 0.025 m at attempt 21, then oscillates 0.35–1.13 m for 150+ attempts. Neither ever sustains 3 "good" reads inside a 5-attempt window (promotion's `bounded_evidence` requirement) nor accumulates >50% "bad" reads (quarantine's `bad_fraction` requirement) — the oscillation defeats both counters simultaneously.

This is the same gap `2026-07-21-icp-reliability-signal/FINDINGS.md` already named ("`quarantine` fired 0/13 on stuck episodes... blind to bearing... sigma-throttled to a ~2–4 m trip point") and the gap the abandoned `quarantine_next_quality` (2026-07-15, see `CANONICAL_CONFIG.md`) tried and failed to close (net regression, no stall-relief) before Injection A was built as its cascade-safe replacement. **Injection A still requires a sustained `bad_fraction > 0.5`, so it does not close this specific oscillation gap either** — it was designed for persistently-bad, not for oscillating.

### D — `stop_gate`'s anchor-corroboration safety net (only path that can veto a low-confidence VLM stop) didn't fire when it should have
Episodes: 205, 276 (final stop), 368, 427, 646.

`ReturnStopGate.check()` (`stop_gate.py`), VLM-issued-stop branch: if `distance_authority_low_reliability` (Injection C) → `deferred`; else if `not high_conf` → `deferred` **unless** `anchor_corroboration_enabled and anchor_route_remaining_m > r_in and d > r_out`, in which case → `vetoed`. This is the **only** path that can block a low-confidence wrong stop.

Spot check on ep205's stop (step ≈2836): `d` (gate authority distance) = 10.76 m (≫ `r_out`=3.0), and anchor7's static `distance_from_start_m` (used as `anchor_route_remaining_m`) = 7.05 m (≫ `r_in`=3.0) — by the code above, both corroboration conditions read as satisfied, which should force `vetoed`. The logged decision was `deferred`. **This specific discrepancy is not yet root-caused** — either a real bug in how `anchor_route_remaining_m` is populated/read at decision time, or an artifact of this analysis's attempt→step approximation being imprecise at that instant. Flagged as an open diagnostic item, not fixed here (see `MODIFICATION_PLAN.md` §D).

Note this mechanism is partly a downstream symptom of A/B/C: `anchor_route_remaining_m` is a static per-anchor quantity, so if `next` got to its current index via an illegitimate A/B/C-driven skip/promotion, corroboration will also look satisfied for the wrong reason.

### E — `hint_action_arbiter` couples "correct my direction" and "block my stop" under one confidence bar
Episodes: 368 and, as background context, most of the D-group.

`HintActionArbiter.check()` (`hint_action_arbiter.py` line 241–242):
```python
if relocalization_confidence is not None and relocalization_confidence < self.cfg.min_relocalization_confidence:  # 0.90
    return HintActionDecision(override=False, reason="low_relocalization_confidence", ...)
```
A single 0.90 confidence bar gates *both* "should I override the VLM's chosen movement direction" (a genuinely risky action to take under uncertainty — reasonable to require high confidence) and "should I suppress a `stop` output" (a much lower-stakes, more conservative action — only needs "probably still far," not "definitely know which way to go"). Below 0.90 confidence the arbiter goes silent on both, so an erroneous voluntary stop under low confidence sails through unchallenged unless `stop_gate`'s own (also-gapped, see D) corroboration path happens to catch it.

### F — VLM never issues a stop at all (decision-layer, out of scope for the anchor/relocalization framework)
Episode: 89.

67/67 `stop_gate` checks in this episode are `pass` (neither `forced` nor `vetoed` nor `deferred` — meaning the VLM literally never produced parseable stop-intent text across ~5000 return steps), even though the final localization was accurate and reasonably confident (conf=0.91, error=1.65 m). No anchor/ICP signal is implicated. Listed here for completeness of the 16-episode classification but explicitly **out of scope** for the fixes in `MODIFICATION_PLAN.md` — needs its own investigation into the return-phase instruction/prompt design, tracked separately.

### G — Injection C's absolute-reliability threshold is a hard cutoff; ep366's veto sat just under it
Episode: 366.

The most dramatic single moment in this batch: the robot is physically at 0.43 m from home (step 4633, well inside `r_in`=3.0) but `stop_gate` `vetoed` three consecutive attempts (steps 4626/4636/4646) on `d`=4.53 m, conf=0.627 — blocking any chance to register the arrival. Computed the same U-score Injection C uses (`_reading_unreliability`) for `current` at those exact attempts: **1.85, 2.01, 2.11, 1.08, 2.14 — all below `reliability_quarantine_threshold=2.5`.** Injection C's downstream-distrust cap genuinely did not trigger, because by its own criterion this reading wasn't unreliable *enough*. This is not a bypassed safeguard; it's a threshold sitting close to, but on the wrong side of, this specific near-miss — the same phenomenon `2026-07-21-icp-reliability-signal/FINDINGS.md` calls the "~0.84 AUC ceiling," here manifesting at a moderate (not high) confidence level rather than the "confidently wrong" tier-(c) extreme.

## 3. Summary table

| Mechanism | Episodes | Root component | Fix exists in prior planning? |
|---|---|---|---|
| A | 19, 88, 95, 427 | `_select_sequential_pair_relocalization`'s `candidate_promote` | No — new |
| B | 344, 355 | `_record_next_anchor_trend` (no current-unreliable escape hatch) | **Planned 2026-07-21, never implemented** (`sequential_pair_evict_unreliable_current`) |
| C | 276, 646 | Promotion `bounded_evidence` + quarantine `bad_fraction`, both blind to oscillation | Partially — `quarantine_next_quality` (07-15) attempted and was reverted; Injection A doesn't close this either |
| D | 205, 276, 368, 427, 646 | `stop_gate`'s anchor-corroboration veto path | Root cause on ep205 not yet found |
| E | 368 (+ background) | `hint_action_arbiter`'s single confidence bar for two different actions | No — new |
| F | 89 | VLM decision/prompt layer | Out of scope, needs separate track |
| G | 366 | Injection C's hard 2.5 threshold | Calibration/graduated-boundary question, not a bug |

See `MODIFICATION_PLAN.md` for the proposed fixes, phased by confidence/cost.
