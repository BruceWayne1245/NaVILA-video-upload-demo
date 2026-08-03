# Post-run plan

This order is frozen before prospective aggregate model outcomes are opened.
Do not tune the V1.1 artifact, features, thresholds, labels, exclusions, or
episode set on this batch.

## During the run

1. Do not edit the live controller, capture implementation, runner, manifest,
   run tag, or V1.1 artifact in place.
2. Monitor only operational health: completed physical IDs, exit codes, active
   episode, disk space, replay-file growth, and obvious JSON corruption.
3. Do not replace a difficult/no-return/navigation-failure episode.
4. Permit only the predeclared infrastructure rule: one retry after 120 seconds
   for VLM startup `exit_code=98`. Preserve both attempt rows in the same
   physical-episode cluster.
5. If the batch process is interrupted, restart the same launched runner and
   run tag. Its resume logic skips any physical ID with a prior non-98 summary
   row and never creates a new episode set.

## 1. Completion and provenance audit

Before model scoring:

1. Recompute the manifest, artifact, runner, driver, navigation, and
   `stuck_recovery.py` hashes. Compare them with `run_provenance.txt`.
2. Reconcile all 100 manifest IDs against `summary.tsv`:
   - one non-98 terminal row, or
   - at most two predeclared exit-98 infrastructure attempts.
3. Report duplicate attempts, timeouts, startup failures, missing measurement
   files, outbound failures, no-return episodes, and interrupted episodes.
4. Keep all 100 scheduled physical IDs in the operational denominator.
5. Do not silently select only outbound successes or only episodes that
   produced a measurement JSON.

## 2. Capture-integrity audit

For every episode that enters return:

1. Validate `anchors.json` and every `frame_step*.json` as readable JSON.
2. Check anchor indices, world poses, raw cloud availability, step ranges,
   duplicate steps, and gaps.
3. Reconcile return-phase environment steps with persisted replay frames and
   report a required-input drop count.
4. Verify attempt/current/next/anchor linkage and chronological ordering.
5. Confirm temporal state resets at each episode and never crosses anchor
   identity boundaries.
6. Recompute at least 100 bearing/distance/pose labels from raw robot and
   anchor poses and require zero mismatch with the dataset labels.
7. Report missingness and unusable reasons rather than imputing away a capture
   failure.

If the required-input capture gate fails, the run is not a valid prospective
model acceptance batch. Do not rescue it by cherry-picking complete episodes.

## 3. Build the prospective dataset without refitting

1. Keep this batch separate from the historical 91,003-row development data.
2. Replay the captured raw geometry with the frozen V1.1 ICP/feature contract:
   top-four basins, yaw/Scan Context/localizability, same-attempt current/next
   pair features, and causal 4/8/16/32 histories.
3. Preserve the frozen 249-feature order and category/missingness semantics.
4. Exclude all episode, scene, batch, ground-truth, downstream outcome, and
   future-observation fields from model inputs.
5. Record a prospective dataset manifest and SHA-256 before calculating
   aggregate performance.

## 4. Score the frozen artifact

Use only the artifact with SHA-256
`5f23aba46a45d564131dccd093b1e76160a513162910709503ac8c0a49cb35ce`.
Do not recalibrate or choose new thresholds. The frozen trusted cutoffs are:

| Head | Maximum predicted bad probability for trusted |
|---|---:|
| bearing | `0.3204705300073818` |
| distance | `0.26456558921851075` |
| pose | `0.30170109857950944` |

Persist row-level probabilities, trusted flags, episode/attempt/anchor/role
linkage, and input availability for reproducible aggregation.

## 5. Primary statistical report

Treat physical CLI episode ID as the independent cluster. Candidate rows,
current/next pairs, repeated attempts, and exit-98 retries are not independent
samples.

For each head, report AUC, AP, Brier score, calibration/ECE, trusted coverage,
empirical trusted bad rate, and a one-sided 95% physical-episode-cluster
bootstrap upper bound. Apply the predeclared gates:

| Head | Minimum AUC | Maximum trusted-risk UCB | Minimum coverage |
|---|---:|---:|---:|
| bearing | 0.80 | 10% | 35% |
| distance | 0.92 | 5% | 35% |
| pose | 0.96 | 5% | 30% |

Also report:

- episode-macro, scene-macro, and worst-scene results;
- current versus next role;
- early/middle/late return;
- all-three-head joint trusted coverage, joint bad rate, and cluster UCB;
- consecutive trusted/untrusted streaks and per-attempt availability;
- the operational waterfall: scheduled -> launched -> outbound success ->
  return capture -> valid V1.1 input -> trusted output;
- Claude heuristic/V1.1 disagreement cells, with ground-truth error in each
  cell.

## 6. Separate Claude and model conclusions

- Navigation success, stuck-recovery events, trend-budget effects, and other
  controller outcomes belong to Claude's non-model evaluation.
- V1.1 receives no causal credit or blame for navigation because it had no
  online control authority.
- The new episode cohort does not by itself provide a paired old/new controller
  A/B. Any historical comparison must state its cohort/configuration limits.

## 7. Decision branches

- **All model gates and integrity gates pass with useful joint coverage:** keep
  enforcement locked; next build a V1.1 portable runtime and run a short online
  shadow canary for feature/probability parity, reset behavior, exceptions,
  latency, and logging.
- **Ranking passes but calibration/risk/coverage fails:** do not tune on this
  prospective result and call it validated. Promote this batch to V1.2
  development data, change the model under a new version, then collect another
  untouched prospective batch.
- **Capture integrity fails:** report the operational failure and fix capture;
  do not compute a passing result from a selected subset.
- **Scalar/basin/temporal signal plateaus:** move to the predeclared raw
  point-cloud/RGB-D direction rather than increasing HGB capacity on the same
  features.
- **Model gates pass but no safe consumer mapping exists:** remain shadow-only.
  Passing prediction gates never automatically enables hint, stop, promotion,
  quarantine, or current-anchor control.
