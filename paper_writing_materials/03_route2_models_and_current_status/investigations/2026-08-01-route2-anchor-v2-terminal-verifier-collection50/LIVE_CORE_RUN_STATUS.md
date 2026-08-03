# Live Route 2 Core run status — snapshot 2026-08-01 22:29 BST

This is a time-stamped operational snapshot, not a completion claim. Re-check
the host before relying on a later PID, episode or service state.

## Detached execution

Service:
`navila-route2-core-dev24-validation20-then-route1-30-20260801.service`

At the snapshot it was `active (running)`, had been running since
22:07:11 BST, and was owned by the per-user systemd manager. The chain and all
current VLM/evaluator descendants were in the same service cgroup.

Run order:

1. Route 2 Core development24;
2. Route 2 Core locked-validation20;
3. existing Route 1 quarantine-veto30.

## Progress at snapshot

- static preflight passed before launch;
- ep319 completed with `exit_code=0` at 22:29:06 BST;
- development episode ep696 started next on port 54696;
- no episode failure had been recorded;
- locked-validation20 had not started;
- the service used about 9.1 GB host memory at the status snapshot.

The launch command confirms the corrected boundary:

- `--reliability_v11_online`;
- `--reliability_v11_core_mode=active`;
- `--reliability_v11_derived_evidence_mode=active`;
- Anchor Core V1 hash-locked and in `shadow`;
- legacy integrated promotion/anchor/candidate-controller prototypes off;
- no `--reliability_v11_consumer_mode=off` in the Core cohort launcher.

Ep319's physically separated Terminal export contained 40 query rows: ten
direct-distance `arrived`, five `boundary`, and 25 `far`; 39 were background
observations and one was near-threshold auxiliary evidence. Action-integrated
motion was used, legacy oracle trajectory motion was not used, and all seven
terminal blind queries had an A0 probe record. These are single-episode
development observations, not validation metrics.

## Immutable provenance

The development run records:

```text
scope=route2_only
cohort=development
episode_count=24
v11_core_mode=active
anchor_core_v1_mode=shadow
terminal_core_v1_mode=postepisode_shadow
hint_core_v1_mode=postepisode_shadow
current_50_control_effect=none
```

The exact provenance, lock-at-launch, ep319 downstream shadow score and ep319
Terminal export summary are archived under `core_correction/run_provenance/`.
The live chain log and large episode outputs remain on the execution host and
are not copied into GitHub.
