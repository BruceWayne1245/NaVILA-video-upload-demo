# Deterministic path-following geometry M50 ablation

## Scope

The runnable local working directory is an isolated copy of the self-contained
Policy V2 online runtime archived at:

`navila_archive/staging_dirs/navila-reliability-v1_1-policy-v2-active50-20260725`

`code/` contains the complete files changed for this experiment; unchanged
dependencies remain in the isolated local working directory. The source
archive is not modified. The copied evaluator keeps the NaVILA
outbound and scripted confirm phases, then replaces return-stage language
action generation with a deterministic controller:

`route memory + sequential-pair ICP -> reverse breadcrumb path follower -> velocity command`

The return branch does not query the VLM, create/commit a route hint, call the
HintActionArbiter, call ReturnStopGate, or call StuckRecovery.  A VLM server is
still started because outbound remains the original NaVILA policy.

## Geometry and oracle boundary

Breadcrumbs are sampled from `RouteMemoryAgent._outbound_pose_from_start`, the
same action/measured-odometry accumulation used by the online route memory.
The path follower never reads `RouteAnchor.metadata["world_pose"]` or the
simulator pose.  Sequential-pair anchor geometry stays `accumulated`.

For a controlled comparison with the paper's online M50, the launcher retains
the comparator's historical `--oracle_align_return_yaw_to_anchor_segment`
return-start convention.  This is the same known oracle-yaw intervention in
the online result; the subsequent return controller and route geometry are
non-oracle.  A fully oracle-yaw-free follow-up must be labelled as a separate
ablation, not substituted into this comparison.

## Path follower

- samples outbound breadcrumbs every 0.10-0.25 m or 12 degrees;
- projects the route-relative return pose onto a local polyline window;
- chooses a target 0.65 m closer to route start by polyline arc length;
- uses 28/12 degree enter/exit hysteresis for turn-in-place;
- otherwise moves forward with the historical primitive velocity;
- stops only when both the geometric distance and polyline endpoint agree.

This first implementation avoids corner cutting by preserving the outbound
polyline.  It intentionally does not add a separate global planner or semantic
obstacle-avoidance model, which would confound the VLM-vs-geometry comparison.

## M50 launcher

[`run_path_following_geometry_m50_20260906.sh`](run_path_following_geometry_m50_20260906.sh)
contains exactly the same 50
`run_episode` rows, in the same order, as the chronological first half of
`policy_v2_active50_replay_on_highsuccess100ep_20260816` and its matched pure
baseline.  It supports `ONLY_EPISODES` for a later smoke run, but this directory
creation step does not launch Isaac Sim or the batch.

The published launcher records the absolute path of the isolated runtime on the
evaluation machine; it is therefore a provenance-preserving launch record, not
a portable installer. The launcher intentionally omits
`--capture_icp_replay_dataset`; the former raw
replay archive was explicitly deleted for article-only retention, and this
comparison needs measurements, trajectories, maps, logs and video rather than
another multi-terabyte training capture.

## Verification

Run the pure controller tests without Isaac Sim:

```bash
PYTHONPATH=code python3 -m unittest tests/test_path_following_geometry.py
```

Before any M50 launch, run one representative `ONLY_EPISODES=<id>` smoke test
and verify in its trajectory/phase events that outbound contains VLM commands,
return contains `deterministic_path_following_command`, and return contains no
`vlm_command`, `route_memory_hint`, `hint_action_arbiter`, or `stop_gate` event.

As of 2026-09-06, no smoke episode has been launched: the RTX 4090 was occupied
by another Python workload at roughly 70-74% compute utilization. Static
verification completed successfully: four controller tests passed, the three
modified Python files compiled, the shell launcher passed `bash -n`, and its 50
episode rows matched the paper M50 list exactly.
