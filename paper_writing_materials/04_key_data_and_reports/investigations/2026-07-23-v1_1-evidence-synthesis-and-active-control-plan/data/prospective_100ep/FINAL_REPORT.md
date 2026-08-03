# V1.1 prospective shadow 100ep final audit

Date: 2026-07-23

## Verdict

The frozen V1.1 artifact passes every predeclared statistical gate on the 59
episodes with scoreable diagnostic records, but the batch does **not** pass the
predeclared capture-integrity gate. Two required ep264 frame JSON files are
corrupt, and ep324 entered return and wrote 595 frames without persisting a
measurement or trajectory that can be reconciled to them. Under the frozen
post-run decision rule, this batch is strong positive model evidence but is not
a formally valid prospective acceptance batch. Enforcement remains locked.

Claude's non-model route-1 controller is also not a satisfactory navigation
result: 17/100 episodes are officially reported round trips; trajectory truth
finds 19/43 outbound-success episodes physically ending within 3 m of the
start, with one outbound-success episode lacking an evaluable return.

## Frozen-model results

All pooled values use physical-episode-balanced weights. Risk bounds are
one-sided 95% bootstraps resampling the 59 physical CLI episode IDs, never
individual ICP rows.

| Head | AUC | AP | Brier | ECE | Trusted coverage | Trusted bad rate | 95% risk UCB | Frozen gate |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| bearing | 0.9196 | 0.8674 | 0.1087 | 0.0256 | 44.90% | 4.68% | 7.70% | statistical pass |
| distance | 0.9453 | 0.8899 | 0.0765 | 0.0165 | 45.79% | 0.95% | 1.32% | statistical pass |
| pose | 0.9743 | 0.9585 | 0.0442 | 0.0094 | 40.48% | 1.29% | 1.89% | statistical pass |

The all-three-head joint operating point has 39.93% coverage, 0.89% empirical
pose-bad risk, and a 1.34% cluster-bootstrap upper bound.

Current- and next-role pooled slices do not materially violate the pooled risk
targets. The important heterogeneity warning is scene `EU6Fwq7SyZv`: bearing
AUC is 0.758 and its empirical bad rate inside the trusted subset is 34.55%.
The cohort contains fresh episodes but no fresh scenes, so this is not evidence
of unseen-scene generalization and is another reason not to enable global
control.

## Dataset and label integrity

- Frozen artifact SHA-256:
  `5f23aba46a45d564131dccd093b1e76160a513162910709503ac8c0a49cb35ce`.
- Prospective V1 CSV: 37,189 rows, 59 physical episodes.
- Prospective V1.1 NPZ: 37,189 rows, frozen 249-feature order, seven scenes.
- Artifact schema, feature names, forbidden-feature exclusion, all three heads,
  thresholds, and finite inference checks pass.
- No unseen `match_class` or `icp_ambiguity` category is present; no feature is
  completely missing.
- All 37,189 raw diagnostic records have the required fields and map to an
  attempt step and anchor pose; diagnostic-record drop count is zero.
- A deterministic balanced sample of 100 raw-pose labels has 100/100 exact
  matches. All 59 usable attempt schedules pass.
- All 474 first episode/anchor stream rows have history count one and missing
  prior-delta features, confirming causal temporal reset at both episode and
  anchor boundaries.

## Capture integrity

- Sixty runs wrote capture frames. Fifty-nine have a persisted return
  trajectory; those contain 97,060 return steps and exactly 97,060
  filename-linked frames, with no gaps, duplicate steps, or extra steps.
- ep324 wrote another 595 frames but has no final measurement or trajectory, so
  those frames cannot be reconciled.
- All 97,655 frame files were fully JSON-parsed. 97,653 pass; ep264 steps 2562
  and 2579 are syntactically corrupt in the middle of their point arrays.
- All captured `anchors.json` files are readable. Anchor 0 has no cloud in all
  60 runs, the predeclared systematic availability condition. Every nonzero
  anchor has a cloud.

These two corrupt required return frames plus the unreconciled ep324 return
violate the frozen zero-drop/exact-linkage gate. No files were repaired and no
episodes were excluded to manufacture a pass.

## Operational denominator and provenance

- Scheduled/unique physical IDs: 100/100.
- Terminal rows: 100. Exit 0: 99; timeout exit 124: ep690.
- No exit-98 retry and no replacement episode.
- ep324 has an operationally incomplete result despite exit 0.
- ep123 reports outbound success but never records a return phase.
- All 100 remain in the operational denominator.
- The 99 Isaac invocations that reached their argv log contain capture, shared
  trend budget, and stuck recovery; all 100 logs are free of a V1.1 model
  runtime/enforcement argument.
- Manifest, artifact, driver, route-memory, relocalization, stop-gate, and
  stuck-recovery hashes match run provenance. The launched runner archive hash
  is `e958286f0e9e908434056dd655a114f5487efad997ca3d62c5ed03e71fc05954`.
- The run-time `round_trip_eval.py` hash
  `7941f9a9611c11c16491ac18db9d2baffc5862c98157c6bfd7c204c304172866`
  is preserved in the archived run snapshot. The current live file changed
  after this run for later vision work and was not substituted into this
  audit.

## Route-1 navigation outcome

- Reported outbound success: 43/100.
- Reported round-trip success: 17/100.
- Of 43 outbound-success episodes, 42 have an evaluable return trajectory.
- Truth definition: final XY distance from the trajectory's step-0 start is
  below 3.0 m after removing three detectable cross-episode reset rows.
- Physical final-position successes: 19/42 evaluable = 45.24%, or 19/43 =
  44.19% in the outbound operational denominator.
- The two truth/report disagreements are ep366 and ep844: both physically end
  inside 3 m but do not receive official return success.
- Five return episodes enter the 3 m radius and later leave it; three finish
  between 3.0 and 3.2 m.
- Among outbound-success episodes, stuck recovery fires in nine and only two
  finish physically successful. Across every episode with return, it fires in
  12 and three finish successful. This run does not demonstrate a reliable
  rescue effect.
- Of the 19 outbound-conditioned physical successes, the terminal stop-gate
  states are eight forced, eight deferred, one accepted, one pass, and one
  vetoed. Success still depends heavily on the stop/termination layer.

The earlier 12/19 = 63% fix-ON snapshot and this 19/43 = 44% result use
different, unpaired episode cohorts. The difference is descriptive and cannot
be attributed causally to shared trend budget or stuck recovery.

## Decision

Do not tune V1.1 on this batch and call it validated. Preserve these results as
prospective evidence, fix capture with atomic per-frame writes and a
measurement/trajectory finalization guard, then run another untouched
prospective cohort. If that integrity-clean rerun reproduces the model gates,
the next permitted step is an online shadow canary for portable-runtime parity,
state resets, exceptions/NaNs, latency, and logging—not enforcement.

For navigation, continue the already identified visual rotation verification
path at promote and forced-stop decision points. Route 1 alone has not removed
the confidently-wrong rotational-basin failure mode.
