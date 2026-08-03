# V1.1 100-episode control-readiness protocol

Status: frozen before the next combined Route-1/V1.1 run.

## Questions this run must answer

1. Does the frozen portable runtime reproduce offline features, probabilities,
   trusted flags, and labels exactly online?
2. When the proposed role-safe filter forwards a raw candidate, how often is
   bearing, distance, or pose actually bad?
3. How many bad current candidates does it block?
4. How many good current candidates does it defer?
5. Does filtering starve relocalization for long consecutive periods?
6. Are failures concentrated by scene, role, or return stage?
7. Does closure/fusion frequently repair or corrupt raw evidence that the
   model judged before postprocessing?
8. Is capture complete enough that no favorable subset selection is needed?

## Frozen inputs

- Portable artifact SHA-256 is recorded in `SOURCE_MANIFEST.sha256`.
- Decision policy: `role-safe-precontroller-joint-trust-v1`.
- Control-readiness gates:
  `configs/v11_control_readiness_gates_v1.json`.
- Physical CLI episode IDs must be frozen before launch.
- All scheduled episode IDs stay in the operational denominator.
- No model, feature, calibrator, threshold, policy, label, gate, or exclusion
  may change after results begin.

## Required run configuration

- Claude's finalized Route-1 controller is the only real controller.
- `route_relocalization_backend=sequential_pair`.
- `--capture_icp_replay_dataset`.
- `--reliability_v11_online_shadow`.
- `--reliability_v11_decision_shadow`.
- Frozen runtime, portable artifact, and policy paths from
  `CLAUDE_RUNNER_ARGS.sh`.
- At most the already predeclared VLM-startup retry; no retry/replacement based
  on navigation outcome, model score, policy decision, or label.

## Integrity gates

- 100 unique completion manifests for 100 scheduled physical episode IDs.
- Every manifest is complete and every recorded measurement, trajectory, and
  shadow-log hash matches.
- At least 40 physical episodes contain scoreable return decisions.
- Zero shadow/model/decision exceptions.
- Zero duplicate `(physical_episode_id, attempt)` decisions.
- Zero control-contract or identity-override violations.
- Zero missing online oracle truth rows.
- Exact online/offline candidate key set.
- Zero online/offline label or trusted-flag mismatches.
- Maximum online/offline probability difference `<=1e-15`.

An episode with no return remains in the operational denominator but is
`not_evaluable_no_score_rows`, not a model failure.

## Frozen consumer-policy gates

All row metrics use physical-episode-balanced weights. Risk upper bounds use a
one-sided 95% physical-episode-cluster bootstrap.

| Gate | Requirement |
|---|---:|
| current forwarded coverage | >=35% |
| current pose-bad block recall | >=70% |
| forwarded current bearing-bad UCB | <=10% |
| forwarded current distance-bad UCB | <=5% |
| forwarded current pose-bad UCB | <=5% |
| scoreable episodes with any forwarded current | >=95% |
| scoreable episodes with a forwarded current in attempts 1–10 | >=90% |
| episode p95 longest full-defer streak | <=10 attempts |
| absolute longest full-defer streak | <=30 attempts |
| scene pose-bad rate, when >=100 forwarded-current rows | <=10% |

Report good-candidate defer rate even though it is not a pass/fail gate. It is
the expected efficiency cost of the safety filter and must inform the active
A/B interpretation.

## Required post-run order

1. Audit runner/source/artifact/policy/gate hashes.
2. Reconcile all scheduled IDs, attempts, retries, and completion manifests.
3. Validate every per-episode shadow JSONL.
4. Rebuild the prospective V1/V1.1 dataset without fitting or calibration.
5. Produce frozen offline row predictions.
6. Run `score_v11_control_readiness.py` with all shadow logs, all completion
   manifests, and the offline row-prediction CSV.
7. Inspect overall, role, episode, scene, and defer-streak reports.
8. Apply every gate mechanically; do not waive a failed gate after seeing the
   outcome.

## Decision branches

- All integrity, model, and consumer gates pass: implement the exact frozen
  filter and run the required 10-episode guarded active canary.
- Prediction gates pass but availability/streak gates fail: the model is a
  useful observer but this hard consumer mapping is unsafe; design a new
  policy version and collect new prospective evidence.
- Risk gates fail: remain shadow; do not tune on this batch and call it
  validated.
- Capture or online/offline parity fails: fix the pipeline and rerun; do not
  score a selected subset as a pass.
- Guarded active canary passes: the following 100-episode experiment should be
  a predeclared active A/B, not another pure shadow batch.
