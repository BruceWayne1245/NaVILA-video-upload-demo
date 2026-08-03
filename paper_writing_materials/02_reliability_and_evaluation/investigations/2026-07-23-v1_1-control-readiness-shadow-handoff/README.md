# Reliability V1.1 control-readiness shadow handoff — 2026-07-23

## Objective

Carry this framework with Claude's next 100-episode Route-1 batch. Route 1
remains the sole controller in that batch, while V1.1 runs a complete
counterfactual version of its proposed control integration.

The run is designed to decide whether the *following* 100-episode experiment
can move from pure shadow to a predeclared active A/B. It measures prediction
quality, exact online/offline parity, the concrete candidate-filter policy,
false admits, false defers, update starvation, scene/role/stage heterogeneity,
and capture integrity.

No finite shadow run can prove navigation benefit causally. Passing all frozen
gates authorizes implementation review and a 10-episode guarded active canary.
Only a clean active canary permits the following 100-episode active A/B.

## Shadow/control boundary

This 100-episode run is still completely observational:

- V1.1 sees copied raw sequential-pair ICP diagnostics.
- Its output is not returned to `RouteMemoryAgent`.
- Current/next anchor identity cannot be changed.
- Hint, promotion, quarantine, stop, recovery, and motor commands are
  untouched.
- Oracle truth is computed only after model scoring and counterfactual policy
  evaluation, then appended under `posthoc_ground_truth`.
- The log asserts `used_for_features=false`, `used_for_scoring=false`, and
  `used_for_decision=false`.
- Model/policy exceptions are swallowed and logged.

The portable artifact and decision policy both remain enforcement-locked.

## Proposed active consumer mapping

The frozen policy is `role-safe-precontroller-joint-trust-v1`:

1. Identify the raw `current` and `next` candidates from the same attempt.
2. If `current` is absent or not jointly trusted, the hypothetical active
   adapter forwards no candidate for that relocalization update.
3. If `current` is jointly trusted and `next` is absent/untrusted, forward
   current only.
4. If both are jointly trusted, forward both unchanged.
5. Never use a trusted next candidate to replace a missing/untrusted current
   candidate.
6. Filtering occurs before RouteMemoryAgent closure/fusion, so rejected raw
   evidence cannot mutate promotion or belief state.

The live controller still receives the original, unfiltered candidates in
this shadow run. The JSONL records the exact hypothetical forwarded anchor
set.

## Why this run is decision-complete

Every decision row contains:

- physical episode, scene, step, attempt, anchor, and role keys;
- frozen online probabilities and trusted flags;
- the exact pre-controller forwarded candidate set;
- the unchanged existing-controller result and postprocessing backend;
- online oracle bearing/distance errors and frozen labels, attached only after
  the decision;
- explicit non-enforcement locks.

The post-run scorer requires an exact join against independently rebuilt
offline rows. Every label, probability, and trusted flag must match; missing
or extra keys fail the run.

Capture is hardened with same-directory temporary writes, file `fsync`, and
atomic `os.replace` for anchors, replay frames, trajectories, and measurements.
Each completed process writes `capture_completion.json` containing hashes.

## Files

- `CLAUDE_RUNNER_ARGS.sh`: flags and frozen preflight.
- `CONTROL_READINESS_PROTOCOL.md`: hypotheses, gates, and analysis order.
- `ACTIVE_INTEGRATION_PLAN.md`: exact post-pass activation path.
- `SOURCE_MANIFEST.sha256`: package-relative runtime, model, policy, gates,
  runner, test, and analysis hashes.
- `REPLAY_SMOKE_SUMMARY.json`: old-canary policy-interface smoke only.
- `REPLAY_SMOKE_DECISIONS.jsonl`: the corresponding 698 reconstructed
  counterfactual decision events.
- `VERIFICATION.md`: checks completed before publication.

Archived implementation:

- `candidate_runtime/round_trip_eval.py`
- `runtime/v11_runtime.py`
- `runtime/reliability_v11_portable_runtime.py`
- `artifacts/reliability_v1_1_portable_shadow.json`
- `configs/v11_decision_shadow_v1.json`
- `configs/v11_control_readiness_gates_v1.json`
- `tools/validate_v11_shadow_jsonl.py`
- `tools/replay_v11_decision_shadow.py`
- `tools/score_v11_control_readiness.py`
- `tests/test_v11_portable.py`
- `tests/test_v11_control_readiness.py`

The runner script retains the current machine's deployment paths under
`/home/teambruce/` so Claude can carry this snapshot into the existing
environment without guessing path substitutions.

## Claude integration

Claude should merge his final Route-1 changes into the candidate entry point,
source `CLAUDE_RUNNER_ARGS.sh`, call `v11_decision_shadow_preflight`, append
`${V11_DECISION_SHADOW_ARGS}`, and keep
`--capture_icp_replay_dataset` enabled.

He must freeze and record the final merged controller hashes before launch.
The V1.1 runtime, portable artifact, policy, gates, and analysis tools may not
change after aggregate results begin.

Navigation results belong only to Route 1. V1.1 receives no causal credit or
blame in this batch.

## Authority

The latest GitHub authority checked before construction was commit
`86a6a6f2c7ff3c0e9cbc870c36e70af76be5e493`. Its 2026-07-23 investigation
shows that scalar reliability cannot resolve rotationally symmetric,
confidently-wrong geometry by itself. V1.1 is therefore a safety/selective-use
layer; visual rotation verification remains the root-cause path.
