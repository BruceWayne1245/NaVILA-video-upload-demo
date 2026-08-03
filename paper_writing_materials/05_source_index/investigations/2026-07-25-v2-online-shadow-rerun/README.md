# 2026-07-25: Policy V2 online-shadow repair and 24ep rerun

Status snapshot: `2026-07-25T09:54:39+01:00`

Prior GitHub authority: private repository `main` at
`520bf4a060770fe00d5690e22a1e42a3cd0d7f01`.

This investigation records the failure of the first 24-episode Policy V2
online-shadow handoff, the 2026-07-25 repair, the successful real-episode
smoke test, and the replacement 24ep rerun. It also freezes the code-ownership
boundary between Route 1 and Route 2 for future work.

## Executive status

The first 24ep run did not evaluate Policy V2. All 24 physical episodes made
two attempts, but all 48 attempts exited before episode initialization and
created no result directory, measurement, trajectory, completion manifest,
V1.1 shadow stream, or Policy V2 consumer stream. The reported `0/24` was an
infrastructure/bootstrap failure, not a navigation or Policy V2 result.

The failure was repaired without changing the live Route 1 source. A real
ep3 smoke test then completed and passed the strict completion validator.
The replacement 24ep online-shadow run started at
`2026-07-25T09:49:04+01:00` and was active/running at this snapshot.

Policy V2 remains locked to shadow:

- Route 1 executes the baseline controller decision;
- Route 2 records only counterfactual consumer allow/veto decisions;
- enforcement is disabled;
- `controller_effects` must remain zero;
- this rerun does not authorize an active canary.

## Root cause of the invalid first 24ep run

The isolated candidate retained a legacy low-level-policy path derived from
`round_trip_eval.py`'s `__file__`:

```text
../logs/rsl_rl/<experiment>/<load_run>
```

That path was valid in the live benchmark tree, but invalid after the entry
point was copied to:

```text
/home/teambruce/navila-reliability-v1_1-policy-v2-20260724/
  policy_v2_live_candidate/scripts/
```

The candidate therefore looked for `agent.yaml` and the locomotion checkpoint
under a nonexistent candidate-local `logs/` tree. The first guaranteed
runtime blocker was the assertion that the loaded run's
`params/agent.yaml` must exist.

The failure was obscured by two lifecycle defects:

1. `IsaacLab/isaaclab.sh -p` ran Python and then executed `break` without
   preserving Python's status, so failed Python processes appeared as
   `exit_code=0`.
2. The batch runner suppressed validator stdout/stderr, retried every
   deterministic bootstrap failure, and did not return nonzero when the final
   valid count was zero.

The resulting first-run record was:

```text
attempts=48
physical_episodes=24
valid_completions=0
result_directories=0
Policy_V2_online_observations=0
```

## 2026-07-25 repair

### Explicit low-level policy dependency

The isolated `round_trip_eval.py` now accepts:

```text
--low_level_policy_log_root
```

The 24ep runner explicitly binds it to:

```text
/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/logs/rsl_rl
```

The candidate no longer relies on its own file location to discover the
low-level locomotion policy.

The following read-only runtime assets are now required and hash-locked in
preflight:

| Asset | SHA-256 |
|---|---|
| `go2_vision/2024-09-25_23-22-02/params/agent.yaml` | `4558ee69bb86e5a8d173fa1b52b768b76dbd7ae369ffefe8370532a9f601ac32` |
| `go2_vision/2024-09-25_23-22-02/model_26499.pt` | `1e21097122ab0bfccaf9d4df2df794d8c1c918a1ddca72c07e38b36768f2e76c` |
| candidate `generated/reversed_instructions.json` | `cd4044f4c4d7a94308e7587aa07b9a4e1acea1a2db8db1dc8bf5cc2d050731fb` |

### Honest process status

The Policy V2 batch driver now invokes the exact Python executable from the
Isaac environment directly:

```text
/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac/bin/python
```

This bypasses the status-masking `isaaclab.sh -p` branch and preserves the
real Python exit status.

### Stronger batch failure semantics

The runner now:

- emits the validator's concrete error after a failed attempt;
- aborts the cohort immediately if an attempt creates no result directory;
- avoids a bounded retry for a deterministic bootstrap/no-result failure;
- exits nonzero if `valid_count != expected_count`;
- supports a one-episode smoke selection with an independent run tag;
- records the low-level config, checkpoint, and instruction-cache hashes in
  run provenance.

### Modified local hashes

| Local file | SHA-256 |
|---|---|
| isolated `round_trip_eval.py` | `220392b7366da435c497dae850fd2f2c7f58b27e9ef87973d703101f2fdd623d` |
| isolated `route_memory_agent.py` | `9a6ef419fdf6eebd2590a0f6b0d793958144cc422c45144179e58aec9855178f` |
| `run_policy_v2_batch_driver.sh` | `540ed476cf203e90ff6d9a3851b8458a09fbca7c11e55ebe1cced962f41696c1` |
| repaired `run_batch.sh` | `c632bdc92a83783cc00f6f455162f76b589b31f89128200b70044902a49ec661` |

## Verification

### Static and regression verification

Preflight passed with:

- 24 unique frozen episodes across seven scenes;
- the frozen Policy V2 artifact locked to shadow/no-enforcement;
- candidate, runtime, policy, low-level config, checkpoint, and instruction
  cache hashes matching;
- Python compilation passing.

The selected Policy V2 and RouteMemoryAgent regression suite passed:

```text
152 passed, 14 skipped
```

### Real ep3 smoke

Smoke run tag:

```text
reliability_v11_policy_v2_shadow_smoke_ep3_rerun1_20260725
```

Runtime:

```text
started=2026-07-25T09:39:29+01:00
finished=2026-07-25T09:48:15+01:00
valid=1/1
python_exit_code=0
completion_validator=PASS
```

Integration and safety results:

| Check | Result |
|---|---:|
| V1.1 session starts / ends | 1 / 1 |
| Policy V2 session starts / ends | 1 / 1 |
| Policy V2 consumer decisions | 17 |
| counterfactual route-hint vetoes | 6 |
| controller effects | 0 |
| enforcement enabled | false |
| episode fail-open disabled | false |

The baseline navigation result was outbound failure and return success. That
is a Route 1 navigation outcome, not an integration failure. The purpose of
the smoke was to prove checkpoint loading, real navigation-loop entry,
V1/V2 temporal logging, shadow no-effect behavior, completion finalization,
and validator acceptance.

## Replacement 24ep online-shadow run

Run tag:

```text
reliability_v11_policy_v2_online_shadow_24ep_rerun1_20260725
```

Detached user service:

```text
navila-v11-policy-v2-shadow-24ep-rerun1.service
```

Launch state at this snapshot:

```text
started=2026-07-25T09:49:04+01:00
ActiveState=active
SubState=running
first_physical_episode=3
summary_rows=0
```

The rerun uses a new run tag and does not reuse or overwrite the invalid
first 24ep run or the ep3 smoke result. Final navigation, parity, consumer,
fail-open, and completion statistics must be added only after the service
reaches a terminal state and all available result directories are validated.

## Permanent Route 1 / Route 2 code boundary

Effective from this investigation forward:

### Route 1: live baseline

Route 1 remains the live benchmark/controller source under:

```text
/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/
```

Policy V2 development must not modify these live Route 1 entry points.

### Route 2: isolated Policy V2 candidate

All future Route 2 / Policy V2 source changes must be implemented under:

```text
/home/teambruce/navila-reliability-v1_1-policy-v2-20260724/
  policy_v2_live_candidate/scripts/
```

Associated Route 2 policy, runtime, tests, experiments, and provenance remain
under the same isolated work root:

```text
/home/teambruce/navila-reliability-v1_1-policy-v2-20260724/
```

This boundary exists so that:

- Route 1 remains a stable, directly comparable baseline;
- Route 2 changes can be hash-frozen, reviewed, tested, and smoked without
  silently changing Route 1;
- online shadow logs preserve an auditable distinction between executed
  baseline decisions and Policy V2 counterfactual decisions;
- a future Route 2 promotion to live cannot occur implicitly.

The live VLM server, dataset, simulator assets, and low-level locomotion
checkpoint may be used by Route 2 only as explicit, read-only, hash-locked
runtime dependencies. Sharing those dependencies does not transfer Route 2
source changes into Route 1.

No Route 2 change may be copied or merged into live Route 1 unless a later
investigation records explicit promotion approval, exact source and asset
hashes, regression results, a passing real-episode smoke, and the intended
activation mode.

