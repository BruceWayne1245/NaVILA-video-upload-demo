# ICRA code and existing-log audit

## DISCREPANCIES

1. **Table I OHA outbound count:** paper request says 45; frozen matched-M50 TSV recomputes **44** (`final_data2/pure_oracle_hint_action_highsuccess100ep_20260812_matched50_full_results.tsv`, field `outbound_success`; `analysis/outbound_consistency.py`). The package's own `final_data2/README.md` also says 44. Likely the manuscript copied a different summary revision.
2. **“bearing threshold 0.90”:** `0.90` is `HintActionArbiterConfig.min_relocalization_confidence`, not the learned bearing-reliability threshold (`main_pipeline/hint_action_arbiter.py:31-45,417-440`). The learned head authorises when `p_bearing_bad_30 <= 0.3204705300`; the artifact also uses 0.2645655892 (distance) and 0.3017010986 (pose). Calling 0.90 the threshold of `r_bearing` conflates two different signals.
3. **FO forced STOP count:** matched-M50 logs contain **28 forced terminal events in 28 episodes**, not 5 (`analysis/terminal_verifier.py`, `analysis/terminal_verifier_events.csv`). The documented 5/5 is from the earlier `canonical_report_next_stopgate_50ep_20260719` *eight-outbound-success subset* (`investigations/CANONICAL_CONFIG.md:73`), not Table I's August M50.
4. **ON terminal result:** its matched TSV has 28 `return_success=True` but 27 `round_trip_success=True`; this is the single outbound-failed episode and is why all Return-decision statistics must first filter `outbound_success=True`.

## A. Outbound repeatability

### A1/A2 code path and determinism

The six actual snapshots are in `analysis/config_snapshots.md`. All use the same task, checkpoint (`load_run=2024-09-25_23-22-02`), history length, phase-prompt instruction provider and episode ids. Instruction selection is identical at `main_pipeline/round_trip_eval.py:3342-3358`; initial/goal poses and the common 100 s limit are set at `:3368-3387`. Return-only arbitration/recovery is phase-guarded at `:4256-4268`; success transition occurs only after outbound STOP at `:4351-4375`. No batch supplied a seed. **No outbound-changing flag difference was found.** GEO's deterministic controller is explicitly return-only.

Determinism audit: decoding is greedy (`main_pipeline/vlm_server.py:149-153`, `do_sample=False`, `temperature=0`), so sampling/top-p is not a source. Every VLM server uses 8-bit loading (`vlm_server.py:57-67` and batch launch); no deterministic-algorithm/cublas workspace setting is present, so deterministic 8-bit CUDA kernels are **NOT FOUND / not guaranteed**. Simulator/render GPU determinism controls are also **NOT FOUND**. Wall clock is used only to time generation (`vlm_server.py:148,161`), not to select an action; per-episode shell timeout is operational, not a decision rule. Thus logs establish run-to-run divergence, but do not uniquely attribute it to quantisation versus Isaac GPU execution.

### A3/A4 result

Counts are L/OH/OHA/FO/ON/GEO = **50/43/44/43/49/46**; mean 45.83/50 (91.7%), range 7 episodes. Across six runs: 29 episodes always succeed, 0 always fail, 21 flip. Of flips, 19 succeed in five runs and 2 in three runs. `analysis/outbound_consistency_M50.csv` contains all 50 rows. The first differing outbound query/action across each flipped episode's six logs has median/Q1/Q3 **0/0/0**, range 0–6 (query index, not simulator step); this is computed by `analysis/outbound_consistency.py`. GEO uses exactly the same 50 episode IDs and its 46 is therefore the same M50 cohort.

## B. Reliability definition

The actual outputs are calibrated error probabilities, not direct ICP fitnesses:

`r_bearing = 1 - p_bearing_bad_30`, `r_distance = 1 - p_distance_bad_0p5`, `r_pose = 1 - p_pose_bad`.

For each head, the portable artifact evaluates every tree, adds its leaf to the model baseline, applies sigmoid, then Platt calibration `sigmoid(slope*logit(p_raw)+intercept)` (`reliability_v11_portable_runtime.py:87-102`). Constants (bearing/distance/pose slope, intercept) are respectively (0.8108613163, 0.0976726123), (0.8319662514, 0.2042459419), (0.8779663182, 0.1288856931). The result lies in [0,1]. In reliability form the authorisation thresholds are respectively **0.6795294700, 0.7354344108, 0.6982989014** (equivalent bad-probability thresholds 0.3204705300/0.2645655892/0.3017010986). Code comparison is at `reliability_v11_portable_runtime.py:109-125`; constants are in `artifacts/reliability_v1_1_portable_shadow.json`, `heads.*`.

All heads consume the same 249-feature vector but have separate HGB trees and calibrators. Inputs include raw ICP confidence, inliers, overlap and residuals; four basin scores/residuals/transforms and margins; Scan Context yaw/region measures; localizability eigenvalues; current/next pair differences; and temporal windows 4/8/16/32. The exact exhaustive list is artifact `feature_names`. The deployed consumer then uses **AND**, `jointly_trusted=all(trusted.values())`, and spends that one joint gate on anchor promotion, route hint, action override, forced stop and stop veto (`v11_portable_runtime.py:109-125`; `v11_consumer_policy_v2.py:231-280`; consumer config `guarded_operations`). Therefore the deployed system is already a shared joint gate downstream, even though it has three model heads upstream.

Odometry: actual ON CLI includes neither `--measured_odometry` nor `--leg_odometry`. The fallback nevertheless integrates commanded action deltas into `_return_pose_from_return_start` (`route_memory_agent.py:1395-1407`; selection at `round_trip_eval.py:4561-4572`), so (a) route-state prior uses **command dead reckoning**, not measured odometry; (b) sequential candidates are the persisted current+next pair, not odometry-selected (`route_memory_agent.py:1040-1045`); (c) an ICP initial-guess input is **NOT FOUND** in the frozen relocalizer. This is not “no odometry”: it uses command integration.

`analysis/reliability_distributions.csv` exports the authoritative `next` role's 16,418 scored attempts. Quantiles (p10/p25/median/p75/p90): bearing **.103/.185/.445/.980/.995**; distance **.026/.081/.250/.996/.999**; pose **.008/.017/.058/.988/.997**. These are learned reliabilities; the paper's median 0.667 refers to legacy `relocalization_confidence`, not any of these heads. On the 1,579 eligible Return decisions, 1,009 have legacy confidence <.90, but only 979 return `low_relocalization_confidence`: the exact 30-step difference is the subset with confidence <.90 that returns earlier as `target_too_close` because distance is checked first (`hint_action_arbiter.py:387-390` before `:417-440`). It is not coincidence.

## C. Stuck recovery

Trigger is eight consecutive VLM-query displacements <0.15 m, believed home distance >5 m, VLM not stopping, and attempts <5 (`stuck_recovery.py:188-212`). It turns approximately 180° in 45° commands (flips direction after two <12° yaw-progress queries), drives forward until net 0.8 m, then faces the next-anchor bearing; each attempt is capped at 12 queries by the actual CLI/default wiring (`round_trip_eval.py:4063-4076`; state machine `stuck_recovery.py:131-186`). No explicit cooldown exists; reset clears the detector. It is last/highest-priority action override but never writes relocalisation, reliability or stop state (`round_trip_eval.py:4256-4284`; module contract `stuck_recovery.py:19-20`).

Enable matrix from configs: L/OH/OHA/FO/GEO are OFF in both phases; ON flag is present but the call is guarded by `phase == "return"`, hence ON Outbound OFF / Return ON. Logs: ON has **15 triggers in 11/50 episodes (22%), median 0**; 2/27 successful round trips triggered it. Every other config has zero because disabled. See `analysis/stuck_recovery_triggers.csv` and `analysis/stuck_recovery_stats.py`. GEO failure upper bound based on terminal N-step displacement is **NOT FOUND**: two GEO result directories are missing and a defensible common terminal window was not reconstructible from all 50 recovered outcomes; do not report an experimental rescue estimate.

## D. Wrong override

Ground truth uses each anchor's logged simulator `world_pose` and each query's simulator position/yaw. Quantisation reuses the arbiter's ±15° forward cone and bearing sign (`hint_action_arbiter.py:20-25,377-445`); CSV script is parameterised by run tag.

Among 130 executed ON overrides, **124 correct (95.4%) / 6 wrong (4.6%)**. Successful episodes: 4/67 wrong (6.0%); failed episodes: 2/63 (3.2%). The maximum episode wrong run is 2; all others are isolated. For the 12 conflict overrides blocked by Policy V2, **2 were correct (gate false negatives) and 10 wrong (gate true positives)**. Thus this existing run directly shows the guard removed 10 wrong interventions at a cost of 2 correct ones. Per-event and episode aggregates are in `analysis/override_correctness_online.csv`; implementation is `analysis/override_correctness.py`.

## E. Evaluation and paired subsets

Return success is explicitly simulator XY distance to **the outbound episode's `start_pos`**, strictly `< success_radius`, at a valid stop (`round_trip_eval.py:3377-3387,4377-4389`); it is not distance to the reverse episode's goal. Measurement records confirm `success_requires_stop=True` (`:4847-4853`).

Reverse-neighbour identity is logged, but its goal coordinates are not stored in the frozen result and the source R2R dataset location is not part of the portable run directory. Therefore the requested 1.77 m/5.52 m recomputation and >3 m subgroup test are **NOT FOUND**; `analysis/reverse_goal_offset.csv` records this per episode rather than substituting terminal distance.

Five-way common Outbound set has **|S_all|=31**. SR on it: L 8/31=25.8%, OH 12/31=38.7%, OHA 21/31=67.7%, FO 26/31=83.9%, ON 19/31=61.3%. IDs and adjacent pairs (n=43,37,38,42) are in `analysis/table1_common_subset.csv`, generated by `analysis/table1_common_subset.py`. AR is not separately identifiable from the frozen TSV (only terminal success flags), so the CSV currently equals SR and must be treated **NOT FOUND**, not as a distinct arrival metric. GEO is excluded from the paper-defined S_all; its 46 means its own Outbound successes. Claims that all three prose occurrences of “46 common” are the same set are false unless rewritten: GEO∩ON Outbound has 45, GEO∩L has 46.

## F. Table II denominator

Exact ON decomposition: all 1,579 = 979 withheld + 600 authorised. On denominator 600: consistent 236 (39.3%), conflict-not-traversable/guard-blocked 126 (21.0%), overridden 130 (21.7%), too-close 108 (18.0%). On denominator 492 (authorised and not close): consistent 48.0%, conflict-not-traversable 25.6%, overridden 26.4%; too-close is excluded and should display n/a, not 22.0%. Conflict total is (126+130)/492=**52.0%**. The output includes the raw too-close count for audit.

Oracle/OHA all-step denominator is 1,604: 976 consistent (60.8%), 250 non-traversable (15.6%), 277 overridden (17.3%), 101 too-close (6.3%). Excluding too-close, n=1,503: 65.0%, 16.6%, 18.4%. This exactly cross-checks 277 and 60.8%. See `analysis/table2_authorised_denominator.csv` and `analysis/table2_authorised.py`.

## G. Terminal verifier

Inputs are route-memory `progress`, not simulator position; simulator pose is used only by `notify_sim_step` to reject >3 m teleports (`stop_gate.py:320-343`). High-confidence force requires estimated `d<=3.0` for 3 consecutive query steps; anchor-corroborated force requires both fixed anchor route-remaining and estimated d <=3.0 for 2 steps (`stop_gate.py:484-515`). Accept: VLM stops, trusted estimated d<=3.0 (`:603-607`). Veto: VLM stops and estimated d>3.0, or low-confidence anchor and estimate independently say far (`:564-587,609-618`). Defer: unreliable/stale authority or low confidence without corroboration (`:522-587`). Force: VLM did not stop and either confirmation condition holds (`:505-515`). Actual FO config is r_in=r_out=3.0, confidence .5, anchor corroboration on, forced-anchor window 2.

Thus force does **not** read simulator distance to s0, but its threshold equals the evaluation radius and its route estimate is ultimately derived from ICP plus outbound anchor geometry. FO and ON use the same type of route-memory estimate; Policy V2 may veto the `forced_stop` consumer in ON. The true distance column in `analysis/terminal_verifier_events.csv` is offline audit only. On matched M50, FO has 28 forced episodes; all 28 terminal true distances are available in the CSV. Counterfactual “without force” outcome is **unknown** because execution stops and no later steps exist. Veto/defer also use the same estimated route distance, not simulator distance, while evaluation alone uses simulator pose. This removes literal oracle-answer leakage but retains matched 3.0 m thresholds and should be disclosed.

## Remaining NOT FOUND / manual confirmation

- Exact CUDA/Isaac source of outbound nondeterminism; deterministic kernel settings were absent.
- Reverse-goal coordinates and E2 distribution.
- A distinct AR field for E3.
- Complete GEO stuck-failure upper bound because two trajectories are absent.
- “What would happen without forced stop” cannot be recovered from terminated trajectories.
