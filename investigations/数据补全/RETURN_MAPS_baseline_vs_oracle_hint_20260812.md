## Route maps: baseline vs oracle_hint on 9 overlap episodes (2026-08-12)

Cross-referencing `final_data/pure_navila_baseline_100ep_20260810_full_results.tsv` against
`final_data/pure_oracle_hint_highsuccess100ep_20260811_full_results.tsv` by `episode_id`: 30
episode_ids overlap between the two 100-episode samples, 26 of those had outbound_success=True
in both. Of those 26, exactly 4 flip from baseline return-fail to oracle_hint return-success.

**Correction (2026-08-12, later):** the original version of this note claimed "no episode goes
the other way." That was wrong — re-checked against the raw `full_results.tsv` rows and there are
2 episodes where the reverse happens (baseline return-success, oracle_hint return-fail):
episode_id 1154 (episode_idx 670, X7HyMhZNoso, baseline dist 0.53 m success → oracle 7.05 m fail)
and episode_id 1700 (episode_idx 994, QUCTc6BB5sX, baseline dist 1.20 m success → oracle 4.38 m
fail). So oracle_hint is not a pure one-directional return-phase gain on this overlap set — it can
also make an individual episode worse. These 2 episodes are not included in the grids below (kept
to the original flip-to-success + divergence-ranked set), but the finding stands as a correction
to the record.

The grids were expanded from 2x2 to 3x3 by adding 5 more overlap episodes, picked (excluding
1154/1700, and excluding near-duplicate mirror-route pairs like 128/129 which share the same
neighbor episode and start/goal) by mean per-point divergence between the baseline and oracle_hint
return paths after arc-length resampling — i.e. cases where both configs still fail return, but the
actual path taken visibly differs:

| episode_id | episode_idx | scene | baseline final dist-to-start | oracle_hint final dist-to-start |
|---|---|---|---|---|
| 422 | 268 | QUCTc6BB5sX | 3.31 m (fail) | 2.75 m (success) |
| 602 | 367 | X7HyMhZNoso | 5.28 m (fail) | 1.49 m (success) |
| 1153 | 669 | X7HyMhZNoso | 6.57 m (fail) | 0.69 m (success) |
| 1378 | 813 | x8F5xyUWy9e | 5.57 m (fail) | 0.78 m (success) |
| 512 | 319 | 2azQ1b91cZZ | 10.25 m (fail) | 7.04 m (fail) |
| 1134 | 653 | Z6MFQCViBuw | 0.00 m (fail)* | 5.59 m (fail) |
| 476 | 295 | zsNo4HB9uLZ | 4.03 m (fail) | 8.45 m (fail) |
| 128 | 88 | EU6Fwq7SyZv | 3.09 m (fail) | 5.18 m (fail) |
| 33 | 20 | x8F5xyUWy9e | 0.00 m (fail)* | 5.46 m (fail) |

\* episodes 1134 and 33 have a baseline final position within ~0.02-0.05 m of the true start
(visually the red "final" marker sits right on top of the green "start" marker) yet are still
logged as return-fail — a stop-confirmation/logging edge case, not a distance-threshold miss.
Kept in because it makes the baseline-vs-oracle divergence in the paired oracle_hint panel even
more visually striking.

Route maps for these 9 episodes, baseline vs oracle_hint, rendered with
`code/plot_baseline_vs_oracle_9ep_grid.py` (reuses `topdown_route_map.render_route_overlay`
and the same green/red header-banner convention as
`artifacts/stop_gate_r3_oracle_hard_20260630_route_maps/hard11_stop_gate_r3_hint_action_arbiter_20260630_grid.png`):

- [`artifacts/baseline_9ep_return_grid_20260812.png`](artifacts/baseline_9ep_return_grid_20260812.png) — 4 red/fail flip episodes plus 5 more red/fail episodes with visibly different return paths from their oracle_hint counterpart.
- [`artifacts/oracle_hint_9ep_return_grid_20260812.png`](artifacts/oracle_hint_9ep_return_grid_20260812.png) — same 9 episodes under oracle_hint: the original 4 flip to green/success, the other 5 stay red/fail but the return path shape/endpoint clearly differs from the baseline panel.

**Note on the occupancy background:** neither `pure_navila_baseline_100ep_20260810` nor
`pure_oracle_hint_highsuccess100ep_20260811` was run with `--topdown_route_map`, so neither has
its own captured floor-slice occupancy map. The occupancy background in both grids is reused
from `canonical_report_next_stopgate_100ep_20260720_accumulated`'s captured maps for the same
4 `episode_idx` — occupancy is scene-geometry-only (not run-dependent), so this is a safe reuse,
not a mismatch between what's plotted and what actually happened during baseline/oracle_hint's
own runs (trajectories/anchors themselves come from each run's own measurement/trajectory files).
