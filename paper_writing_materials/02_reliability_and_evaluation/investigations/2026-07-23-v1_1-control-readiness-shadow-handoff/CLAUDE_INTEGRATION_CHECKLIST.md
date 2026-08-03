# Claude integration checklist

1. Start from Claude's final Route-1 source, not an older local README or code
   copy.
2. Merge the V1.1 argument definitions, initialization, sequential-pair
   wrapper, controller snapshot, online truth, and atomic capture/finalization
   blocks from the candidate `round_trip_eval.py`.
3. Confirm a no-model run is behaviorally unchanged.
4. Source `CLAUDE_RUNNER_ARGS.sh` and run
   `v11_decision_shadow_preflight`.
5. Append `${V11_DECISION_SHADOW_ARGS}` without removing
   `--capture_icp_replay_dataset`.
6. Freeze the 100 physical episode IDs before launch.
7. Record final hashes for runner, merged driver, route-memory agent,
   relocalization, stop gate, stuck recovery, V1.1 runtime, portable runtime,
   portable artifact, policy, gates, and analysis tools.
8. Confirm startup prints
   `decision_shadow=True enforcement=False controller_effect=False`.
9. Confirm the first return episode writes score, controller snapshot, and
   decision events with complete posthoc truth.
10. Confirm `capture_completion.json` exists only after measurement and
    trajectory finalization.
11. Do not retry or replace an episode based on model output or navigation
    failure.
12. Do not inspect aggregate outcome and then change thresholds, policy, gates,
    or episode membership.

