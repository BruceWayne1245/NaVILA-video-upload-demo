# 2026-07-20 — ground-truth deep dive on `canonical_report_next_stopgate_50ep_20260719_accumulated`'s 8 outbound-success episodes

**Every number below is computed from simulator ground truth (the trajectory log's own `position`/`yaw_rad`, never the system's own confidence/estimate), not from log-text pattern matching.** 8 of the batch's 50 episodes had `outbound_success=True` (4, 367, 680, 1040, 647, 319, 295, 268); `ep319`'s measurement JSON hit the same intermittent write-corruption bug documented elsewhere and was excluded (only the top-level success fields, unaffected by the corruption, were salvageable — `outbound_success=True`, `return_success=False`). The remaining 7 (6 round-trip successes + `ep680`, the one round-trip failure in this subset) were analyzed attempt-by-attempt.

## Methodology

**Ground-truth anchor positions**: replayed each episode's outbound trajectory, accumulating `|command[:2]| × 0.02s` (control_dt) per step to get a cumulative-commanded-distance curve, then looked up each anchor's own recorded `anchor_distance_from_start_m` (from `route_relocalization_diagnostics.covisibility_records`) against that curve to get its true `(x, y, yaw)`. This is the same method (and gives 0m verified match error, confirmed against the known outbound-stop position) used in the 2026-07-19 `closure-check-and-stopgate-fixes` investigation.

**Attempt-to-step alignment**: verified empirically (not assumed) that every episode's `n_attempts ≈ (last_return_step − first_return_step) / 5`, exactly matching `--route_relocalization_interval_updates=5`. Attempt *N* (1-indexed) → `step = return_start + (N−1)×5`, confirmed across all 7 episodes to within rounding.

**closure_check replay (item 3 below) is a faithful re-implementation, not an approximation**: `_sequential_pair_closure_precheck`'s actual SE(2) algebra (`compose_pose`/`inverse_delta`/`relative_delta`/`_reproject_delta_to_anchor`, threshold-mode reconstruct/reject logic, the real 0.75m/30° precheck threshold and 1.5× quality-ratio reconstruct threshold, both read from `route_memory_agent.py`'s actual defaults) was ported and run directly against each attempt's recorded `(current, next)` pair. The one substitution: anchor-to-anchor edges use **oracle** (ground-truth world-pose difference) instead of the live **accumulated** edge chain, because this batch didn't run with `--capture_icp_replay_dataset` so the internal accumulated-edge state isn't recoverable after the fact. This is the same substitution this project's own 07-19 replay used, justified the same way (anchor pairs are 1-hop apart, drift negligible).

**hint_action_arbiter / stop_gate correctness** (items 2, 4) is judged against true bearing/true distance computed from the same ground-truth anchor positions and the trajectory's true `(x, y, yaw)` at the exact event step — never against the system's own `relocalization_confidence` or `gate_conf`.

## 1. Next/current anchor identity vs. true position

`current` and `next` are always adjacent anchors by construction (`next = current − 1`), so their anchor-count offset from the true pair is mechanically identical — one number covers both.

| Episode | Attempts | Exact match | Off by 1 | Off by ≥2 | Mean offset (m) | Median offset (m) |
|---|---:|---:|---:|---:|---:|---:|
| ep4 | 219 | 50.2% | 44.3% | 5.5% | 0.51 | 0.00 |
| ep367 | 307 | 47.2% | 38.1% | 14.7% | 0.67 | 0.92 |
| ep1040 | 392 | 38.3% | 58.2% | 3.6% | 0.65 | 1.01 |
| ep647 | 126 | 23.0% | 47.6% | 29.4% | 1.01 | 1.01 |
| ep295 | 281 | 36.7% | 40.6% | 22.8% | 0.83 | 1.01 |
| ep268 | 371 | 40.7% | 41.8% | 17.5% | 0.76 | 1.01 |
| **ep680 (fail)** | 1001 | **70.1%** | 15.6% | 14.3% | 0.47 | 0.00 |

Pooled across the 6 successes (attempt-weighted): **40.6% exact**, ~45% off by exactly one anchor, <15% off by ≥2. **`ep680` has the *highest* exact-match rate of the whole set (70.1%)** — its failure is not an anchor-identity problem; see item 5.

## 2. `hint_action_arbiter`: forced takeovers vs. gated corrections, ground-truth correctness

"Forced" = `override=true`. "Gated" = `override=false` with `reason` in `{low_relocalization_confidence, occupied_in_local_map_path}` *and* the VLM's original action actually disagreed with `desired_kind` (excludes `vlm_action_consistent`/`target_too_close`, which aren't real conflicts). Correctness is judged by bucketing true bearing to the reported `target_anchor_index` into forward/left/right (±20°) and comparing against whichever action actually executed.

| Episode | Forced | Forced correct | Gated | Gated-exec correct | Gated: should've overridden |
|---|---:|---:|---:|---:|---:|
| ep4 | 1 | 1 (100%) | 9 | 7 (78%) | 2 |
| ep367 | 3 | 3 (100%) | 11 | 8 (73%) | 2 |
| ep1040 | 8 | 8 (100%) | 16 | 8 (50%) | 5 |
| ep647 | 1 | 1 (100%) | 3 | 1 (33%) | 0 |
| ep295 | 5 | 4 (80%) | 9 | 5 (56%) | 0 |
| ep268 | 6 | 6 (100%) | 20 | 14 (70%) | 0 |
| **ep680 (fail)** | 22 | **5 (22.7%)** | 28 | 22 (79%) | 2 |

Pooled (6 successes): forced 24×, **23 correct (95.8%)**; gated 68×, exec-correct 43× (63.2%), only 9 were genuine missed corrections. **`ep680`: 22 forced takeovers, only 5 correct (22.7%)** — worse than not intervening at all. This is the most direct, most legible contributor to `ep680`'s failure found in this session.

## 3. bearing-signal reconstruction (07-19 fix): fire rate, correctness, and reject-side false negatives

"Reconstruct" fires when position/heading disagreement exceeds 0.75m/30° and one side's quality (`confidence×√inlier_count`) beats the other by ≥1.5×; "correct" = the reconstructed value lands within 0.5m/30° of true *and* is closer to true than the pre-reconstruction reading. "Reject" is the fallback when disagreement exists but neither side's quality dominates (07-19 fix: now counted as an explicit failed promotion vote instead of silently dropped); "should've reconstructed" = ground truth shows exactly one side was actually clean (<0.5m/30°) at that reject.

| Episode | Reconstructions | Correct | Incorrect | Rejects | Reject: should've reconstructed |
|---|---:|---:|---:|---:|---:|
| ep4 | 55 | 45 (82%) | 10 | 17 | 8 (47%) |
| ep367 | 48 | 48 (100%) | 0 | 103 | 75 (73%) |
| ep1040 | 159 | 137 (86%) | 22 | 58 | 46 (79%) |
| ep647 | 23 | 21 (91%) | 2 | 26 | 10 (38%) |
| ep295 | 74 | 74 (100%) | 0 | 54 | 23 (43%) |
| ep268 | 117 | 93 (79%) | 24 | 95 | 46 (48%) |
| **ep680 (fail)** | 56 | 54 (96%) | 2 | 751 | **577 (76.8%)** |

Pooled (6 successes): 476 reconstructions, **418 correct (87.8%)** — the mechanism itself is sound when it fires. But of 353 rejects, **208 (58.9%) had a ground-truth-clear correct side that the 1.5× quality-ratio gate wasn't decisive enough to pick.** `ep680` is the extreme case: 751 rejects, 577 (76.8%) should've reconstructed. **This directly corroborates `CANONICAL_CONFIG.md`'s own suspicion that the reject path is too conservative** — independent confirmation from a fresh, ground-truth-anchored replay rather than log inspection.

## 4. stop_gate: withheld-stop vs. forced-stop, ground-truth-verified

`stop_gate.py::check()` only returns `vetoed`/`deferred`/`accepted` when `vlm_issued_stop=True`; with no VLM stop attempt it's `pass` or (once anchor-corroboration confirms) `forced`.

| Episode | gate_decision counts | Final true dist-to-start (m) | Verdict |
|---|---|---:|---|
| ep4 | pass×20, forced×1 | 1.47 | forced stop correct (conf 0.46) |
| ep367 | pass×28, forced×1 | 1.55 | forced stop correct (conf 1.0) |
| ep1040 | pass×36, forced×1 | 1.47 | forced stop correct (conf 1.0) |
| ep647 | pass×9, forced×1 | 1.50 | forced stop correct (conf 0.46) |
| ep295 | pass×24, accepted×1 | 2.63 | VLM issued stop, gate accepted (only such case) |
| ep268 | pass×34, forced×1 | 2.45 | forced stop correct (conf 0.80) |
| **ep680 (fail)** | pass×80 | 7.13 | anchor-agreement streak never reached |

**`vetoed`/`deferred` (robot wanted to stop, gate withheld it) occurred zero times across all 7 episodes** — the VLM essentially never attempted an explicit stop during return in this subset (`ep295` is the sole exception, and the gate simply accepted it). **`forced` (robot didn't ask to stop, gate ended the episode anyway) fired 5 times, all ground-truth-verified correct** (final true distance 1.47–2.45m), two of them (`ep4`, `ep647`) at confidence 0.46 — exactly the band the pre-07-19 `deferred≈pass` bug would have mishandled had the VLM actually issued a stop there. `ep680` never accumulated a qualifying anchor-agreement streak at all.

## 5. ICP accuracy

Every single-role covisibility record's self-reported `(bearing, distance)` compared to the true bearing/distance to that record's own claimed anchor.

| Episode | Readings | Dist median (m) | Ang median (°) | Dist<0.5m & Ang<30° | Ang<10° alone |
|---|---:|---:|---:|---:|---:|
| ep4 | 460 | 0.049 | 2.22 | 75.0% | 74.8% |
| ep367 | 633 | 0.037 | 3.54 | 77.9% | 67.9% |
| ep1040 | 793 | 0.066 | 7.28 | 63.4% | 55.7% |
| ep647 | 252 | 0.052 | 3.39 | 78.6% | 71.0% |
| ep295 | 562 | 0.030 | 1.87 | 81.9% | 74.4% |
| ep268 | 742 | 0.076 | 3.89 | 64.4% | 64.0% |
| **ep680 (fail)** | 2002 | **0.229** | **9.71** | **47.7%** | 50.2% |

Pooled (6 successes): **72.0%** joint dist<0.5m/ang<30°, **66.5%** ang<10° alone. `ep680`'s distance median (0.229m) is ~4-6× every other episode's, and its joint rate (47.7%) is the floor of the whole set — **this is the root of ep680's failure**: everything downstream (item 3's reject-heavy closure_check, item 2's wrong-direction arbiter takeovers, item 4's stop_gate never confirming) is consistent with propagating from ICP itself being unreliable on this episode, not a separate independent bug in any of those layers.

## 6. Per-episode verdict: does it follow the intended design?

Intended design: hint tells the VLM the next-ahead anchor's distance/bearing on the return route; `hint_action_arbiter` forcibly corrects when the VLM visibly ignores it; `stop_gate` closes out the episode once truly near start.

- **ep4, ep367, ep1040, ep647, ep268 — yes**, via the same pattern: mediocre-to-decent raw ICP/anchor accuracy, but reconstruction/arbiter/stop-gate each fire rarely and are correct almost every time they do, so the layered redundancy absorbs the noise. `ep268` is the closest to a near-miss among the successes (24/117 reconstructions wrong, 6/20 gated corrections executed wrong) but the final stop_gate confirmation still landed correctly.
- **ep295 — yes, and the cleanest case**: the only episode where the VLM itself issued the return stop and the gate simply accepted it, rather than needing a forced rescue. Also has the best pooled ICP accuracy of the set (81.9% joint, 1.87° median angle).
- **ep680 — no.** Not one isolated bug: ICP accuracy collapses first (47.7% joint vs. 63-82% elsewhere), which starves `closure_check`'s quality-ratio signal of discriminating power (77% of its 751 rejects had a clear right answer it couldn't act on), which feeds `hint_action_arbiter` bad directions (77% of its 22 forced takeovers were wrong), and `stop_gate` correctly never found a trustworthy anchor-agreement streak to close on. Each layer behaved reasonably given its inputs; the inputs themselves were bad from the start.

**Overall**: the 6/7 success rate in this subset is carried by three redundant correction layers (bearing reconstruction, hint_action_arbiter, stop_gate anchor-corroboration), not by anchor tracking being accurate — true anchor-pair identity matches only 40.6% of the time pooled, and even ICP itself only clears the 0.5m/30° bar 72% of the time in successful episodes. The layers work because when they do fire, they're right the large majority of the time (87.8%, 95.8%, 100% respectively for reconstruction/forced-takeover/forced-stop). The single biggest quantified inefficiency across the whole set is **closure_check's reject path**: 58.9% (successes) to 76.8% (`ep680`) of rejects had a ground-truth-clear correct side that the 1.5× quality-ratio threshold wasn't decisive enough to select — independent, ground-truth-based confirmation of the concern `CANONICAL_CONFIG.md` already flagged from log-based analysis.

## Code

`code/` contains the analysis scripts used for this session (`deep_analysis.py` — ground-truth anchor/curve reconstruction; `se2.py` — faithful port of `route_memory_agent.py`'s closure-check SE(2) algebra; `deep_analysis2.py` — per-attempt ground-truth join, items 1/5; `deep_analysis3.py` — item 3; `deep_analysis4.py` — items 2/4; `master_report.py` — aggregation). Not committed to the main codebase; ad hoc for this session, same status as prior sessions' offline replay harnesses per the 2026-07-08 README entry.
