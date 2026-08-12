## Route maps: baseline vs oracle_hint on the 4 oracle-only-return overlap episodes (2026-08-12)

Cross-referencing `final_data/pure_navila_baseline_100ep_20260810_full_results.tsv` against
`final_data/pure_oracle_hint_highsuccess100ep_20260811_full_results.tsv` by `episode_id`: 30
episode_ids overlap between the two 100-episode samples, 26 of those had outbound_success=True
in both. Of those 26, exactly 4 flip from baseline return-fail to oracle_hint return-success
(no episode goes the other way — oracle_hint was a pure return-phase gain on this overlap set):

| episode_id | episode_idx | scene | baseline final dist-to-start | oracle_hint final dist-to-start |
|---|---|---|---|---|
| 422 | 268 | QUCTc6BB5sX | 3.31 m (fail) | 2.75 m (success) |
| 602 | 367 | X7HyMhZNoso | 5.28 m (fail) | 1.49 m (success) |
| 1153 | 669 | X7HyMhZNoso | 6.57 m (fail) | 0.69 m (success) |
| 1378 | 813 | x8F5xyUWy9e | 5.57 m (fail) | 0.78 m (success) |

Route maps for these 4 episodes, baseline vs oracle_hint, rendered with
`code/plot_baseline_vs_oracle_4ep_grid.py` (reuses `topdown_route_map.render_route_overlay`
and the same green/red header-banner convention as
`artifacts/stop_gate_r3_oracle_hard_20260630_route_maps/hard11_stop_gate_r3_hint_action_arbiter_20260630_grid.png`):

- [`artifacts/baseline_4ep_return_grid_20260812.png`](artifacts/baseline_4ep_return_grid_20260812.png) — all 4 red (return fail); blue outbound reaches the goal fine, but the return path (magenta numbered order markers) never gets back near the green start marker.
- [`artifacts/oracle_hint_4ep_return_grid_20260812.png`](artifacts/oracle_hint_4ep_return_grid_20260812.png) — all 4 green (round-trip success); yellow `A1..A15` route-memory anchors visible (oracle_hint runs with `--route_memory`, baseline does not), return path follows the anchor chain back close to start.

**Note on the occupancy background:** neither `pure_navila_baseline_100ep_20260810` nor
`pure_oracle_hint_highsuccess100ep_20260811` was run with `--topdown_route_map`, so neither has
its own captured floor-slice occupancy map. The occupancy background in both grids is reused
from `canonical_report_next_stopgate_100ep_20260720_accumulated`'s captured maps for the same
4 `episode_idx` — occupancy is scene-geometry-only (not run-dependent), so this is a safe reuse,
not a mismatch between what's plotted and what actually happened during baseline/oracle_hint's
own runs (trajectories/anchors themselves come from each run's own measurement/trajectory files).
