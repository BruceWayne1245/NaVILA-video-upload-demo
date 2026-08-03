# 2026-07-24 status update: current-data audit, Policy V2, and detached 24ep handoff

Status snapshot: `2026-07-24T20:37:22+01:00`

GitHub authority used for this work: private repository `main` at
`63f541df43de7e393f83513add855736fb20929b`.

This is a post-freeze operational update. The original 2026-07-23 files and
`SOURCE_MANIFEST.sha256` remain the immutable Policy V1 decision-shadow
snapshot. This file records the later Policy V2 work and is intentionally not
retroactively inserted into that frozen manifest.

## Executive status

The frozen V1.1 model is useful as a selective risk signal on the currently
available data. The original Policy V1 consumer, which drops a whole
relocalization update when `current` is untrusted, is not suitable for active
control because it can starve the existing controller for extremely long
periods.

An isolated Policy V2 candidate has therefore been implemented. It preserves
all raw candidates and all reversible relocalization updates, and evaluates
V1.1 trust only at five high-consequence downstream consumers:

1. anchor promotion;
2. route-hint injection;
3. hint-action override;
4. stop-gate forced stop;
5. stop-gate veto of a VLM stop.

Policy V2 is currently locked to online shadow. It records what it would
allow or veto, while Route 1 executes the unchanged baseline decision.
`controller_effect` must remain false.

A detached 24-episode Policy V2 online-shadow cohort is armed to begin
automatically after the currently running 100ep service reaches any terminal
state. The current live source and current service were not modified.

## Current 100ep run at the handoff snapshot

- Unit: `navila-v11-decision-shadow-rgbd-100ep.service`
- Run tag:
  `reliability_v11_decision_shadow_rgbd_100ep_20260724`
- State when the handoff was armed: `active/running`
- Completed summary rows: 76/100
- Active physical episode: 355
- Current unit restart policy: `Restart=no`
- Live benchmark:
  `/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench`

The partial-data audit below was performed without stopping or changing this
run. The formal 100ep analysis must still use the final scheduled denominator
and the fixed post-run order in `CONTROL_READINESS_PROTOCOL.md`.

## Step 1 result: model usability from currently available data

At the audit snapshot, 72 result directories existed:

- 40 integrity-valid episodes with scoreable V1.1 decision rows;
- 26 valid episodes that never reached return scoring;
- 4 episodes with syntactically invalid measurement JSON:
  ep18, ep100, ep814, and ep1069;
- 2 episodes without completion manifests: ep615 and ep645.

Across all 40 currently eligible episodes:

| Metric | Current result |
|---|---:|
| scoreable current-anchor rows | 10,327 |
| jointly trusted current coverage | 48.21% |
| pose-bad block recall | 99.37% |
| pose-bad rate among trusted current rows | 0.603% |
| one-sided 95% Wilson upper bound | 0.812% |

Interpretation: V1.1 is useful for deciding whether a high-consequence
consumer should rely on the authoritative anchor. This is development
evidence, not formal activation approval, because the source batch is
incomplete, has known integrity exclusions, and was inspected while designing
Policy V2.

## Why Policy V1 was not promoted to active control

The original role-safe pre-controller filter can remove every relocalization
update whenever `current` is untrusted. On the frozen representative 24ep
replay it would have created 3,768 full-update defers. Individual episodes
contain untrusted-current streaks as long as 900 attempts.

That failure mode is architectural rather than a threshold-tuning detail:
good risk discrimination does not make prolonged loss of reversible
relocalization evidence safe. Policy V1 remains a historical, frozen
decision-shadow contract; it is not the active integration target.

## Step 2 implementation: Policy V2 consumer guard

### Safety contract

Policy V2 never:

- drops or edits a raw ICP candidate;
- substitutes `next` for `current`;
- changes anchor identity;
- blocks a reversible relocalization update;
- reads posthoc oracle truth during a decision.

Before the first score in an episode, baseline behavior is preserved. After
scores are available, an untrusted or missing authoritative-anchor assessment
counterfactually vetoes only the requested guarded operation.

A malformed or non-finite model output disables Policy V2 for the rest of the
episode, fails open to Route 1, and emits a high-severity event. Thirty
consecutive promotion vetoes trigger the same fail-open recovery valve. Either
condition must fail a future guarded active canary.

### Isolated code changes

The exact live sources were copied before modification. Nothing under the
current live `scripts/` directory or the active reliability worktree was
changed.

`round_trip_eval.py` received 249 insertions and 10 deletions relative to the
live entry point:

- added `off|shadow|active` Policy V2 CLI wiring, default `off`;
- loaded and reset the consumer guard per physical episode;
- passed every V1.1 score into the per-anchor assessment cache;
- evaluated route hints, hint overrides, forced stops, and VLM-stop vetoes at
  their final pre-execution hooks;
- wrote a dedicated, flushed
  `reliability_v11_consumer_v2.jsonl`;
- summarized operation/veto/controller-effect counts in the measurement;
- added the Policy V2 stream and hash to `capture_completion.json`.

`route_memory_agent.py` received 16 insertions:

- added an optional consumer-guard callback;
- invoked it only after the baseline promotion logic proposes promotion and
  immediately before the anchor identity commit.

The adapter itself enforces a hard activation lock: `active` mode is rejected
unless a separate policy artifact declares both `mode=active` and
`enforcement_approved=true`. The current artifact declares:

```text
mode=shadow
enforcement_approved=false
identity_override_authorized=false
candidate_flow=preserve_baseline_candidates
```

### Frozen local hashes

| Artifact | SHA-256 |
|---|---|
| isolated candidate `round_trip_eval.py` | `e22df759d3d0024e2a00d2ec79758129320c39aba1798c17d185bc5105920805` |
| isolated candidate `route_memory_agent.py` | `9a6ef419fdf6eebd2590a0f6b0d793958144cc422c45144179e58aec9855178f` |
| `configs/v11_consumer_policy_v2.json` | `000d8dda31f1808b9db3b1a270ecb522b7b9377d0672c1ea8ff5b4d5bcfdb3bf` |
| `reliability/v11_consumer_policy_v2.py` | `1a8727328a1ef0a98d29eceb1365e966b8fef10c3f2f0c2b6ef7dfb7094eab3f` |

Local isolated root:

`/home/teambruce/navila-reliability-v1_1-policy-v2-20260724/`

### Verification completed

- Python compilation: pass.
- Full selected regression/unit/wiring suite: 152 passed, 14 skipped.
- Policy-specific coverage includes shadow no-effect behavior, active-only
  guarded vetoes, preserved relocalization flow, bootstrap, missing
  assessment, invalid-model fail-open, bounded promotion fallback, activation
  lock, promotion callback wiring, and default-off CLI behavior.

## Offline Policy V2 replay

The deterministic representative cohort contains 24 episodes, seven scenes,
15 return successes, and nine return failures. It spans low/medium/high trust
and risk bins, 41–1001 decisions per episode, and untrusted streaks from 3 to
900 attempts.

| Operation | Requests | V2 vetoes | Pose-bad veto recall | Pose-good allow rate |
|---|---:|---:|---:|---:|
| reversible relocalization update | 7,375 | 0 | n/a by design | 100.0% |
| anchor promotion | 126 | 31 | 96.67% | 97.92% |
| route hint | 624 | 356 | 99.69% | 89.90% |
| hint-action override | 99 | 5 | 100.0% | 100.0% |
| forced stop | 12 | 3 | 100.0% | 100.0% |
| VLM-stop veto | 26 | 13 | 100.0% | 100.0% |

Policy V2 produced zero relocalization defers, zero fail-open-disabled replay
episodes, and zero shadow controller effects. These are encouraging replay
results, not navigation or online-integration evidence.

## Detached 24ep online-shadow handoff

### Frozen cohort

Physical episode indices, in launch order:

```text
3 87 93 95 196 205 264 333 351 387 420 448
579 654 671 682 687 715 764 815 888 890 962 987
```

Scene allocation:

```text
QUCTc6BB5sX=3  x8F5xyUWy9e=2  EU6Fwq7SyZv=5
zsNo4HB9uLZ=6  2azQ1b91cZZ=4  X7HyMhZNoso=3  TbHJrupSAjP=1
```

This is prospective for online Policy V2 execution, logging, and temporal
linkage. Because the cohort was selected using revealed Policy V1 outcomes,
it is not an unbiased navigation-effect cohort and cannot establish causal
benefit.

### Launch and failure semantics

- Handoff unit:
  `navila-v11-policy-v2-shadow-24ep-chain.service`
- Current unit dependency:
  `navila-v11-decision-shadow-rgbd-100ep.service`
- New run tag:
  `reliability_v11_policy_v2_online_shadow_24ep_20260724`
- Handoff armed:
  `2026-07-24T20:37:22+01:00`
- Handoff state after registration: `active/running`, waiting.
- Service properties:
  `Restart=on-failure`, `RestartSec=120s`,
  `KillMode=control-group`.

The handoff waits for the current unit to leave
`active|activating|reloading|deactivating`. It then launches regardless of
whether the terminal state is success, failure, a nonzero exit, or a
bug-triggered termination. It does not require `Result=success`.

Before launch it performs cleanup restricted to the old run tag and last VLM
port, verifies the runner hash, and repeats the complete preflight. The new
batch is managed by the same user systemd manager as the current batch and is
independent of any Codex conversation or terminal.

The handoff cannot distinguish a terminal failure from a service that is
permanently hung but still marked active. The current runner's per-episode
timeout is the first-line protection for that case.

### Batch robustness and hashes

Each episode is accepted only if the completion manifest, measurement,
trajectory, Policy V1 shadow stream, and Policy V2 consumer stream all parse
and satisfy the expected episode/mode/no-effect contract. Incomplete output is
archived, not overwritten. One bounded infrastructure retry is allowed.
Already valid episodes are skipped on service resume.

| File | SHA-256 |
|---|---|
| `episodes.tsv` | `4821aab1efda7663a4a3e1bb35091ce79e8e9cd85b6ccbc414d72f48f99ba0ee` |
| `run_batch.sh` | `41c56e8244ab55c3843017eb31bd3b122bee307cd3907a171e0cfd6cb4acf640` |
| `run_policy_v2_batch_driver.sh` | `2964b908f2b9eb045148a2c6c521d8399711ca68d4496a032cf551fa86296ccc` |
| `validate_completion.py` | `01dbe8df1597d981c2e4a08fd284d37744a9c140ef07f5bfd57da767f1ba4143` |
| `chain_after_current.sh` | `d0d455ec94640bb70d2923b880131fa418e8c8e60f66d2cb1c8c954649c5856c` |

Preflight passed:

- exactly 24 unique episodes and the frozen seven-scene allocation;
- Policy V2 locked to shadow/no-enforcement;
- every candidate, runtime, portable artifact, policy, VLM server, driver,
  validator, and manifest hash matched;
- Python syntax/compilation checks passed.

## Acceptance contract for the 24ep shadow cohort

The cohort may authorize preparation of an active artifact only if:

- all 24 scheduled episodes have valid completion/provenance records;
- online and offline V1.1 scores and trust flags match exactly;
- online and offline Policy V2 decisions match exactly;
- every Policy V2 event is temporally linked to the intended score and
  authoritative anchor;
- raw candidates, poses, probabilities, identity, and reversible
  relocalization flow are unchanged;
- `controller_effects=0` in every episode;
- zero model/runtime exceptions or fail-open disables;
- zero 30-promotion-veto fallback;
- zero new crash, deadlock, or stuck condition attributable to the adapter;
- operation-level risk/coverage is at least consistent with the development
  replay, with all deviations reported rather than tuned away.

Navigation success is descriptive in this shadow cohort because Route 1
remains the sole controller.

## Revised next plan

1. Let the current 100ep service terminate naturally. The detached handoff
   starts the 24ep Policy V2 shadow batch even if the current service exits
   unsuccessfully.
2. Audit the final current-100ep denominator using the original frozen
   protocol. Do not convert partial/revealed evidence into a formal pass.
3. Validate and score all 24 Policy V2 online-shadow episodes against the
   acceptance contract above.
4. If the 24ep contract fails, keep Policy V2 shadow-only, fix/version the
   integration or policy, and collect new prospective evidence.
5. If it passes, perform code review and create a separate hash-locked active
   artifact. Activation still requires explicit authorization; the current
   shadow artifact cannot be switched active by a CLI flag.
6. Run a guarded 10ep active canary. This is the first stage where V1.1 may
   affect control.
7. Only after a clean 10ep canary, run a predeclared paired or randomized
   100ep baseline-versus-active A/B. That experiment, not replay or shadow,
   estimates causal navigation value.
