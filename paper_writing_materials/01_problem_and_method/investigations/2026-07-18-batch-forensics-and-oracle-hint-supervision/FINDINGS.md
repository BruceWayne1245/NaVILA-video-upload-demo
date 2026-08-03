# 2026-07-18: Batch 1/2/3 forensics, hint-vs-hint_action causal split on the 07-15 baseline failures, and a new oracle-supervised hint/hint_action interception experiment

## 0. Context and what this document covers

Three 22-episode live A/Bs were launched 2026-07-16 to test three independent, non-stacking mechanisms on top of the "Variant 1" `sequential_pair` baseline (see `investigations/2026-07-16-*`): `current_confidence_ambiguity_gate` (batch 1), `short_baseline_require_resolution` (batch 2), `motion_integrated_multiframe_submap` (batch 3). This document covers everything done in the 2026-07-18 session: (1) discovering and fixing a chain-script bug that left batch 3 stuck for ~39 hours, (2) a deep forensic analysis of batch 1 and batch 2's results against the reference baseline, (3) a follow-up precision/recall check of the confidence-ambiguity gate against ground truth, (4) a causal root-cause split of the reference baseline's 8 known return-failures into "bad hint text misled the VLM" vs "VLM drifted independently and the active-correction mechanism didn't help," and (5) a new research-only oracle-supervised interception experiment motivated by that split, implemented and queued to run on the full 50-episode set.

**Reference baseline throughout**: `shadow_hint_swap_50ep_20260714_accumulated` (same 22/50-episode Variant-1 config, no 07-16 additions). On the 22-episode subset shared with batches 1/2/3, this run produced **14 successes / 8 failures = 63.6%** (all 22 outbound-succeeded in that run): successes = `{4,5,187,368,408,1040,89,647,1038,430,500,295,268,488}`, failures = `{134,367,994,319,708,498,354,214}`.

## 1. Batch 3 was silently stuck for ~39 hours — root cause and fix

`chain_multiframe_submap_after_short_baseline_20260716.sh` polled `run_22ep_short_baseline_require_resolution_20260716_master.log` for a `[master] batch finished` line. That file was never created: batch 2 was actually invoked directly by `chain_short_baseline_after_confidence_gate_20260716.sh` (no separate output redirection of its own), so its entire output landed in `chain_short_baseline_after_confidence_gate_20260716.log` instead. The polling script looped `sleep 30` indefinitely against a file that would never exist, from 2026-07-16T18:50 to (undetected) 2026-07-18T09:53 — roughly 39 hours.

Also found: an orphaned Isaac Sim process from batch 1's `ep268` timeout (recorded `exit_code=124` in `summary.tsv`) never exited and was still running 43h later, holding ~4.3GB GPU memory at 0% utilization — the same recurring "Isaac Sim doesn't exit cleanly after a timeout/crash" class of bug documented since 2026-07-05.

**Fix**: killed the orphaned process group, then launched batch 3 directly (`nohup bash run_22ep_multiframe_submap_20260716.sh > run_22ep_multiframe_submap_20260716_master.log 2>&1 &`, confirmed `PPID=1`, fully detached). This log path is confirmed correct going forward. Batch 3 started 2026-07-18T09:55:25, expected ~6-7h.

## 2. What batch 1 and batch 2 actually changed, code-level

Diffed `route_memory_agent.py` between the 2026-07-15 baseline code snapshot and each 2026-07-16 investigation's own `code/` snapshot.

**Batch 1 — `current_confidence_ambiguity_gate`** (`investigations/2026-07-16-current-role-confidence-ambiguity-gate/`): per return-phase attempt, if the "current" role's `best_to_second_score_ratio >= 0.75` (the same yaw-basin-competition signal already validated for the "next"-role `quarantine_next_quality` mechanism, now reused for "current," a role nothing else in the pipeline monitors), caps the *reported* `relocalization_confidence` to `min(confidence, 0.5)` — a hard floor, stateless (re-derived fresh every attempt, no persistent counter). This only affects downstream reporting (`hint_action_arbiter`'s 0.90 confidence gate, `filter_std_m`); it never touches promotion voting, closure-check, or the underlying estimate itself. Designed as an "abstain, don't ban" mechanism, explicitly to avoid repeating 2026-07-15's `quarantine_next_quality` cascade-with-no-release-valve bug.

**Batch 2 — `short_baseline_require_resolution`** (`investigations/2026-07-16-short-baseline-require-resolution/`): the pre-existing `short_baseline_disambiguation` diagnostic (compares two return-phase views of the same "next" anchor ≥0.3m apart) was found to resolve on only 0.1% of live events historically — root-caused this session to `bounded_evidence`'s *normal* multi-vote promotion path routinely completing before 0.3m of travel accumulates (not the rare single-attempt bypass, as first hypothesized). Fix: withholds promotion (`promote=False`) while a pending disambiguation entry is unresolved, bounded by a `stall_attempts=60` release valve (never permanently blocks, same "abstain, don't ban" family as batch 1).

## 3. Round-trip outcomes and per-episode flips vs. the reference baseline

Conditioning on outbound success *within that specific run* (established project methodology — VLM outbound-phase stochasticity is a known confound):

- **Batch 1**: 11 comparable episodes, **5/11 = 45.5%**. Flips vs. baseline: `ep5` S→F, `ep89` S→F, `ep500` S→F (regressions); `ep367` F→S (improvement).
- **Batch 2**: 16 comparable episodes, **7/16 = 43.75%**. Flips vs. baseline: `ep187` S→F, `ep89` S→F, `ep500` S→F, `ep295` S→F, `ep268` S→F, `ep430` S→F (six regressions); `ep994` F→S (one improvement).

Both are well below the reference baseline's 63.6%.

## 4. Did each mechanism do its job? (firing rate, then precision/recall)

**Firing rate** (via the `confidence == 0.5` exact-value fingerprint, confirmed a clean proxy — zero false hits in any gate-off run checked): batch 1's gate fired far more than its own offline pilot anticipated — per-episode `gate_floor_rate` ranged 0% (e.g. `ep368`) up to **94.2%** (`ep5`, 65/69 attempts), 87.9% (`ep214`), 77.8% (`ep319`). The offline pilot only modeled the 8 known 07-14 return-failure episodes' dwells; it never characterized firing behavior on episodes like `ep5`/`ep500`/`ep488` that were 07-14 *successes*.

Batch 2's mechanism cannot be directly instrumented from the output JSON (no "promotion withheld this attempt" field exists) — the only observable proxy, `anchor_heading_reliable` flipping to `False`, **never fired once across all 16 comparable episodes**. Dwell/promotion-count differences vs. baseline are present but modest. Verdict: engaged only mildly, neither its intended benefit nor any clear harm is visible via its own designed channel.

**Precision/recall of batch 1's gate against real Isaac-oracle ground truth** (n=5,466 current-role attempts across 15 episodes; ground truth = anchor's true `world_pose` transformed into the robot's true body frame at the aligned trajectory row, independent of the shadow's own ICP estimate):

| Threshold for "actually wrong" | Precision | Recall | FPR |
|---|---|---|---|
| bearing error > 45° | 0.727 | 0.852 | 0.262 |
| bearing error > 20° | 0.833 | 0.812 | 0.191 |

This **matches or slightly beats** the mechanism's own offline-calibrated numbers (re-checked exactly: the CODE_CHANGE doc's cited "TP=97.6%/FP=41.1% at 0.5" are recall/FPR on a curated bimodal subset, not precision — like-for-like, live recall 0.852 vs. offline 0.801, live FPR 0.262 vs. offline 0.344, i.e. live is *better*). This is unusual for this project — most mechanisms degrade live relative to offline promise (e.g. `short_baseline_disambiguation`'s 0.1%/0% collapse). **The gate's underlying detector signal genuinely holds up.**

But precision is **highly route-dependent, not uniform**: near-perfect on genuinely self-similar routes (`ep5`: precision 0.99, recall 1.00 — 955/1001 fires were real >45° errors), near-coinflip elsewhere (`ep214` 0.48, `ep319` 0.41), and on low-firing-rate episodes the rare fires are mostly false alarms (`ep367`: 5.2% fire rate, precision 0.20; `ep295`: 11.3% fire rate, precision 0.03).

## 5. Root-causing the specific flipped episodes

**`ep5` (batch 1, S→F)**: true `position`/`speed_mps` shows the robot frozen at `(1.9, 3.37, 0.27)`, speed ≈0.001 m/s, for 4,567/5,001 = 91.3% of the entire return phase (the pre-existing "robot physically stops moving" locomotion-policy bug, documented since 2026-07-06/07 on `ep5`/`ep408`) — not a relocalization defect. **But** during the entire frozen stretch, the confidence gate forces `confidence=0.5`, so `hint_action_arbiter` reports `reason="low_relocalization_confidence"` and `override=False` for literally all 5,001/5,001 steps — the gate (correctly, per §4's precision check) never once let the one mechanism that might have attempted a corrective action engage. A real, secondary, gate-attributable cost layered on top of a pre-existing unrelated bug — not a false alarm, but an unhelpful response to a correct alarm.

**`ep89` (both batches, S→F)**: nearly identical failure signature in both — batch 1 frozen 62.0% of return, final true distance 2.51m; batch 2 frozen 35.5% of return, final true distance 2.50m — despite batch 2 having the confidence gate confirmed *off*. Baseline `ep89` shows zero freeze, smooth progress, succeeds. **Strongest evidence that this specific regression is a shared confound (route/locomotion-policy prone to sticking near ~2.5m on a bad day) independent of either new flag.**

**`ep500` (both batches, S→F, different mechanisms)**: batch 1 reaches a true minimum distance of 0.149m at 75.8% of return (essentially arrives) but `stop_gate` never fires (`gate_decision="pass"` throughout) and the robot drifts back out to 5.77m — an ordinary stop-decision failure, not gate-related (arbiter reason there is `target_too_close`, pre-existing). Batch 2: true distance actually *increases* mid-return (7.42→13.96m, a genuine wrong-direction excursion) with no freeze and no anomalous dwell — an ordinary VLM navigation-stochasticity failure, unrelated to promotion-withholding.

**Batch 2's other four regressions** (`ep187`, `ep295`, `ep268`, `ep430`) show minor freezes or mid-return wander-then-partial-recovery patterns, none showing the withheld-promotion signature.

**Improvements** (`ep367` batch 1, `ep994` batch 2) both look like ordinary favorable rollout variance — `ep367`'s gate-floor-rate was only 2.8%, too rare to explain a 7.38m→1.81m turnaround.

**Part-D verdict**: the 45.5%/43.75% gap vs. 63.6% is mostly *not* a systematic effect of either mechanism — dominated by ordinary run-to-run locomotion/VLM stochasticity plus the pre-existing freeze bug. Batch 1's gate is a real, secondary aggravating factor specifically on already-frozen episodes (by correctly detecting ambiguity and then silencing the one corrective channel via a response strategy, "ambiguous → fully defer to VLM," that isn't well-suited to an already-stuck robot). Batch 2's mechanism looks close to inert on this data — its offline validation was explicitly incomplete when launched, and this run doesn't settle whether it helps. **Neither mechanism should be judged confirmed-bad (unlike 07-15's `quarantine_next_quality`, which had a proven deterministic cascade bug) nor confirmed-good; a larger-n rerun is needed before any keep/revert decision.**

## 6. Root-cause split of the reference baseline's 8 known failures: hint vs. hint_action

User-requested distinction: **"hint"** = the informational bearing/distance/vector text injected into the VLM's prompt (passive). **"hint_action" / `hint_action_arbiter`** = the separate active-override mechanism that can replace the VLM's chosen action outright. Checked `investigations/2026-07-15-50ep-batch-current-next-simultaneous-failure/FINDINGS.md` first (per project convention, GitHub is the source of truth) — it establishes that bearing error correlates with the failing episodes and that the system dwells on 1-3 bad anchors for 30-73% of return, but does **not** do the precise timing/causal ordering split requested. Fresh ground-truth timeline reconstruction (hint bearing error vs. Isaac-oracle anchor `world_pose` over time, `hint_action_arbiter`'s per-step reason/override log, true `distance_to_start_m` trend) for all 8:

**Category A — hint led the VLM astray (bad hint content precedes/explains the drift), 4/8: `134, 367, 319, 214`.**
- `134`: bearing error already 40.1° *before* the dominant anchor-7 dwell (worsens to 63.6-69.6° during it); the arbiter is actively *enforcing* the bad reading (`vlm_conflicts_with_clear_hint` fires 12/30 times during the dwell) — the strongest direct case: the active-correction mechanism is amplifying an already-wrong hint.
- `367`: bearing error 90.6° even before the dominant dwell, worsening to 139-161° and sustained (108-168°) through the terminal window; arbiter mostly self-blocked (`low_relocalization_confidence` 27/36 during the dwell, ~100% in the tail) — purely the raw hint text doing the damage, not amplified action.
- `319`: a specific, confident, wrong number — the final hint event reads "route anchor A1 is 0.58m away" while true distance is 6.94m; bearing error 61-68° through the whole 9-event dominant-anchor window. Arbiter blocked throughout (irrelevant to the outcome).
- `214`: bearing error 118-172° essentially the entire episode (worst of the 8), arbiter 100% correctly self-blocked — but the raw hint text alone is severely and continuously wrong.

**Category B — VLM drifted independently, hint_action never got a fair chance to help, 3/8: `994, 498, 354`.**
- `994`/`498`: in the failure window, the hint correctly degrades to the hedged "position uncertain (σ≈4-5m, filter lost lock)...do NOT stop until you visually confirm" wording, confidence 0.35-0.48, arbiter appropriately abstains every step — yet true distance still climbs (994: 7.92→11.34m; 498: 8.15→8.65m), the robot moving *away* from start against explicitly-correct guidance. The hint content is not at fault; nothing was available to actively correct the VLM's own bad decision.
- `354` — the cleanest B case: hint error is bad early (52.0° mean, arbiter correctly blocked 69/74=93% of the time) but becomes genuinely **accurate** during the 45-event terminal dwell (5.2-5.5° error) — **and the arbiter still never overrides once** (`low_relocalization_confidence` 45/45 for the whole terminal window), true distance stuck 8.46→7.69m until timeout. This is the strongest evidence that the arbiter's confidence gate may be reading a stale/lagged signal rather than reacting to the current attempt's (by-then-good) confidence — not yet investigated further, flagged as a concrete lead.

**Mixed/inconclusive, 1/8: `708`** — hint is bad and arbiter abstains throughout (consistent with A), but true distance plateaus rather than actively drifting (robot may be independently stalled) — can't cleanly attribute.

**Summary**: roughly half the known failures (4/8) are genuinely hint-content-driven; the other half (3/8) are VLM-decision/arbiter-engagement failures where a more accurate hint alone would not have helped (better active correction, or fixing the `354`-style stale-confidence-gate hypothesis, would matter more there).

## 7. New experiment: oracle-supervised hint/hint_action interception

Directly motivated by §6: quantify the *recoverable upper bound* if a privileged oracle could perfectly filter out inaccurate hints (Category A) and block badly-informed active corrections, while leaving Category B (already-accurate-hint, VLM-decision) failures untouched as an expected floor.

**Design** (user-specified): run the exact 07-15/07-14-baseline code path (Variant 1 `sequential_pair`, no 07-16 additions — `current_confidence_ambiguity_gate`, `short_baseline_require_resolution`, and `motion_integrated_multiframe_submap` are all deliberately left off, to isolate this experiment against the exact reference-baseline code), with two new independent, off-by-default, research-only oracle-supervision filters:

- `--oracle_hint_supervision` (+ `--oracle_hint_bearing_error_threshold_deg`, default 10.0): each return-phase VLM step, compares the hint about to be injected against Isaac's privileged ground-truth bearing to the same target anchor; if the disagreement exceeds the threshold, suppresses the specific numeric hint text and falls back to the pre-existing hedged "position uncertain...do NOT stop" wording instead.
- `--oracle_hint_action_supervision` (+ `--oracle_hint_action_bearing_error_threshold_deg`, default 45.0): independently, if that same ground-truth bearing error exceeds this (higher) threshold, forces `hint_action_arbiter`'s override decision to not execute for that step, regardless of what the arbiter itself decided.

Both thresholds are evaluated from the same single per-step ground-truth computation but gate two different, independent downstream consumers (hint text visibility vs. action execution); either flag can be used alone.

**Implementation** (`/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/`, snapshotted in `code/` alongside this document):
- `route_memory_agent.py`: new `RelativeStartProgress.oracle_supervision_suppressed: bool = False` field; `_make_anchor_hint`'s hedge-branch condition extended from `if self._filter_lost(progress):` to `if self._filter_lost(progress) or progress.oracle_supervision_suppressed:`. This is the only change to this file — `RouteMemoryAgent` itself never reads oracle state; the flag is purely set externally.
- `round_trip_eval.py`: new helper `oracle_true_bearing_error_to_anchor_deg(env, route_agent, anchor_index, reported_bearing_deg)`, built from the pre-existing `pose_delta_body`/`get_robot_pose`/`signed_angle_diff` primitives (same convention as the existing `oracle_anchor_segment_return_yaw` helper); independently verified via a standalone numeric sanity check (synthetic robot/anchor poses, confirmed correct bearing and error signs, including under a 90° robot yaw rotation). Four new CLI flags as described above. Wired into the main return-phase step loop: the ground-truth bearing error is computed once per VLM query step (immediately after `route_query_progress` is resolved, before hint injection); if `--oracle_hint_supervision` triggers, `route_query_progress` is wrapped via `dataclasses.replace(..., oracle_supervision_suppressed=True)` before being passed to `inject_hint` (and logged as an `oracle_hint_supervision_suppressed` phase event with the measured error); if `--oracle_hint_action_supervision` triggers (checked after `hint_action_arbiter.check()` returns), `_last_hint_action_decision` is replaced via `dataclasses.replace(..., override=False, reason="oracle_hint_action_supervision_blocked(<original reason>)")` before it can affect the executed action.
- `tests/test_route_memory_agent.py`: two new tests — `oracle_supervision_suppressed=False` reproduces byte-identical hint text to before the field existed (no-behavior-change guarantee), `oracle_supervision_suppressed=True` correctly falls back to the hedged wording while still naming the anchor.

**Validation**: `py_compile` clean on both modified scripts; full suite via `PYTHONPATH=scripts python3 -m unittest discover -s tests` — 261 tests, zero regressions, only the pre-existing unrelated `cv2`-missing import error in `test_loftr_matching.py` (not caused by this change).

**Live batch, full 50-episode set** (same episode list as `shadow_hint_swap_50ep_20260714_accumulated`, i.e. NOT restricted to the 22-episode subset used by the 07-16 batches), same base config as that reference batch plus only the two new flags at their default thresholds (10°/45°). Run tag `oracle_hint_supervision_50ep_20260718_accumulated`. Queued to launch automatically once batch 3 (`shadow_multiframe_submap_22ep_20260716`) finishes, via `chain_oracle_hint_supervision_after_multiframe_submap_20260718.sh` (confirmed polling the correct log path this time).

**How to apply, once results land**: compare round-trip success against the 63.6% (14/22) reference on the same 50 episodes; check the new `oracle_hint_supervision_suppressed` phase-events and `oracle_hint_action_supervision_blocked(...)` reason strings to quantify how often each filter fired; specifically check whether the 4 Category-A episodes (`134,367,319,214`) recover under this experiment (the direct test of §6's hypothesis) — Category-B episodes (`994,498,354`) are not expected to improve (their hints were already accurate or correctly hedged) and should be treated as an expected floor, not a surprise if they remain failures.
