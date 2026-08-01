# Live run status — snapshot 2026-08-01 16:00:57 BST

This is a time-stamped operational snapshot. Re-check the host before using
any PID, service state, episode or GPU claim in a later session.

## Detached execution proof

Active service:

`navila-route2-anchorv2-terminal50-resume1-20260801.service`

At verification:

- `ActiveState=active`, `SubState=running`;
- main PID `153684`, parent PID `1819` (the per-user systemd manager);
- control group:
  `/user.slice/user-1006.slice/user@1006.service/app.slice/navila-route2-anchorv2-terminal50-resume1-20260801.service`;
- `Linger=yes` for user `teambruce`;
- the service is independent of the conversation, SSH shell and interactive
  session that created it.

## Run identifiers and paths

- Workspace:
  `/home/teambruce/navila-route2-anchorv2-terminal50-20260801`
- Run state:
  `/home/teambruce/navila-route2-anchorv2-terminal50-20260801/runs/route2_anchorv2_terminal_collection50_20260801`
- Orchestrator log:
  `.../runs/route2_anchorv2_terminal_collection50_20260801/orchestrator.log`
- Canary tag:
  `route2_anchorv2_terminal_collection50_20260801_canary`
- Remaining-49 tag:
  `route2_anchorv2_terminal_collection50_20260801_batch49`
- Batch logs:
  `/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/<tag>`
- Result prefix:
  `/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_<tag>_ep<id>`

## Current progress

| Episode | Exit | Outbound | Return | Round trip | A0 probes / return queries | A0 available | Anchor predictions | Controller effects |
|---:|---:|---|---|---|---:|---:|---:|---:|
| 368 | 0 | true | true | true | 30/30 | 29 | 318 | 0 |
| 87 | 0 | true | false | false | 71/71 | 71 | 1001 | 0 |
| 88 | 0 | true | false | false | 73/73 | 73 | 1001 | 0 |
| 134 | 0 | false | false | false | 0/0 | 0 | 0 | 0 |
| 310 | 0 | true | true | true | 31/31 | 31 | 358 | 0 |
| 678 | 0 | true | false | false | 47/47 | 47 | 520 | 0 |

Ep4 was running on port 54004 at the snapshot. Six of 50 were complete; 43
were queued behind the current episode. Across the six complete episodes,
A0 probes covered 252/252 return queries, 251 probes were available, and the
Anchor guard emitted 3,198 predictions with zero controller effects.

## Incident and recovery

The original service
`navila-route2-anchorv2-terminal50-20260801.service` completed ep368 and its
capture validation, then failed at the offline-scoring wrapper with:

`line 292: tag: unbound variable`

Cause: under `set -u`, a single Bash `local` statement attempted to expand
`${tag}` while declaring `tag`, `episode`, and `result_dir`. The declarations
were split into separate statements. Ep368 was then revalidated rather than
rerun. Its 30/30 A0 contract and Anchor shadow metadata passed, and resume1
entered ep87.

The old error remains in the append-only orchestrator log as audit history.
It is not a current failure. After resume, no new fatal, timeout, OOM,
port-busy/overflow or capture-integrity error had occurred at this snapshot.

## Concurrent downstream queue

The separate Route 1 follow-up unit
`navila-quarantine-veto-30ep-queue-20260801.service` was active and waiting at
the snapshot. Its queue script waits for the Route 2 unit and matching Route 2
driver processes to finish before it can launch the anchor0-fix +
quarantine-veto 30ep batch. It therefore uses no GPU while Route 2 is active
and is not part of this service's process tree or runtime snapshot.

## Continuation rules

1. Do not edit the driver snapshot or evaluator while this service is active.
2. Do not restart merely because an episode has a long quiet log; redirected
   output is not a liveness contract.
3. Determine episode validity from `exit_code`, `capture_completion.json`,
   measurement/trajectory integrity and the validator, not navigation success.
4. If the service exits, inspect `CANARY_PASSED`, `COMPLETED`,
   `NEEDS_INFRA_RETRY`, the batch summary and matching descendant processes
   before deciding whether a retry is needed.
5. Never rerun the locked Fresh49 as development data. This collection has its
   own development manifest and result tags.
6. Preserve all non-return episodes; they are valid yield/outcome evidence and
   must not be silently dropped from accounting.
