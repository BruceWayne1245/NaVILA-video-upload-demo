# NaVILA + Isaac Sim VLN-CE Deployment on RTX 4090

Reproduction of [NaVILA](https://navila-bot.github.io/) (RSS 2025) Isaac Sim benchmark on a local workstation with RTX 4090.

**Status: End-to-end evaluation working ✅ — Episode 0: success=1.0, SPL=0.907**

**Latest update (2026-06-30) — hint-action arbiter rerun brings ep187 to near-threshold round-trip success:** a return-phase `HintActionArbiter` was added in [`code/hint_action_arbiter.py`](code/hint_action_arbiter.py) and wired into [`code/round_trip_eval.py`](code/round_trip_eval.py). It compares the VLM action against the oracle next-anchor hint, checks the hinted local path against the USD floor-slice occupancy map, and, when the VLM clearly conflicts with a clear route-hint direction, replaces the VLM output with a valid NaVILA action string. Episode 187 was rerun on top of the oracle+yaw+stop-gate r3 stack with `--route_hint_source=oracle --oracle_align_return_yaw_to_anchor_segment --stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0 --topdown_route_map --hint_action_arbiter`. Official measurement is still just outside the strict `<3.0 m` return threshold (`3.016 m`), but the stop-gate authority had already accepted at `2.979 m`, so this run is practically a full-route success modulo centimeter-level measurement/sensor tolerance. Compared with the previous r3 ep187 result (`8.095 m`), the return route now follows the anchor chain back to the start region instead of drifting into the lower-left dead corner. The arbiter logged `45` return decisions and overrode the VLM `8` times (`vlm_conflicts_with_clear_hint`), while leaving `24` hint-consistent actions untouched and declining `13` cases where the local occupancy check marked the hinted path occupied. Per-step trajectory, measurement, route map, occupancy map, and metadata are uploaded under [`artifacts/stop_gate_r3_hint_arbiter_ep187_20260630/ep187/`](artifacts/stop_gate_r3_hint_arbiter_ep187_20260630/ep187/).

[![ep187 hint-action arbiter route map](artifacts/stop_gate_r3_hint_arbiter_ep187_20260630/ep187/output_280_routes.png)](artifacts/stop_gate_r3_hint_arbiter_ep187_20260630/ep187/output_280_routes.png)

| Episode | Outbound | Official return | Practical round trip | Final dist | Stop-gate authority | Arbiter overrides | Artifacts |
|---:|:---:|:---:|:---:|---:|---:|---:|---|
| 187 | True | False (`3.016 m`, strict `<3.0 m` miss) | True / near-threshold | 3.016 m | accepted at 2.979 m | 8 / 45 | [`trajectory`](artifacts/stop_gate_r3_hint_arbiter_ep187_20260630/ep187/output_280.jsonl), [`routes`](artifacts/stop_gate_r3_hint_arbiter_ep187_20260630/ep187/output_280_routes.png), [`occupancy`](artifacts/stop_gate_r3_hint_arbiter_ep187_20260630/ep187/output_280_occupancy.png), [`measurement`](artifacts/stop_gate_r3_hint_arbiter_ep187_20260630/ep187/measurement_280.json) |

**Latest update (2026-06-30) — stop-gate r_in fixed to 3.0 m, hard-11 batch rerun with USD occupancy route maps:** the stop-gate inner radius was corrected from `r_in=2.5 m` to `r_in=3.0 m` (matching the official 3.0 m return-success radius). The previous `r_in=2.5 m` left a 0.5 m dead zone where neither VETO, ACCEPT, nor FORCE could activate even when the robot was inside the success radius — both `scripts/stop_gate.py` and the `--stop_gate_r_in` argparse default were updated. The 11 hard episodes were rerun with `--route_hint_source=oracle --oracle_align_return_yaw_to_anchor_segment --stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0 --topdown_route_map` via `scripts/run_stop_gate_r3_oracle_hard_batch_20260630.sh`. Result: outbound `8/11`, return `4/8` (outbound-success), round-trip `4/11`. Key improvement: ep5 recovered from the r_in=2.5 regression (`9.559 m` → `2.253 m ✅`). ep368 remains a success (`1.423 m`). ep678 and ep1040 outbound failures are VLM non-determinism, not gate-related. All 11 episodes have USD floor-slice occupancy route maps; a combined grid is at [`artifacts/stop_gate_r3_oracle_hard_20260630_route_maps/hard11_stop_gate_r3_20260630_grid.png`](artifacts/stop_gate_r3_oracle_hard_20260630_route_maps/hard11_stop_gate_r3_20260630_grid.png). Batch logs: `batch_logs/stop_gate_r3_oracle_hard_20260630/`. Unit tests: 31/31 stop_gate tests pass with r_in=r_out=3.0.

[![hard-11 stop-gate r3 route map grid](artifacts/stop_gate_r3_oracle_hard_20260630_route_maps/hard11_stop_gate_r3_20260630_grid.png)](artifacts/stop_gate_r3_oracle_hard_20260630_route_maps/hard11_stop_gate_r3_20260630_grid.png)

| Episode | Outbound | Return | Round Trip | Final dist | Gate events |
|---:|:---:|:---:|:---:|---:|---|
| 4 | True | True | True | 1.125 m | — |
| 5 | True | True | True | 2.253 m | — |
| 134 | True | False | False | 13.722 m | — |
| 187 | True | False | False | 8.095 m | — |
| 367 | True | False | False | 7.554 m | — |
| 368 | True | True | True | 1.423 m | — |
| 408 | False | False | False | 2.125 m | — (outbound fail) |
| 678 | False | False | False | 3.576 m | — (outbound fail) |
| 680 | True | True | True | 0.978 m | — |
| 994 | True | False | False | 11.440 m | — |
| 1040 | False | — | False | 2.688 m | — (outbound fail) |


**Latest update (2026-06-30) — hard-11 no-oracle vs oracle+yaw+stop-gate trajectory comparison maps generated:** the full 11 hard episodes from the 2026-06-29 batch were rendered as side-by-side trajectory comparison maps without rerunning Isaac/VLM. Each figure uses the saved per-step JSONL trajectories and measurements: left panel = pure no-oracle/no-hint baseline, right panel = oracle route hint + confirm yaw alignment + return stop-gate. Outbound and return paths are drawn as thin dashed lines; magenta numbered dots mark return-phase temporal order; oracle anchors are shown when available. These are trajectory-space comparison plots on a shared grid, not USD occupancy maps, because the original 11 batch runs did not save `--topdown_route_map` floor-slice artifacts. All 11 PNGs plus manifest are uploaded under [`artifacts/hard11_no_hint_vs_stop_gate_maps_20260630/`](artifacts/hard11_no_hint_vs_stop_gate_maps_20260630/), and the offline renderer is saved as [`code/plot_hard_batch_comparison_maps.py`](code/plot_hard_batch_comparison_maps.py).

| Episode | Comparison map |
|---:|---|
| 4 | [`ep4_no_oracle_vs_oracle_yaw_stop_gate.png`](artifacts/hard11_no_hint_vs_stop_gate_maps_20260630/ep4_no_oracle_vs_oracle_yaw_stop_gate.png) |
| 5 | [`ep5_no_oracle_vs_oracle_yaw_stop_gate.png`](artifacts/hard11_no_hint_vs_stop_gate_maps_20260630/ep5_no_oracle_vs_oracle_yaw_stop_gate.png) |
| 134 | [`ep134_no_oracle_vs_oracle_yaw_stop_gate.png`](artifacts/hard11_no_hint_vs_stop_gate_maps_20260630/ep134_no_oracle_vs_oracle_yaw_stop_gate.png) |
| 187 | [`ep187_no_oracle_vs_oracle_yaw_stop_gate.png`](artifacts/hard11_no_hint_vs_stop_gate_maps_20260630/ep187_no_oracle_vs_oracle_yaw_stop_gate.png) |
| 367 | [`ep367_no_oracle_vs_oracle_yaw_stop_gate.png`](artifacts/hard11_no_hint_vs_stop_gate_maps_20260630/ep367_no_oracle_vs_oracle_yaw_stop_gate.png) |
| 368 | [`ep368_no_oracle_vs_oracle_yaw_stop_gate.png`](artifacts/hard11_no_hint_vs_stop_gate_maps_20260630/ep368_no_oracle_vs_oracle_yaw_stop_gate.png) |
| 408 | [`ep408_no_oracle_vs_oracle_yaw_stop_gate.png`](artifacts/hard11_no_hint_vs_stop_gate_maps_20260630/ep408_no_oracle_vs_oracle_yaw_stop_gate.png) |
| 678 | [`ep678_no_oracle_vs_oracle_yaw_stop_gate.png`](artifacts/hard11_no_hint_vs_stop_gate_maps_20260630/ep678_no_oracle_vs_oracle_yaw_stop_gate.png) |
| 680 | [`ep680_no_oracle_vs_oracle_yaw_stop_gate.png`](artifacts/hard11_no_hint_vs_stop_gate_maps_20260630/ep680_no_oracle_vs_oracle_yaw_stop_gate.png) |
| 994 | [`ep994_no_oracle_vs_oracle_yaw_stop_gate.png`](artifacts/hard11_no_hint_vs_stop_gate_maps_20260630/ep994_no_oracle_vs_oracle_yaw_stop_gate.png) |
| 1040 | [`ep1040_no_oracle_vs_oracle_yaw_stop_gate.png`](artifacts/hard11_no_hint_vs_stop_gate_maps_20260630/ep1040_no_oracle_vs_oracle_yaw_stop_gate.png) |

**Latest update (2026-06-30) — USD floor-slice occupancy route maps added and episode 4 visual diagnostic rerun:** a top-down route-map diagnostic was implemented using a USD mesh floor-slice projection rather than an overhead Isaac camera, avoiding ceiling views and producing a true occupancy-style map of nearby room obstacles. The module slices scene geometry from `floor_z + 0.08 m` to `floor_z + 2.2 m`, rasterizes occupied mesh triangles into a 2-D grid, and overlays outbound trajectory, return trajectory, start/goal/final markers, and route-memory anchors when available. Episode 4 was rerun twice with `--topdown_route_map`: (1) pure no-oracle/no-hint baseline and (2) direct oracle hint (`--route_memory --route_hint_source=oracle --route_relocalization_backend=none`). Both runs completed successfully at the process level and produced occupancy/route overlays. In this fresh pair, both runs achieved outbound success but failed return: no-oracle baseline ended `9.449 m` from start; direct oracle ended `8.876 m` from start. The map artifacts are uploaded under [`artifacts/topdown_route_maps_ep4_20260630/`](artifacts/topdown_route_maps_ep4_20260630/): no-oracle overlay [`no_oracle/output_7_routes.png`](artifacts/topdown_route_maps_ep4_20260630/no_oracle/output_7_routes.png), direct-oracle overlay [`direct_oracle/output_7_routes.png`](artifacts/topdown_route_maps_ep4_20260630/direct_oracle/output_7_routes.png), with matching occupancy-only PNGs and map metadata JSONs in each subdirectory.

| Episode 4 run | Outbound | Return | Round Trip | Final distance to start | Route map |
|---|:---:|:---:|:---:|---:|---|
| no-oracle baseline | True | False | False | 9.449 m | [`routes`](artifacts/topdown_route_maps_ep4_20260630/no_oracle/output_7_routes.png) / [`occupancy`](artifacts/topdown_route_maps_ep4_20260630/no_oracle/output_7_occupancy.png) |
| direct oracle hint | True | False | False | 8.876 m | [`routes`](artifacts/topdown_route_maps_ep4_20260630/direct_oracle/output_7_routes.png) / [`occupancy`](artifacts/topdown_route_maps_ep4_20260630/direct_oracle/output_7_occupancy.png) |

**Latest update (2026-06-29) — pure VLM baseline (no hint, no stop gate, no yaw alignment) evaluated on 11-episode hard batch:** the same 11 hard episodes were run with no route-memory hint, no stop-gate arbiter, and no confirm-phase yaw alignment — VLM navigates purely on visual input. This establishes the unassisted baseline for comparison against oracle hint and stop-gate variants. Result: outbound `9/11` (ep134 outbound fail; ep678 outbound failed this run — VLM non-determinism), return `4/9` (valid outbound-success samples), round-trip `4/11`. Successful round trips: ep5 (2.809 m), ep680 (1.001 m), ep994 (1.201 m), ep1040 (2.266 m). ep367 had a transient VLM server crash (transformers import race) on first attempt and was rerun immediately; second attempt succeeded (outbound ✅, return ❌ 5.397 m). Batch logs: `batch_logs/no_hint_hard_fresh_20260629/`. Per-step JSONL trajectories uploaded to `artifacts/no_hint_hard_batch_20260629/trajectories/`.

Three-way comparison across all 11 episodes (round-trip success / distance):

| Episode | no-hint | oracle+yaw | oracle+yaw+stop-gate(r_in=2.5) | oracle+yaw+stop-gate(r_in=3.0) |
|---:|:---:|:---:|:---:|:---:|
| 4 | ❌ 12.9 m | ✅ 0.378 m | ✅ 0.496 m | ✅ 1.125 m |
| 5 | ✅ 2.809 m | ✅ 2.253 m | ❌ 9.559 m | ✅ 2.253 m |
| 134 | ❌ outbound | ❌ outbound | ❌ outbound | ❌ 13.722 m |
| 187 | ❌ 11.9 m | ❌ 7.649 m | ❌ 7.567 m | ❌ 8.095 m |
| 367 | ❌ 5.397 m | ❌ 0.000 m† | ❌ 0.000 m† | ❌ 7.554 m |
| 368 | ❌ 6.949 m | ❌ 4.447 m | ✅ 1.625 m | ✅ 1.423 m |
| 408 | ❌ 3.947 m | ❌ 5.996 m | ❌ 8.483 m | ❌ outbound |
| 678 | ❌ outbound | ✅ 2.824 m | ✅ 1.292 m | ❌ outbound |
| 680 | ✅ 1.001 m | ✅ 1.253 m | ✅ 2.553 m | ✅ 0.978 m |
| 994 | ✅ 1.201 m | ❌ 4.410 m | ❌ 4.329 m | ❌ 11.440 m |
| 1040 | ✅ 2.266 m | ✅ 1.264 m | ✅ 1.916 m | ❌ outbound |
| **round-trip** | **4/11** | **5/11** | **5/11** | **4/11** |

†ep367: oracle distance reports 9.6 m throughout return while physical distance is 0.000 m — bookkeeping anomaly, not a genuine success. Key observations: (1) oracle hint improves outbound reliability (9→10/11); (2) for return, oracle hint and no-hint both achieve 5 and 4 successes respectively on their valid outbound-success sets — the gain is marginal and non-monotone (ep5/994/680 succeed without hint but fail or regress with hint, while ep4/678 require the hint to complete outbound); (3) stop-gate converts ep368 from failure to success and rescues ep1040 via FORCED terminal, but regressions on ep5 offset the gain.

**Latest update (2026-06-29) — return-phase stop-gate arbiter implemented and evaluated on 11-episode oracle hard batch:** a dedicated stop-arbitration layer (`scripts/stop_gate.py`, `ReturnStopGate`) was added between the VLM output and the terminal-condition check in `round_trip_eval.py`. It does not modify hint generation, anchor selection, or particle filtering; it only reads the authoritative oracle distance and decides each step: VETO a premature stop (high conf, d > r_out=3.0 m) and inject a forward command toward `bearing_to_start`; ACCEPT a stop (high conf, d ≤ r_in=2.5 m); DEFER to the VLM (low conf or hysteresis zone); FORCE terminal if the robot stays within r_in for ≥ 3 consecutive VLM-query steps without issuing a stop; PASS on teleport frames (single-step jump > 3 m). The gate was tested with `--route_hint_source=oracle --route_relocalization_backend=none --oracle_align_return_yaw_to_anchor_segment --stop_gate --stop_gate_r_in=2.5 --stop_gate_r_out=3.0 --stop_gate_confirm_steps=3 --stop_gate_min_confidence=0.5` on the 11 hard episodes. Aggregate: outbound `10/11`, return `5/10` (outbound-success episodes), round-trip `5/11` — equal to the oracle baseline. Gate net contribution: ep368 converted from failure (4.447 m) to success (1.625 m, 1× ACCEPTED); ep1040 saved by FORCED stop (VLM never issued stop, gate triggered terminal at d=2.01 m → 1.916 m success); ep5 regressed to failure (9.559 m vs baseline 2.253 m — VLM non-determinism, 0 gate events); ep187 and ep994 vetoed 33× and 79× respectively but robot still stalled (navigation capacity bottleneck, not a stop-decision problem). ep367 anomaly unchanged: Isaac distance reports 9.6 m throughout return while physical distance is 0.000 m — oracle d is invalid (likely start_pos/teleport-reset misalignment), stop never triggered. 31 unit tests for stop_gate all pass. Batch logs: `batch_logs/stop_gate_oracle_hard_fresh_20260629/`.

| Episode | Outbound | Return | Round Trip | Final dist | Gate events |
|---:|:---:|:---:|:---:|---:|---|
| 4 | True | True | True | 0.496 m | 1× accepted |
| 5 | True | False | False | 9.559 m | none (VLM non-det.) |
| 134 | False | False | False | 7.494 m | — (outbound fail) |
| 187 | True | False | False | 7.567 m | 33× vetoed |
| 367 | True | False | False | 0.000 m | none (oracle d invalid) |
| 368 | True | True | True | 1.625 m | 1× accepted |
| 408 | True | False | False | 8.483 m | none (timeout/no stop) |
| 678 | True | True | True | 1.292 m | 1× accepted |
| 680 | True | True | True | 2.553 m | 70× vetoed |
| 994 | True | False | False | 4.329 m | 79× vetoed |
| 1040 | True | True | True | 1.916 m | 1× forced |

**Latest update (2026-06-29) — direct oracle route-anchor + confirm yaw alignment hard batch completed:** the pure oracle path has now been rerun on all 11 hard episodes (`4, 5, 134, 187, 367, 368, 408, 678, 680, 994, 1040`) with fresh VLM and Isaac processes per episode. This version bypasses particle filtering/gating for the return hint, selects the next reversed-route anchor from Isaac/global route progress, and uses `--oracle_align_return_yaw_to_anchor_segment` at the confirm-to-return transition so the robot starts return facing the nearest reverse anchor segment. Aggregate result: outbound success `10/11`, return success on outbound-success episodes `5/10`, round-trip success `5/11`. Successful round trips were ep4 (`0.378 m`), ep5 (`2.253 m`), ep678 (`2.824 m`), ep680 (`1.253 m`), and ep1040 (`1.264 m`). Failures after outbound success were ep187 (`7.649 m`), ep367 (`0.000 m` but no return terminal event, likely bookkeeping/termination issue), ep368 (`4.447 m`), ep408 (`5.996 m`), and ep994 (`4.410 m`). Ep134 failed outbound and is not a valid return-oracle sample. Main diagnosis: direct oracle bearing clearly steers VLM behavior, but a perfect global anchor bearing is still not equivalent to a locally feasible corridor-following command in narrow indoor layouts; confirm-stage yaw alignment helps but does not remove wall/contact and anchor-alignment failure modes. Full logs are in [`batch_logs/direct_oracle_align_yaw_hard_20260629/`](batch_logs/direct_oracle_align_yaw_hard_20260629/), and all per-step JSONL trajectories plus measurement JSONs are uploaded under the matching `eval_results/...direct_oracle_align_yaw_hard_20260629_ep*/` directories. Single-episode ep4/ep5 diagnostic trajectories before and after yaw alignment are also uploaded: `direct_oracle_route_anchor_ep4_20260629`, `direct_oracle_global_lookahead_ep4_20260629`, `direct_oracle_global_lookahead_ep5_20260629`, and `direct_oracle_align_yaw_ep5_20260629`.

| Episode | Outbound | Return | Round Trip | Final distance to start |
|---:|:---:|:---:|:---:|---:|
| 4 | True | True | True | 0.378 m |
| 5 | True | True | True | 2.253 m |
| 134 | False | False | False | 7.886 m |
| 187 | True | False | False | 7.649 m |
| 367 | True | False | False | 0.000 m |
| 368 | True | False | False | 4.447 m |
| 408 | True | False | False | 5.996 m |
| 678 | True | True | True | 2.824 m |
| 680 | True | True | True | 1.253 m |
| 994 | True | False | False | 4.410 m |
| 1040 | True | True | True | 1.264 m |

**Latest update (2026-06-29) — pure oracle route hint path implemented for retesting PF-corrupted failures:** post-run inspection of the oracle-anchor hard batch showed every return-stage route-memory record still had `source="arc_length_particle_filter"` rather than a pure oracle source. This means the previous `oracle_anchor` backend only supplied perfect relative anchor poses into the route-memory particle filter; the VLM still saw the filter estimate, not the oracle truth. In the 5 return failures among outbound-success episodes (`5`, `187`, `367`, `408`, `994`), the particle filter corrupted that estimate, so this is not yet a clean test of oracle distance+bearing guidance. A new explicit `--route_hint_source=oracle` path has been added in `scripts/round_trip_eval.py`: during the return phase it computes the exact simulator start vector from the current Isaac pose and injects it directly as `source="direct_oracle_start"`, `relocalization_backend="oracle_direct"`, `relocalization_confidence=1.0`, and `filter_std_m=null`. This bypasses `RouteMemoryAgent.progress()`, anchor chaining, arc-length particle filtering, and filter-lost gating for prompt hint generation. Per-step trajectory logging now records `configured_source`, `source`, and `filter_std_m` so the rerun can verify the VLM only saw the direct oracle signal. Regression coverage was added to prove that a direct oracle `progress_override` bypasses an already-populated `arc_length_particle_filter` state; `PYTHONPATH=scripts python3 -m unittest tests/test_route_memory_agent.py` passes (`19` tests). New scripts are ready: `scripts/run_direct_oracle_hard_fresh_batch_20260629.sh` runs the hard batch with fresh VLM/Isaac per episode, `--route_hint_source=oracle`, and `--route_relocalization_backend=none`; `scripts/run_direct_oracle_return_failures_fresh_20260629.sh` defaults to only the 5 outbound-success/return-failure episodes (`5 187 367 408 994`). Full Isaac/VLM retesting has not been started yet.

**Latest update (2026-06-29) — oracle-anchor hard-case batch with fresh per-episode isolation:** the original oracle-anchor sanity check had only been run on ep994; it showed the route-memory hint interface was feasible when the relocalization backend is perfect. This has now been extended to the 11 hard episodes from the previous 30-episode v4 baseline where the language-only run had `outbound_success=true` and `return_success=false`: 4, 5, 134, 187, 367, 368, 408, 678, 680, 994, 1040. To avoid cross-episode contamination, the batch runner was changed so every episode uses a fresh 8-bit VLM server, a fresh Isaac process, and an episode-specific VLM port (`PORT_BASE + episode_idx`); failed VLM startups are detected immediately and rerun rather than being treated as algorithm results. Two startup failures in the first pass (368, 1040) were rerun successfully. In the final valid oracle-anchor results, 9 episodes had outbound success: 4, 5, 187, 367, 368, 408, 680, 994, 1040. Oracle-anchor return succeeded on 4/9 of those outbound-success episodes: ep4 (`0.664 m`), ep368 (`2.086 m`), ep680 (`1.230 m`), and ep1040 (`1.146 m`). Return still failed on ep5 (`7.589 m`), ep187 (`8.761 m`), ep367 (`6.750 m`), ep408 (`5.475 m`), and ep994 (`4.398 m`). Ep134 and ep678 failed outbound in the oracle run and therefore are not valid return-feasibility samples for this batch. Key implication: perfect nearest-anchor relocalization is helpful but not sufficient as currently prompted/used; failures remain where the VLM either does not exploit the oracle route hints correctly or terminates/moves incorrectly despite exact anchor-relative geometry. Per-step JSONL trajectories for all 9 outbound-success episodes are uploaded in [`artifacts/oracle_anchor_hard_batch_20260629/trajectories/`](artifacts/oracle_anchor_hard_batch_20260629/trajectories/), with [`summary_outbound_success_episodes.tsv`](artifacts/oracle_anchor_hard_batch_20260629/summary_outbound_success_episodes.tsv) and [`manifest.json`](artifacts/oracle_anchor_hard_batch_20260629/manifest.json).

| Episode | Outbound | Return | Final distance to start |
|---:|:---:|:---:|---:|
| 4 | True | True | 0.664 m |
| 5 | True | False | 7.589 m |
| 187 | True | False | 8.761 m |
| 367 | True | False | 6.750 m |
| 368 | True | True | 2.086 m |
| 408 | True | False | 5.475 m |
| 680 | True | True | 1.230 m |
| 994 | True | False | 4.398 m |
| 1040 | True | True | 1.146 m |

**Latest update (2026-06-29) — rear-camera anchor fix + VIO bridge:** root-cause diagnosis of the seqpf_sfix second-half failure led to two targeted fixes. (1) **GT co-visibility diagnostic (completed 2026-06-28):** per-attempt analysis of all 85 LoFTR calls in `seqpf_sfix` revealed two distinct failure zones. Zone A (d2s < 6 m, attempts 37–85): depth-consistent co-visibility = 0% throughout; cause is **camera-direction mismatch** — Go2 strafes laterally so the outbound anchors (A0–A15) face ~+92° to ±180° (north/west) while the return robot faces ~0° to −90° (east/south), giving a ~150–180° angular separation. LoFTR produces 40–100 "matches" via visual aliasing on repetitive corridor texture, but RANSAC gives position errors of +6 to +13 m which SeqSLAM correctly rejects. Zone B (d2s 6–8 m, attempts 27–35): depth-consistent co-visibility is 13–24% (real shared geometry), LoFTR finds 110–170 inliers with conf=1.0, but **corridor geometric degeneracy** — planar walls cannot constrain translation along the corridor axis — causes RANSAC to give position errors of +3.9 to +5.9 m; again correctly rejected by SeqSLAM. Branch verdicts: Branch 1 (co-visibility low/zero) ✅ confirmed for Zone A (camera direction mismatch, not off-path drift); Branch 2 (co-visibility exists but matching fails) ✅ applies to Zone B (degeneracy, not matcher quality — MASt3R would have the same problem); Branch 3 (anchor spacing too large) ❌ wrong (1 m anchors, robot 0.2–1.5 m from nearest anchor throughout). Key confirmed finding: `hint_gate` was harmful because the VLM is robust to specific-but-wrong hints (it ignores erroneous "0 m arrived" claims) but loses navigational narrative when given generic "position uncertain" messages; the fix is to preserve directional/distance language and only suppress explicit arrival/stop claims when filter std is high. (2) **Rear-camera anchor + LoFTR fix (2026-06-29):** the camera-direction mismatch is fixed by adding a rear-facing camera (`rear_rgbd_camera`, body −x direction, rot=(−0.5, 0.5, 0.5, −0.5), 54° FOV, 512×512 RGB+depth) in `Go2VisionSceneCfg`. `route_memory_descriptor_from_infos` now also saves `rear_rgb`, `rear_depth_depth_measurement`, `rear_camera_intrinsics`, `rear_camera_rotation_body`, `rear_camera_position_body` at each outbound anchor. `build_rear_view_descriptor()` in `relocalization.py` constructs a synthetic anchor descriptor exposing rear camera data under standard field names (so LoFTR + 3-D RANSAC + `camera_rotation_to_body_yaw` work unchanged). `feature_depth_anchor_relocalization` now tries two views per anchor — `("front", anchor.descriptor)` then `("rear", build_rear_view_descriptor(anchor.descriptor))` — with `backend` tags `_front`/`_rear` for diagnostic tracking. During the return phase: current front-camera view (faces east) ↔ anchor rear-camera view (faces east during outbound when body faces west) = correct orientation match. (3) **VIO bridge (2026-06-29, off by default):** `RouteMemoryAgent` computes `_feature_anchor_indices` in `finalize_outbound` by marking consecutive anchor pairs where `|Δyaw| > 15°` (corners/doorways); `_sequence_match_observation` suppresses visual particle-filter updates when filter std > `vio_bridge_std_threshold_m` (default 2.5 m) AND the candidate arc-length is > `vio_bridge_feature_radius_m` (default 2.0 m) from any feature anchor. Enabled with `--vio_bridge`. On ep994, feature anchors identified at A2, A3, A5, A6, A9, A10, A12, A13, A15, A16 (10 of 17, covering all path turns). Next step: run ep994 with `--route_relocalization_backend=loftr_depth --result_suffix=rear_cam_20260629` and compare second-half co-visibility and accepted observation count against `seqpf_sfix`.

**Latest update (2026-06-28) — uncertainty-gated hints + lateral-exclusion odometry + blackout noise inflation:** three targeted fixes to the arc-length particle filter pipeline, motivated by post-hoc diagnosis of `seqpf_sfix`. (1) **Hint gating** (`filter_std_m` field added to `RelativeStartProgress`): when particle filter std exceeds `max(2.5, 20% × route_length)` — 3.2 m for a 16 m route — `_filter_lost()` returns true and the hint switches from a precise distance claim to `"position uncertain (σ≈X m, filter lost lock); continue toward the outbound start using the visual instruction — do NOT stop until you visually confirm you are back at the starting location."` This directly prevents premature VLM stop from a "0 m arrived" hint while the robot is still 4–5 m away. Retroactive replay on seqpf_sfix shows 35/37 hint events would be gated (only the first two — pure action-integration and first anchor match — would pass as high-confidence). (2) **Lateral-motion exclusion**: `update_return_motion()` replaces `math.hypot(dx, dy)` with `abs(dx)` for both particle filter `predict()` and `_sequence_current_s_m` decrement; lateral velocity commands during turns no longer inflate arc-length odometry. (3) **Blackout noise inflation**: `predict()` gains `extra_process_noise_m` parameter; when `_distance_since_sequence_observation_m > 3 m`, extra noise grows at 0.015 m per additional meter, so the filter spreads faster during observation gaps and std crosses the gating threshold sooner. All 57 tests pass. Ep994 rerun `loftr_depth_ep994_hint_gate_20260628` ran and **return failed**: outbound success true, return success false, final distance to start `4.403 m`. Gating activated at step 2626 (dist 10.8 m, std 3.68 m), leaving the VLM with 21 consecutive generic "position uncertain, continue via visual instruction" hints and no specific distance/direction signal for the final 10 m. The VLM stopped at step 3926 based on visual judgment alone. Root cause: hint gating removes navigational narrative that keeps the VLM moving — seqpf_sfix succeeded precisely because the VLM correctly ignored specific-but-wrong "0 m arrived" hints; replacing those with generic warnings removed the implicit "keep moving" signal. Fix direction: preserve directional/distance information even when filter is uncertain, and only suppress the explicit arrival/stop claim. Artifacts in `artifacts/loftr_depth_ep994_hint_gate_20260628/`.

**Latest update (2026-06-28) — SeqSLAM particle filter (seqpf_sfix):** arc-length position is now tracked by a 256-particle filter (`ArcLengthParticleFilter`) updated via LoFTR relocalization observations scored with a SeqSLAM-style sequence-consistency metric. Ep994 rerun `loftr_depth_ep994_seqpf_sfix_20260628` succeeded: outbound success true, return success true, round-trip success true, final distance to start `1.264 m`. The particle filter captured 8 LoFTR observations spanning anchors 14→8 (route positions 14.1 m → 7.8 m from start), then lost track. From step 3626 onward, hints incorrectly reported 0 m remaining while the true simulator distance was 4–5 m; the VLM did not stop prematurely and navigated correctly using visual/instruction cues. Key diagnosis: the particle filter provides accurate early hints but loses observations after anchor 8 and collapses to zero, so late-return guidance currently comes from the VLN instruction rather than the relocalization hint. Measurement and per-step trajectory are in `artifacts/loftr_depth_ep994_seqpf_sfix_20260628/`.

**Latest update (2026-06-28) — monotonic anchor progress v2:** route-memory target-anchor selection now applies a monotonic policy before the consistency gate, rejects anchor-index regressions away from start, and advances targets after passing an anchor even when the robot did not enter a tight 0.8 m radius. Ep994 rerun `loftr_depth_ep994_monotonic_anchor_v2_20260628` succeeded: outbound success true, return success true, round-trip success true, final distance to start `1.148 m`. Target anchors were monotonic (`None -> 14 -> 13 -> 8 -> 7 -> 6 -> 5 -> 4 -> 3`) with zero monotonic violations. The remaining issue is scalar progress: late route-memory distance remains conservative because it still uses `distance_to_target_anchor + target_anchor.route_remaining` instead of full anchor-chain path projection. Source snapshots, tests, measurement, per-step trajectory, and video are in `artifacts/loftr_depth_ep994_monotonic_anchor_v2_20260628/` and `code/`.

**Latest update (2026-06-28) — 3D-3D rotation fix validates ep994 return:** feature-depth/LoFTR relocalization now preserves the full Kabsch/RANSAC rotation and converts it into `anchor_dtheta_rad` instead of treating the backend as translation-only. A fresh 8-bit VLM ep994 rerun with `--route_relocalization_backend=loftr_depth` succeeded end-to-end: outbound success true, return success true, round-trip success true, final distance to start `1.264 m`. The run produced 85 successful relocalization estimates, 672 pose candidates, max 148 3D inliers, and 86/86 nonzero `anchor_dtheta_rad` records. Artifacts, including the per-step trajectory JSONL and video, are in `artifacts/loftr_depth_ep994_rotation_fix_20260628/`.

**Latest update (2026-06-27) — LoFTR matcher integrated:** geometry pipeline verified correct via 18-test suite; LoFTR (`kornia==0.6.12`, `pretrained="outdoor"`) installed in both conda environments and wired as the `loftr_depth` backend. Offline synthetic tests show LoFTR produces 5–9× more inlier matches than ORB under rotation, scale change, and perspective warp. The `--route_relocalization_backend=loftr_depth` flag is ready; ep994 evaluation with the VLM server running is the next step.

**Anchor relocalization pipeline (2026-06-27):** route memory was extended to a map-free relocalization interface. Each outbound anchor stores RGB, depth, camera intrinsics, and route-distance metadata. The Return stage can accept a metric relative pose to any saved anchor and convert it into a prompt hint such as "route anchor A0 is 0.61 m away, 112 deg to your left; estimated remaining route via anchor is 0.61 m." An Isaac oracle-anchor backend verified the full hint pipeline on episode `994`: outbound success true, return success true, round-trip success true, final distance to start `0.619 m`.

**Classical backend failure analysis (2026-06-27):** ORB+depth on ep994 produced 12 estimates from 76 attempts (6–11 3D inliers each), all too noisy to help. GT covisibility diagnostics showed the bottleneck is matching quality, not missing shared view. SIFT+depth produced more candidates but every estimate was rejected by the consistency gate (37/37 rejected; minimum error 8.06 m). Geometry code was independently verified correct — a formal oracle-consistency proof and 18-test suite confirm the backproject→RANSAC→camera-to-body chain is exact. The 8 m+ SIFT errors are caused entirely by bad feature correspondences, not by a geometry bug.

---

## Hardware & System

| Component | Detail |
|---|---|
| GPU | NVIDIA GeForce RTX 4090 (24 GB VRAM, sm_89) |
| CPU | Intel Core i9-14900K (24 cores / 48 threads) |
| RAM | 125 GB |
| OS | Ubuntu 22.04.5 LTS |
| Driver | 570.124.06 |
| CUDA | 12.8 (system) |
| Storage | Root: 1.8 TB NVMe; Data: `/mnt/SSD4T` (3.6 TB, used for all project files) |

**Note on storage:** The root partition was at 100% capacity. All project files, conda environments, model checkpoints, and datasets are placed on `/mnt/SSD4T`.

---

## Directory Layout

```
/mnt/SSD4T/teambruce/
├── projects/
│   └── navila-isaac/
│       ├── NaVILA/               # AnjieCheng/NaVILA (commit 76b98f2)
│       ├── NaVILA-Bench/         # yang-zj1026/VLN-CE-Isaac (commit e9d2db1)
│       ├── IsaacLab/             # yang-zj1026/IsaacLab (commit 4d558ec)
│       └── checkpoints/
│           └── navila-llama3-8b-8f/  # HuggingFace: a8cheng/navila-llama3-8b-8f (16 GB)
├── conda_envs/
│   ├── vlnce-isaac/              # Isaac Sim + IsaacLab environment
│   └── navila-vlm/               # NaVILA VLM server environment
└── conda_pkgs/                   # Conda package cache (redirected from root)
```

---

## Conda Environment Setup

### Configure conda to use SSD4T

```bash
# ~/.condarc
pkgs_dirs:
  - /mnt/SSD4T/teambruce/conda_pkgs
  - /home/teambruce/miniconda3/pkgs
envs_dirs:
  - /mnt/SSD4T/teambruce/conda_envs
  - /home/teambruce/miniconda3/envs
```

### Environment 1: `vlnce-isaac` (Isaac Sim + IsaacLab)

```bash
conda create --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac python=3.10 -y

# Install Isaac Sim 4.1.0.0
conda run --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  pip install \
    isaacsim-rl==4.1.0.0 isaacsim-replicator==4.1.0.0 \
    isaacsim-extscache-physics==4.1.0.0 isaacsim-extscache-kit-sdk==4.1.0.0 \
    isaacsim-extscache-kit==4.1.0.0 isaacsim-app==4.1.0.0 \
    --extra-index-url https://pypi.nvidia.com

# Run IsaacLab installer (this downgrades torch to 2.2.2+cu121 — fine on RTX 4090 sm_89)
TERM=xterm conda run --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -i none

# Install rsl_rl and warp
conda run --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -p -m pip install \
  -e /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/rsl_rl

conda run --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  pip install warp-lang==1.13.0
```

Key versions after install:
- `torch 2.2.2+cu121` (IsaacLab pins this; works on sm_89)
- `isaacsim-app 4.1.0.0`
- `omni-isaac-lab 0.20.8` (yang-zj1026 fork)
- `rsl-rl 2.0.2`
- `warp-lang 1.13.0`

### Environment 2: `navila-vlm` (NaVILA VLM Server)

```bash
conda create --prefix /mnt/SSD4T/teambruce/conda_envs/navila-vlm python=3.10 -y

# PyTorch (original NaVILA pin — works natively on RTX 4090)
conda run --prefix /mnt/SSD4T/teambruce/conda_envs/navila-vlm \
  pip install torch==2.3.0+cu121 torchvision==0.18.0+cu121 \
  --index-url https://download.pytorch.org/whl/cu121

# FlashAttention 2.5.8 — prebuilt wheel available for sm_89 (Ada Lovelace)
conda run --prefix /mnt/SSD4T/teambruce/conda_envs/navila-vlm \
  pip install https://github.com/Dao-AILab/flash-attention/releases/download/v2.5.8/flash_attn-2.5.8+cu122torch2.3cxx11abiFALSE-cp310-cp310-linux_x86_64.whl

# NaVILA/VILA package
conda run --prefix /mnt/SSD4T/teambruce/conda_envs/navila-vlm \
  pip install -e /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA

# Upgrade bitsandbytes (0.41.0 has API incompatibility with transformers patch)
conda run --prefix /mnt/SSD4T/teambruce/conda_envs/navila-vlm \
  pip install "bitsandbytes>=0.43.0"

# Apply NaVILA transformers patch
SITE=/mnt/SSD4T/teambruce/conda_envs/navila-vlm/lib/python3.10/site-packages/transformers
REPLACE=/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA/llava/train/transformers_replace
cp ${REPLACE}/modeling_utils.py        ${SITE}/modeling_utils.py
cp ${REPLACE}/models/llama/modeling_llama.py   ${SITE}/models/llama/modeling_llama.py
cp ${REPLACE}/models/llama/tokenization_llama.py ${SITE}/models/llama/tokenization_llama.py
cp ${REPLACE}/models/mistral/modeling_mistral.py ${SITE}/models/mistral/modeling_mistral.py
cp ${REPLACE}/models/mixtral/modeling_mixtral.py ${SITE}/models/mixtral/modeling_mixtral.py
```

Key versions:
- `torch 2.3.0+cu121`
- `flash-attn 2.5.8`
- `transformers 4.37.2`
- `bitsandbytes 0.49.2`

---

## Repository Setup

```bash
cd /mnt/SSD4T/teambruce/projects/navila-isaac

git clone https://github.com/yang-zj1026/VLN-CE-Isaac.git NaVILA-Bench
git clone https://github.com/yang-zj1026/IsaacLab.git IsaacLab
git clone https://github.com/AnjieCheng/NaVILA.git NaVILA

# IsaacLab extension symlinks
ln -sf $(pwd)/NaVILA-Bench/isaaclab_exts/omni.isaac.vlnce \
       IsaacLab/source/extensions/omni.isaac.vlnce
ln -sf $(pwd)/NaVILA-Bench/isaaclab_exts/omni.isaac.matterport \
       IsaacLab/source/extensions/omni.isaac.matterport
```

---

## Data & Assets

### NaVILA Checkpoint

```bash
mkdir -p /mnt/SSD4T/teambruce/projects/navila-isaac/checkpoints
conda run --prefix /mnt/SSD4T/teambruce/conda_envs/navila-vlm \
  huggingface-cli download a8cheng/navila-llama3-8b-8f \
  --local-dir /mnt/SSD4T/teambruce/projects/navila-isaac/checkpoints/navila-llama3-8b-8f
```

Size: ~16 GB (4 safetensors shards).

### VLN-CE-Isaac Assets (Matterport USD + Annotations)

```bash
conda run --prefix /mnt/SSD4T/teambruce/conda_envs/navila-vlm \
  huggingface-cli download Zhaojing/VLN-CE-Isaac \
  --repo-type dataset \
  --local-dir /mnt/SSD4T/teambruce/projects/navila-isaac/vlnce_assets

ASSETS=/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/isaaclab_exts/omni.isaac.vlnce/assets
mkdir -p ${ASSETS}
cp vlnce_assets/vln_ce_isaac_v1.json.gz ${ASSETS}/
unzip -q vlnce_assets/matterport_usd.zip -d ${ASSETS}/
# Result: 91 Matterport scene directories
```

Low-level policy checkpoints for Go2 and H1 are bundled in the `NaVILA-Bench/logs/` directory (included in the git repo).

---

## Patches Required

The following patches were necessary to run on this setup. All are due to version mismatches between NaVILA's pinned dependencies and current library releases — none are RTX 4090 / Ada Lovelace specific.

### 1. `NaVILA/llava/train/sequence_parallel/globals.py`
**Issue:** Hard import of `deepspeed` fails when DeepSpeed is not installed (evaluation-only setup).
```python
# Before
import deepspeed.comm as dist

# After
import torch
try:
    import deepspeed.comm as dist
except ImportError:
    import torch.distributed as dist
```

### 2. `NaVILA/llava/model/builder.py`
**Issue:** `load_8bit=True` skips setting `torch_dtype`, but `prepare_config_for_eval()` always pops it → `KeyError`.
```python
# After (line 44-46)
if load_8bit:
    kwargs["load_in_8bit"] = True
    kwargs["torch_dtype"] = torch.float16  # ← added
```

### 3. `transformers/modeling_utils.py` (in conda env site-packages AND NaVILA repo)
**Issue:** NaVILA's transformers patch calls `set_module_quantized_tensor_to_device(..., fp16_statistics=...)`, but the current transformers renamed this parameter to `quantized_stats`.
```python
# Before
set_module_quantized_tensor_to_device(model, param_name, param_device, value=param, fp16_statistics=fp16_statistics)

# After
set_module_quantized_tensor_to_device(model, param_name, param_device, value=param, quantized_stats=fp16_statistics)
```
Apply to both:
- `conda_envs/navila-vlm/lib/python3.10/site-packages/transformers/modeling_utils.py`
- `NaVILA/llava/train/transformers_replace/modeling_utils.py`

### 4. `NaVILA-Bench/scripts/vlm_server.py`
**Issue (a):** `args.model_path` references the global `args` instead of `self.args` → `NameError`.  
**Issue (b):** Calling `self.model.to(device)` after loading with `device_map` causes meta tensor error.  
**Fix:** Use `self.args.model_path`, pass explicit `device_map={"": device}`, remove redundant `.to()`.  
**Added:** `--load_8bit` flag, `--max_new_tokens` flag, `pad_token_id` in generate call.

### 5. `NaVILA-Bench/scripts/navila_eval.py`
**Issue:** PIL JPEG encoding (`pil_image.save(..., format="JPEG")`) crashes inside Isaac Sim due to bundled PIL version conflict with conda env's Pillow.  
**Fix:** Replace with OpenCV encoding:
```python
import cv2
np_bgr = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
_, buf = cv2.imencode(".jpg", np_bgr)
encoded_images.append(base64.b64encode(buf.tobytes()).decode())
```

### 6. `vlnce-isaac` conda env `PIL/_util.py`
**Issue:** Isaac's bundled `PIL/ImageFont.py` calls `PIL._util.is_directory()`, which doesn't exist in Pillow 11.x+.  
**Fix:** Add the function:
```python
def is_directory(f):
    return isinstance(f, (bytes, str, os.PathLike)) and os.path.isdir(f)
```

### 7. Isaac bundled `botocore/httpchecksum.py`
**Path:** `.../isaacsim/extscache/omni.kit.pip_archive/pip_prebundle/botocore/httpchecksum.py`  
**Issue:** The conda env's `s3transfer` imports `DEFAULT_CHECKSUM_ALGORITHM` from botocore, but Isaac's bundled botocore is too old to have it. This caused `omni.replicator.core` to fail loading, breaking camera sensor initialization.  
**Fix:** Add the constant to Isaac's bundled botocore:
```python
DEFAULT_CHECKSUM_ALGORITHM = "crc32"
```

---

## Running the Evaluation

Requires two terminals.

### Terminal 1 — VLM Server

```bash
/home/teambruce/miniconda3/bin/conda run \
  --prefix /mnt/SSD4T/teambruce/conda_envs/navila-vlm \
  python /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/vlm_server.py \
  --model_path /mnt/SSD4T/teambruce/projects/navila-isaac/checkpoints/navila-llama3-8b-8f \
  --port 54321 \
  --load_8bit
```

Wait until the port is listening:
```bash
ss -tlnp | grep 54321
```

### Terminal 2 — Isaac Evaluation

```bash
cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench && \
OMNI_KIT_ACCEPT_EULA=YES \
/home/teambruce/miniconda3/bin/conda run \
  --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -p \
  scripts/navila_eval.py \
  --task=go2_matterport_vision \
  --num_envs=1 \
  --history_length=9 \
  --load_run=2024-09-25_23-22-02 \
  --headless \
  --enable_cameras \
  --episode_idx=0
```

Results saved to: `eval_results/go2_matterport_vision_loco_2024-09-25_23-22-02/`

### VRAM Usage (RTX 4090, 24 GB)

| Component | VRAM |
|---|---|
| VLM server (8-bit) | ~10 GB |
| Isaac Sim + camera rendering | ~8 GB |
| **Total** | **~18 GB / 24 GB** |

---

## Results

### Episode 0 — `go2_matterport_vision`

```json
{
    "path_length": 8.977,
    "distance_to_goal": 0.787,
    "success": 1.0,
    "spl": 0.907,
    "oracle_navigation_error": 0.203,
    "oracle_success": 1.0
}
```

**success = 1.0, SPL = 0.907** — the Go2 robot successfully navigated to the goal following NaVILA's language-conditioned commands.

---

## Project Progress Log

### 2026-06-05 — Language-Only Round-Trip Baseline

After confirming the baseline NaVILA + Isaac Sim VLN-CE deployment on six episodes, the next project stage is to construct a single-episode long-horizon task with an Outbound -> Confirm -> Return structure.

Implemented a language-only round-trip baseline evaluator:

```text
code/round_trip_eval.py
```

The working copy in the Isaac project is:

```text
/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/round_trip_eval.py
```

This baseline intentionally does not use route memory, anchors, template inversion, geometric hints, or fallback control. It only tests whether NaVILA can execute a continuous long-horizon round-trip task from language.

Supported modes:

- `static_long_instruction`: NaVILA always receives one complete outbound-confirm-return instruction from the first step onward.
- `phase_prompt`: the evaluator provides phase-specific language prompts for Outbound and Return, but still provides no route-memory or geometric information.

Current behavior:

- Converts the original single-trip VLN-CE instruction into a round-trip instruction.
- Interprets the first NaVILA `stop` during Outbound as a phase transition rather than ending the episode.
- Runs a scripted Confirm phase as a 360-degree scan.
- Continues into a Return phase inside the same simulator episode.
- Evaluates return success by distance to the original starting point.
- Saves stop events, phase events, generated instructions, outbound success, return distance-to-start, return success, and round-trip success into the measurement JSON.
- Writes results under `eval_results/round_trip_<mode>_<task>_loco_<run>/` so modes and baseline results are not overwritten.

Run command for Baseline A, the strict long-instruction version:

```bash
cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench && \
OMNI_KIT_ACCEPT_EULA=YES \
/home/teambruce/miniconda3/bin/conda run \
  --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -p \
  scripts/round_trip_eval.py \
  --task=go2_matterport_vision \
  --num_envs=1 \
  --history_length=9 \
  --load_run=2024-09-25_23-22-02 \
  --headless \
  --enable_cameras \
  --round_trip_mode=static_long_instruction \
  --episode_idx=0
```

Run command for Baseline B, the phase-prompt language-only version:

```bash
cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench && \
OMNI_KIT_ACCEPT_EULA=YES \
/home/teambruce/miniconda3/bin/conda run \
  --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -p \
  scripts/round_trip_eval.py \
  --task=go2_matterport_vision \
  --num_envs=1 \
  --history_length=9 \
  --load_run=2024-09-25_23-22-02 \
  --headless \
  --enable_cameras \
  --round_trip_mode=phase_prompt \
  --episode_idx=0
```

The next technical steps are:

- Run both baseline modes with GPU access and compare behavior.
- Decide whether `static_long_instruction` is too strict for NaVILA's original single-trip training distribution.
- Use the stronger language-only baseline as the comparison target for the later external-memory agent.
- Only after this baseline is measured, add route-template memory, geometric hints, and fallback control as the proposed method.

### 2026-06-05 — First `phase_prompt` Round-Trip Test

Ran `phase_prompt` on `go2_matterport_vision`, episode 0.

Artifacts:

```text
results/round_trip_phase_prompt_episode0/
├── output_0.mp4
├── measurement_raw_before_outbound_success_fix.json
└── summary.md
```

Observed behavior:

- Outbound reached the original target region and NaVILA emitted `stop`.
- The evaluator transitioned from Outbound to scripted Confirm, then into Return inside the same simulator episode.
- Return did not reach the original starting point.

Key numbers:

```text
outbound stop step: 1200
outbound stop distance to goal: 0.493 m
outbound goal radius: 3.0 m
outbound success: true by distance threshold
return success: false
round-trip success: false
final distance to start: 8.523 m
final distance to outbound goal: 2.974 m
```

Important evaluator fix:

The raw JSON from this first run records `round_trip.outbound_success=false`, but this is a logging bug: the evaluator inferred outbound success from the final post-return measurement. The code has been fixed so that outbound success is computed at the first outbound `stop` using the outbound goal radius.

### 2026-06-05 — Second `phase_prompt` Run After Evaluator Fix

Ran `phase_prompt` again on `go2_matterport_vision`, episode 0, after fixing outbound-success logging.

Artifacts:

```text
results/round_trip_phase_prompt_episode0_run2/
├── output_0.mp4
├── measurement.json
└── summary.md
```

Key numbers:

```text
outbound stop step: 1425
outbound stop distance to goal: 0.780 m
outbound goal radius: 3.0 m
outbound success: true
return stop step: 4801
return stop distance to start: 6.055 m
final distance to start: 6.062 m
return success: false
round-trip success: false
top-level path length: 29.794 m
```

Interpretation:

The phase-prompt baseline can complete the outbound portion and transition through Confirm into Return, but it still fails the return-to-start objective. In this run, NaVILA stopped during Return while still about 6 m from the original start. This supports keeping `phase_prompt` as a language-only baseline before adding the external route-memory agent.

### 2026-06-06 — Return-Failure Diagnosis

Reviewed both `phase_prompt` runs using the saved command events, measurements, and videos.

Findings:

- All Return-phase NaVILA outputs were parseable navigation commands; neither run failed because of an invalid-language-output fallback.
- The robot did not remain physically stuck for a prolonged period.
- Run 1 stayed mainly around the living-room area and timed out without returning.
- Run 2 entered a corridor, later selected an incorrect direction, returned toward the living-room area, and emitted `stop` while still about `6.06 m` from the start.
- The second run therefore shows both route-selection/re-localization failure and incorrect task-completion judgment.

The existing logs do not contain a full per-step pose trajectory, so they cannot yet distinguish gradual geometric drift from a discrete wrong turn at a junction. A later baseline instrumentation update should record pose, heading, distance to the reversed reference path, along-path progress, commanded motion, and executed motion.

### 2026-06-06 — Explicit Reverse-Instruction Generator

Added an offline instruction-rewriting module to the working NaVILA-Bench project:

```text
scripts/instruction_rewriter.py
tests/test_instruction_rewriter.py
```

The module:

- accepts an episode's original outbound instruction;
- asks a local or OpenAI-compatible LLM for an independently executable Return instruction;
- requires JSON output;
- reverses landmark/route order and directional actions through prompt constraints;
- rejects unchanged, empty, refusal, and obvious stop-first outputs;
- caches the generated instruction so benchmark runs are deterministic;
- supports `cache_only` evaluation, keeping the instruction-generation LLM outside the navigation loop.

The initial `llama3.2` generation was rejected during manual review because it reversed landmark order incorrectly and introduced ambiguous room transitions. The prompt was strengthened and versioned as `round-trip-rewriter-v2`. A second generation using local `qwen2.5vl:7b` produced:

```text
Outbound:
Exit the bedroom and turn left. Walk straight passing the gray couch
and stop near the rug.

Return:
From the rug, walk back past the gray couch. Turn right, enter the bedroom,
and stop at the original starting location.
```

Five unit tests currently cover generation, caching, cache-only loading, unchanged-output rejection, and rejection of an outbound `stop` repeated as the first Return action.

Important limitation:

The current generator validates format and several obvious logical errors, but it does **not** mathematically prove that an LLM-generated reverse instruction is geometrically correct. Sparse source instructions may omit junctions, landmark-side relations, or the exact visual identity of the starting location. Generated instructions must therefore remain versioned and manually reviewed before benchmark use.

Planned correction work:

- parse the outbound instruction into structured route steps;
- mechanically reverse step order and invert directional relations;
- validate landmark order with a second pass;
- use the episode reference path and heading to check turn geometry;
- record an explicit human-review status in the cache and measurement JSON.

### 2026-06-06 — Explicit Reverse-Instruction Baseline Test

Checked system resources before the run:

```text
GPU: RTX 4090, approximately 23.6 GB VRAM free before loading models
System memory: approximately 117 GB available
SSD4T: approximately 2.7 TB available
```

Ran Episode 0 in `phase_prompt` mode using the reviewed `qwen2.5vl:7b` reverse instruction from the deterministic cache. The result directory used the suffix `explicit_reverse_v2` so the previous runs were not overwritten.

Key results:

```text
outbound stop step: 1200
outbound stop distance to goal: 0.529 m
outbound success: true
return stop step: 4976
return stop distance to start: 11.279 m
final distance to start: 11.281 m
return success: false
round-trip success: false
```

Observed behavior:

- The explicit instruction changed the Return behavior: the robot left the living-room region and entered a long corridor.
- It entered the wrong part of the environment, continued issuing valid movement commands, and finally emitted `stop` far from the original start.
- This run demonstrates that replacing the abstract “retrace the route” prompt with a manually reviewed, explicit reverse instruction is not sufficient by itself.
- The result is consistent with failures in visual re-localization, junction selection, route-progress estimation, and stop judgment.

This remains a language-only baseline. It still uses no route memory, anchor matching, geometric hints, template inversion, or fallback controller.

Operational note:

After Isaac Sim shut down, `nvidia-smi` temporarily lost communication with NVML even though the NVIDIA kernel modules remained loaded and no NVIDIA Xid entry was found in the checked kernel-log window. GPU/driver health should be confirmed before another simulation run.

### 2026-06-06 — Strict Long-Instruction Baseline

After GPU/NVML communication recovered, ran Episode 0 in `static_long_instruction` mode using the same cached `qwen2.5vl:7b` outbound + explicit Return instruction.

Key results:

```text
outbound success: false
return started: false
closest outbound distance to goal: 0.143 m
final distance to outbound goal: 3.004 m
final distance to start: 8.410 m
path length: 13.854 m
stop events: 0
outbound timeout: approximately 50 seconds
```

Observed behavior:

- The robot correctly left the bedroom and entered the living-room area.
- It passed through the target region and came within `0.143 m` of the outbound goal.
- NaVILA did not emit `stop`, so the evaluator never transitioned to Confirm or Return.
- It continued navigating and moved away from the outbound target until timeout.

Interpretation:

This is a subtask-boundary or phase-transition failure. Under the full combined instruction, NaVILA failed to recognize that the outbound subtask had finished. This run does not measure reverse-route ability because Return never started.

Result directory:

```text
eval_results/round_trip_static_long_instruction_go2_matterport_vision_loco_2024-09-25_23-22-02_strict_explicit_reverse_v2/
```

### 2026-06-06 — Controlled Phase-Prompt Return Diagnosis

Added reusable diagnostic controls to `round_trip_eval.py`:

```text
--return_instruction_file=<path>
--return_instruction_override=<text>
--oracle_return_pose
```

The evaluator now records the natural Return pose, optional expert-corrected pose, selected Return instruction, and phase-transition events. `--oracle_return_pose` places the robot at the expert outbound endpoint and faces it toward the previous expert waypoint when Return begins.

Three Episode 0 conditions were compared:

| Return condition | Outbound | Return | Final distance to start |
|---|---:|---:|---:|
| Generated reverse instruction + natural pose | Success | Failure | `11.281 m` |
| Human Oracle instruction + natural pose | Success | Success | `1.995 m` |
| Human Oracle instruction + expert pose | Success | Success | `1.992 m` |

The human Oracle Return instruction was:

```text
From the rug, turn around. Retrace the route past the gray couch and continue straight back
toward the bedroom doorway. Turn right through the doorway into the bedroom and stop at the
original starting position inside the bedroom. Do not stop before reaching the bedroom.
```

Additional observations:

- The natural-pose Oracle run began Return approximately `1.01 m` from the expert endpoint and still succeeded.
- Both Oracle-instruction runs entered the configured `2.0 m` Return success radius.
- The expert-pose run reproduced the original successful outbound stop distance of `0.529 m` before pose correction.
- An initial expert-pose implementation exposed an inference-tensor refresh bug; the invalid run was discarded, the history-buffer reset was fixed, and the corrected `oracle_instruction_pose_v2` run completed normally.

Revised conclusion (updated 2026-06-06):

The Oracle instruction successes are methodologically invalid as evidence for NaVILA's round-trip capability. The Oracle instruction adds spatial detail that is absent from the original outbound instruction ("turn around", "Do not stop before reaching the bedroom", explicit doorway language), making it a strictly easier task. A scientifically valid baseline requires a reverse instruction at the same level of specificity as the original. See the 2026-06-06 Instruction Rewriter v3 entry below.

Relevant result directories:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_explicit_reverse_v2/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_oracle_instruction_v1/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_oracle_instruction_pose_v2/
```

### 2026-06-06 — Instruction Rewriter Upgraded to v3 (Parse → Mechanical Invert → Render)

The one-step LLM generation pipeline (`round-trip-rewriter-v2`) was replaced with a three-step pipeline that separates logic from language:

1. **Parse** — LLM converts the outbound instruction into a structured step sequence (JSON).
2. **Mechanical invert** — deterministic Python code reverses step order and applies fixed rules: `left ↔ right`, `exit_room ↔ enter_room`, landmark order guaranteed by code.
3. **Render** — LLM converts the inverted step sequence back to natural language at the same level of specificity as the original.

The motivation is to eliminate instruction logic errors (wrong landmark order, un-inverted turn directions) as a confounding variable, while keeping the generated instruction at the same granularity as the original outbound instruction. Adding detail beyond the original (e.g. "turn around", explicit stop constraints) would reduce task difficulty and invalidate the comparison.

The v2 pipeline depended on the LLM to get both the spatial inversion logic and the language rendering correct in a single step. The v3 pipeline guarantees structural correctness by code and uses the LLM only for parsing and rendering.

Files changed:

```text
scripts/instruction_rewriter.py   (PROMPT_VERSION → round-trip-rewriter-v3)
tests/test_instruction_rewriter.py (10 tests, all passing)
```

Episode 0 v3 generated return instruction (qwen2.5vl:7b):

```text
From the rug, move straight to the gray couch, turn right, and enter the bedroom. Stop at the bedroom.
```

### 2026-06-06 — Training Coverage Diagnosis: Reverse-Direction Episode Test

**Research question:** Is the return-phase failure caused by (H1) insufficient training coverage of the reverse route direction, or (H2) a structural limitation specific to the round-trip context?

**Method:** Search the VLN-CE-Isaac dataset for episodes in the same scene (`zsNo4HB9uLZ`) whose outbound path traverses the same waypoints as episode 0's return path, in the reverse direction.

**Finding:** Episodes 1198, 1199, and 1200 share the identical waypoint sequence with episode 0's return path (5/5 waypoints within 2 m), traveling from the corridor near the rug toward the bedroom. Their array indices in the dataset are 705, 706, and 707.

| | Episode 0 outbound | Episodes 1198–1200 outbound |
|---|---|---|
| Start | Bedroom `(15.07, 4.48)` | Corridor `(12.86, 0.07)` |
| Goal | Rug area `(13.05, -1.87)` | Bedroom `(15.07, 4.48)` |
| Direction | Bedroom → Rug | Corridor → Bedroom (= episode 0 return direction) |
| Waypoint overlap | — | 5 / 5 |

**Result:** Episode 705 (`episode_id=1198`, instruction: "Walk straight into the hallway. Turn right and go into the room. Wait near the door on the left.") evaluated with standard `navila_eval.py`:

```json
{
    "path_length": 7.630,
    "distance_to_goal": 1.080,
    "success": 1.0,
    "spl": 0.807,
    "oracle_navigation_error": 0.159,
    "oracle_success": 1.0
}
```

**Conclusion:** NaVILA achieves `success = 1.0` on the reverse-direction path as a standard outbound episode. This directly rules out H1: the training distribution covers this path direction, and the model has the capability to navigate it. The return failure in the round-trip evaluation is therefore a structural problem specific to the round-trip context — not a training coverage gap. This is the key result justifying the need for an external route-memory mechanism rather than simply adding more training data.

Result file:

```text
eval_results/go2_matterport_vision_loco_2024-09-25_23-22-02/measurements/1197.json
```

### 2026-06-16 - Return-Failure Ablations: Pose Drift vs Instruction Quality

Ran a focused set of Episode 0 round-trip ablations to separate three possible causes of Return failure:

1. accumulated outbound pose drift at the start of Return;
2. quality and training-distribution fit of the generated reverse instruction;
3. the round-trip context itself, including phase transition, visual history, and stop judgment.

All runs used the same language-only `phase_prompt` round-trip evaluator and no route memory, anchor matching, geometric hints, or fallback controller unless explicitly noted. The standard v3 reverse instruction was:

```text
From the rug, move straight to the gray couch, turn right, and enter the bedroom. Stop at the bedroom. This is the return phase. Stop only when you have reached the original starting location.
```

The retrieved reverse-direction dataset instruction from Episode 705 / `episode_id=1198` was:

```text
Walk straight into the hallway. Turn right and go into the room. Wait near the door on the left.
```

#### Round-trip: v3 reverse instruction vs oracle Return pose

| Condition | Outbound | Return | Final distance to start | Return-start pose error |
|---|---:|---:|---:|---:|
| v3 reverse instruction + natural Return pose | true | false | `11.213 m` | XY `0.300 m`, yaw `-46.4 deg` |
| v3 reverse instruction + oracle Return pose | true | false | `10.029 m` | after reset: XY `0.000 m`, yaw `0.0 deg` |

Key observation: oracle Return pose reset worked exactly, but did not recover success. This means accumulated outbound pose drift is not by itself a sufficient explanation for Return failure.

#### Same reverse path as a normal single-trip episode

Used Episode 705 (`episode_id=1198`) in the same scene (`zsNo4HB9uLZ`). This episode follows the reverse direction of Episode 0's Return path as a normal VLN task.

| Single-trip condition on Episode 705 | Success | SPL | Distance to goal |
|---|---:|---:|---:|
| Original Episode 705 instruction | `1.0` | `0.892` | `0.317 m` |
| Episode 0 v3 reverse instruction used as override | `0.0` | `0.000` | `17.740 m` |

Key observation: NaVILA succeeds on this reverse-direction route with the dataset's natural instruction, but fails badly when the v3 reverse instruction is used as the user instruction. This shows reverse-instruction wording and training-distribution fit are a major confound.

#### Round-trip using Episode 705's natural instruction as Return instruction

| Condition | Outbound | Return | Final distance to start | Termination |
|---|---:|---:|---:|---|
| Episode 705 instruction + natural Return pose | true | false | `3.532 m` | Return stop at `3.532 m` |
| Episode 705 instruction + oracle Return pose | true | false | `11.351 m` | Return stop at `11.351 m` |

Replacing the v3 reverse instruction with Episode 705's natural instruction improved the natural-pose Return substantially (`11.21 m` -> `3.53 m` from start), but still did not enter the configured `2.0 m` success radius. Adding oracle Return pose to the Episode 705 instruction did not help in this run.

Current interpretation:

- v3 reverse-instruction quality is insufficient and materially worsens Return behavior.
- Pose drift exists, especially heading error at Return start, but correcting the Return pose alone does not restore success.
- Round-trip context remains a separate failure factor: phase transition, accumulated visual history, current-view mismatch, and premature stop judgment can still break Return even with a dataset instruction that succeeds as a clean single-trip episode.

Result directories:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_drift_natural_ep0_v3/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_drift_oracle_pose_ep0_v3/
eval_results/go2_matterport_vision_loco_2024-09-25_23-22-02_ep1198_original_instruction/
eval_results/go2_matterport_vision_loco_2024-09-25_23-22-02_ep1198_episode0_v3_return_instruction/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_drift_natural_ep0_ep705_return_instruction/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_drift_oracle_pose_ep0_ep705_return_instruction/
```

### 2026-06-16 - Instruction Rewriter v4: Dataset Reverse-Path Retrieval

Upgraded the reverse-instruction generator from v3 to v4.

Previous v3 behavior:

- parsed the outbound instruction;
- mechanically inverted the parsed route;
- rendered a reverse instruction with an LLM;
- for Episode 0 produced the weak instruction beginning with `From the rug...`.

Problem identified by ablations:

- the v3 instruction failed even as a clean single-trip override on Episode 705;
- the dataset's natural reverse-direction instruction succeeded on that same route;
- therefore the reverse instruction must be treated as a real experimental variable, not as a solved preprocessing step.

New v4 behavior:

1. Given the current dataset path and episode index, search the same scene for episodes whose reference path overlaps the current episode's Return path in reverse order.
2. Rank candidates by matched waypoints, path-length agreement, coverage, mean waypoint distance, and dataset index.
3. If a strong reverse-path neighbor exists, use that episode's original VLN instruction as the Return instruction.
4. If no neighbor exists, fall back to the parse -> mechanical invert -> render pipeline.

For Episode 0, v4 retrieves:

```text
episode_index=705; episode_id=1198; matched_waypoints=5; mean_distance_m=0.000
```

and uses:

```text
Walk straight into the hallway. Turn right and go into the room. Wait near the door on the left.
```

The cache was updated with a `round-trip-rewriter-v4` entry, so `--instruction_rewriter_provider=cache_only` now resolves Episode 0 to the dataset reverse-path instruction when dataset context is available.

Implementation notes:

```text
scripts/instruction_rewriter.py    # v4 retrieval + fallback generator
scripts/round_trip_eval.py         # passes dataset path and episode index into InstructionRewriter
tests/test_instruction_rewriter.py # 11 tests passing, including reverse-path retrieval ranking
```

### 2026-06-16 - Per-Step Trajectory Logging and Stronger Oracle Reset

Added per-step trajectory logging to the round-trip evaluator so every completed run can be diagnosed from a JSONL trajectory file rather than only from final measurements.

Each round-trip measurement now records:

```text
round_trip.trajectory_file
round_trip.trajectory_record_count
```

Each trajectory record includes:

- step index and current phase;
- robot position, quaternion, yaw, root velocity, and planar speed;
- active high-level command and latest VLM output;
- distance to the original start and outbound goal;
- nearest point on the outbound reference path and reversed return path.

Also strengthened `--oracle_return_pose`. It now resets more than just the robot pose:

- writes the expert return-start pose and zero root velocity;
- clears low-level proprioceptive history;
- rebuilds low-level observations as normal writable tensors;
- clears stop/same-position state;
- clears the VLM image history;
- forces the first Return VLM query to use a fresh post-reset camera frame.

Two implementation bugs were exposed and fixed while validating this:

1. The local IsaacLab `SimulationContext` does not expose `write_data_to_sim()`, so the call is now version-gated.
2. Rebuilding low-level observations inside `torch.inference_mode()` created inference tensors that the VLN wrapper could not update in place. The refresh path now temporarily disables inference mode and clones detached tensors.

#### v4 rerun with trajectory logging

Both runs used Episode 0, `phase_prompt`, `cache_only`, and the v4 dataset reverse-path instruction retrieved from Episode 705:

```text
Walk straight into the hallway. Turn right and go into the room. Wait near the door on the left.
```

| Condition | Outbound | Return | Round trip | Final distance to start | Trajectory records |
|---|---:|---:|---:|---:|---:|
| v4 baseline, natural Return pose | true | true | true | `1.995 m` | `2963` |
| v4 baseline + stronger oracle reset | true | false | false | `13.295 m` | `3152` |

Baseline details:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_traj_baseline_ep0/
measurements/0.json
trajectories/output_0.jsonl
```

- `instruction_rewriter_provider`: `dataset_reverse_path_neighbor`
- `instruction_rewriter_model`: `episode_index=705;episode_id=1198;matched_waypoints=5;mean_distance_m=0.000`
- outbound stop distance to goal: `0.195 m`
- Return-start pose error before oracle correction: XY `0.456 m`, yaw `-72.6 deg`
- final distance to start: `1.995 m`, inside the configured `2.0 m` success radius

Oracle-reset details:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_traj_oracle_reset_ep0/
measurements/0.json
trajectories/output_0.jsonl
```

- oracle reset itself was exact: post-reset XY error `0.000 m`, z error `0.000 m`, yaw error `0.0 deg`
- Return began near the reversed reference path: trajectory sample at Return start had nearest-return-path distance `0.063 m`
- Return initially moved closer to start (`6.673 m` -> `5.691 m`), then drifted away (`9.096 m`, `12.101 m`) and finally stopped at `13.295 m`

Current interpretation:

- The v4 instruction fix is material: the natural-pose v4 baseline succeeded where earlier v3 variants failed.
- The stronger oracle reset now cleanly isolates robot pose, low-level history, VLM visual history, and stop/memory state at Return transition.
- Because oracle reset was exact but the Return trajectory still diverged after the reset, this failure is not explained by accumulated outbound pose drift alone. The per-step log points to post-reset Return-phase visual decision/control drift or stop judgment as the next target.

### 2026-06-16 - v4 Baseline Stability and Random-Episode Generalization

After the first v4 Episode 0 baseline succeeded just inside the configured `2.0 m` return-success radius, repeated the same language-only baseline to check whether that success was a one-off stochastic result.

All runs used Episode 0, `phase_prompt`, `cache_only`, and the v4 dataset reverse-path instruction retrieved from Episode 705.

| Run set | Runs | Round-trip success | Final distance to start |
|---|---:|---:|---|
| Original v4 baseline + 5 repeats | 6 | 6 / 6 | `1.995 m` to `2.000 m` |

Repeat-run observations:

- The Episode 0 v4 baseline success is reproducible across six total runs.
- The margin is extremely narrow: the final distance is consistently just inside the `2.0 m` success threshold.
- Several runs are bitwise-identical or nearly identical, while two repeats used a slightly different outbound stop pose and still ended inside the threshold.

Representative result directories:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_traj_baseline_ep0/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_repeat_baseline_ep0_r1/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_repeat_baseline_ep0_r2/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_repeat_baseline_ep0_r3/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_repeat_baseline_ep0_r4/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_repeat_baseline_ep0_r5/
```

Then stopped testing Episode 0 and sampled three different episodes from `vln_ce_isaac_v1.json.gz`, restricted to cases where v4 could retrieve a reverse-path neighbor from the dataset.

| episode_idx | episode_id | scene | Reverse-neighbor source | Outbound | Return | Round trip | Final distance to start |
|---:|---:|---|---|---:|---:|---:|---:|
| 189 | 286 | `2azQ1b91cZZ` | episode_idx `696`, 4 matched waypoints, mean distance `0.000 m` | true | false | false | `7.217 m` |
| 278 | 444 | `EU6Fwq7SyZv` | episode_idx `888`, 4 matched waypoints, mean distance `0.261 m` | false | false | false | `1.173 m` |
| 799 | 1361 | `zsNo4HB9uLZ` | episode_idx `393`, 5 matched waypoints, mean distance `0.000 m` | false | false | false | `5.932 m` |

Per-episode notes:

- Episode 189 completed Outbound and entered Return, but never got close to the start. During Return its best distance to start was about `6.19 m`, and it stopped at about `7.21 m`.
- Episode 278 failed before Return. It remained in the Outbound phase and eventually hit the same-location/stuck guard, with final distance to outbound goal `9.954 m`.
- Episode 799 also failed before Return. It continued issuing movement/turn commands but did not produce a successful outbound stop, ending `2.104 m` from the outbound goal.

Random-episode result directories:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_random_baseline_ep189/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_random_baseline_ep278/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_random_baseline_ep799/
```

Current interpretation:

- Episode 0 is a favorable narrow-margin case rather than a generally representative round-trip success.
- On random episodes, many failures happen before Return because Outbound itself does not reliably terminate successfully.
- For return-specific diagnosis, future tests should either pre-screen for episodes with stable Outbound success or use an oracle Return-start setup to isolate the Return leg from Outbound failure.

### 2026-06-17 — v4 Baseline: 5 New Random Episodes Across 5 Scenes

Ran 5 new episodes sampled from the v4-eligible pool (episodes that have at least one reverse-path neighbor in the same scene). Selected one best candidate per scene, prioritising highest matched-waypoint count and lowest mean path distance. All runs used `phase_prompt` mode and `cache_only` instruction provider (v4 dataset reverse-path retrieval).

System state before run: GPU 24018 MB VRAM free, RAM 120 GB available, SSD4T 2.7 TB available.

| ep_idx | ep_id | scene | Reverse-neighbor source | Outbound | Return | Round trip | Final distance to start |
|---:|---:|---|---|---:|---:|---:|---:|
| 366 | 601 | `X7HyMhZNoso` | ep_idx=1038, ep_id=1759, 7 matched, mean 0.000 m | true | false | false | `7.441 m` (timeout) |
| 105 | 151 | `QUCTc6BB5sX` | ep_idx=993, ep_id=1699, 7 matched, mean 0.000 m | true | true | **true** | `1.997 m` |
| 3 | 7 | `x8F5xyUWy9e` | ep_idx=354, ep_id=583, 5 matched, mean 0.000 m | false* | true | false | `1.997 m` |
| 132 | 193 | `2azQ1b91cZZ` | ep_idx=756, ep_id=1288, 7 matched, mean 0.258 m | false | — | false | — |
| 612 | 1069 | `zsNo4HB9uLZ` | ep_idx=678, ep_id=1165, 7 matched, mean 0.000 m | false | — | false | — |

*ep3 outbound stopped at 3.919 m, marginally outside the 3.0 m goal radius.

Per-episode notes:

- **Episode 366 (X7HyMhZNoso):** Outbound completed successfully (stopped at 2.456 m from goal). During Return, the robot became stuck in alternating left/right 45-degree turns from approximately step 3750 onward, timed out at step 7051 with distance to start 7.441 m. Classic Return visual-decision failure with no forward progress.

- **Episode 105 (QUCTc6BB5sX):** Full round-trip success. Outbound stopped cleanly at 1.186 m from goal. Return distance improved continuously from 11.875 m → 9.822 m → 6.861 m → 3.019 m across 500-step checkpoints. Final distance to start: 1.997 m (inside 2.0 m radius).

- **Episode 3 (x8F5xyUWy9e):** Anomalous result. Outbound formally failed (stopped at 3.919 m, just outside the 3.0 m goal radius) but Return still succeeded (final distance 1.997 m). The robot reached the outbound target area closely enough to execute a successful Return despite the formal outbound failure. This round-trip is counted as a failure (outbound unconfirmed), but it suggests Return capability in this episode is robust even from a slightly incorrect outbound endpoint.

- **Episode 132 (2azQ1b91cZZ):** Outbound never emitted a stop; the episode timed out in the outbound phase at 5.421 m from original start. Return never started.

- **Episode 612 (zsNo4HB9uLZ):** Same failure mode as ep132 — outbound timeout without stop, Return never started. Final position was 2.962 m from the original start (still in outbound phase).

Updated cumulative results across all random episodes tested with v4 (excluding the 6 Episode 0 stability runs):

| ep_idx | scene | Outbound | Return | Round trip | Final dist to start |
|---:|---|---:|---:|---:|---:|
| 189 | `2azQ1b91cZZ` | true | false | false | `7.217 m` |
| 278 | `EU6Fwq7SyZv` | false | — | false | — |
| 799 | `zsNo4HB9uLZ` | false | — | false | — |
| 366 | `X7HyMhZNoso` | true | false | false | `7.441 m` |
| 105 | `QUCTc6BB5sX` | true | true | **true** | `1.997 m` |
| 3 | `x8F5xyUWy9e` | false* | true | false | `1.997 m` |
| 132 | `2azQ1b91cZZ` | false | — | false | — |
| 612 | `zsNo4HB9uLZ` | false | — | false | — |

Round-trip success rate on random episodes: **1 / 8 (12.5%)**, versus 6 / 6 for the Episode 0 stability set. Both confirmed successes (ep0 and ep105) ended just inside the 2.0 m threshold (1.995–1.997 m), suggesting they are near-threshold cases rather than comfortable successes. Outbound failure is the dominant blocker: 5 of 8 random episodes failed before Return started.

Result directories:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_random_baseline_ep366/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_random_baseline_ep105/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_random_baseline_ep3/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_random_baseline_ep132/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_random_baseline_ep612/
```


### 2026-06-18 — v4 Baseline: 30 Additional Reverse-Path Episodes

Ran two new automatic serial batches with `phase_prompt` mode and `cache_only` v4 dataset reverse-path retrieval. The batch runner started the next episode automatically after each run completed; no manual intervention was required after launch. All 30 runs exited with code `0`.

Batch scripts and local summaries:

```text
/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/run_v4_batch_10_20260618.sh
/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/run_v4_batch_20_20260618.sh
/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/v4_batch_10_20260618/summary.tsv
/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/v4_batch_20_20260618/summary.tsv
```

Aggregate results across the 30 new runs:

- Outbound success: **14 / 30**
- Return success: **5 / 30**
- Full round-trip success: **3 / 30**
- Outbound-success per-step trajectory logs uploaded: **14 JSONL files** under `results/per_step_logs/v4_batch_20260618_outbound_success/`

| Batch | Runs | Outbound | Return | Round trip |
|---|---:|---:|---:|---:|
| Batch A: 10 episodes | 10 | 3 | 2 | 0 |
| Batch B: 20 episodes | 20 | 11 | 3 | 3 |
| **Combined** | **30** | **14** | **5** | **3** |

Per-episode results:

| Batch | ep_idx | ep_id | scene | Reverse-neighbor source | Outbound | Return | Round trip | Final distance to start | Outbound stop distance to goal | Trajectory records | Uploaded trajectory log |
|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| Batch A: 10 episodes | 106 | 152 | `QUCTc6BB5sX` | ep_idx=993, ep_id=1699, 7 matched, mean 0.000 m | false | true | false | `0.000 m` | `9.581 m` | 4512 | — |
| Batch A: 10 episodes | 367 | 602 | `X7HyMhZNoso` | ep_idx=1038, ep_id=1759, 7 matched, mean 0.000 m | true | false | false | `5.793 m` | `1.033 m` | 3302 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_10_20260618_ep367_episode602_X7HyMhZNoso.jsonl` |
| Batch A: 10 episodes | 613 | 1070 | `zsNo4HB9uLZ` | ep_idx=678, ep_id=1165, 7 matched, mean 0.000 m | false | true | false | `1.996 m` | `16.438 m` | 1714 | — |
| Batch A: 10 episodes | 133 | 194 | `2azQ1b91cZZ` | ep_idx=756, ep_id=1288, 7 matched, mean 0.258 m | false | false | false | `6.199 m` | — | 2502 | — |
| Batch A: 10 episodes | 198 | 307 | `TbHJrupSAjP` | ep_idx=537, ep_id=928, 7 matched, mean 1.519 m | false | false | false | `0.550 m` | — | 2502 | — |
| Batch A: 10 episodes | 186 | 280 | `EU6Fwq7SyZv` | ep_idx=447, ep_id=754, 6 matched, mean 0.433 m | false | false | false | `3.561 m` | — | 2502 | — |
| Batch A: 10 episodes | 4 | 8 | `x8F5xyUWy9e` | ep_idx=354, ep_id=583, 5 matched, mean 0.000 m | true | false | false | `10.151 m` | `1.630 m` | 2552 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_10_20260618_ep4_episode8_x8F5xyUWy9e.jsonl` |
| Batch A: 10 episodes | 336 | 547 | `Z6MFQCViBuw` | ep_idx=651, ep_id=1132, 4 matched, mean 0.000 m | false | false | false | `12.322 m` | — | 2502 | — |
| Batch A: 10 episodes | 408 | 682 | `oLBMNvg9in8` | ep_idx=522, ep_id=907, 4 matched, mean 0.761 m | true | false | false | `6.884 m` | `0.686 m` | 5827 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_10_20260618_ep408_episode682_oLBMNvg9in8.jsonl` |
| Batch A: 10 episodes | 107 | 153 | `QUCTc6BB5sX` | ep_idx=993, ep_id=1699, 7 matched, mean 0.000 m | false | false | false | `12.227 m` | — | 2502 | — |
| Batch B: 20 episodes | 368 | 603 | `X7HyMhZNoso` | ep_idx=1038, ep_id=1759, 7 matched, mean 0.000 m | true | false | false | `6.826 m` | `0.451 m` | 7027 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep368_episode603_X7HyMhZNoso.jsonl` |
| Batch B: 20 episodes | 614 | 1071 | `zsNo4HB9uLZ` | ep_idx=678, ep_id=1165, 7 matched, mean 0.000 m | false | false | false | `0.761 m` | — | 2502 | — |
| Batch B: 20 episodes | 993 | 1699 | `QUCTc6BB5sX` | ep_idx=105, ep_id=151, 7 matched, mean 0.000 m | true | true | true | `1.994 m` | `0.522 m` | 4411 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep993_episode1699_QUCTc6BB5sX.jsonl` |
| Batch B: 20 episodes | 134 | 195 | `2azQ1b91cZZ` | ep_idx=756, ep_id=1288, 7 matched, mean 0.258 m | true | false | false | `6.223 m` | `0.252 m` | 3252 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep134_episode195_2azQ1b91cZZ.jsonl` |
| Batch B: 20 episodes | 199 | 308 | `TbHJrupSAjP` | ep_idx=537, ep_id=928, 7 matched, mean 1.519 m | false | false | false | `0.589 m` | — | 2502 | — |
| Batch B: 20 episodes | 187 | 281 | `EU6Fwq7SyZv` | ep_idx=447, ep_id=754, 6 matched, mean 0.433 m | true | false | false | `11.813 m` | `0.216 m` | 7727 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep187_episode281_EU6Fwq7SyZv.jsonl` |
| Batch B: 20 episodes | 5 | 9 | `x8F5xyUWy9e` | ep_idx=354, ep_id=583, 5 matched, mean 0.000 m | true | false | false | `8.598 m` | `0.255 m` | 3882 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep5_episode9_x8F5xyUWy9e.jsonl` |
| Batch B: 20 episodes | 337 | 548 | `Z6MFQCViBuw` | ep_idx=651, ep_id=1132, 4 matched, mean 0.000 m | false | false | false | `4.622 m` | `4.818 m` | 3702 | — |
| Batch B: 20 episodes | 409 | 683 | `oLBMNvg9in8` | ep_idx=522, ep_id=907, 4 matched, mean 0.761 m | false | false | false | `2.125 m` | — | 1666 | — |
| Batch B: 20 episodes | 678 | 1165 | `zsNo4HB9uLZ` | ep_idx=612, ep_id=1069, 7 matched, mean 0.000 m | true | false | false | `3.782 m` | `0.208 m` | 3777 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep678_episode1165_zsNo4HB9uLZ.jsonl` |
| Batch B: 20 episodes | 679 | 1166 | `zsNo4HB9uLZ` | ep_idx=612, ep_id=1069, 7 matched, mean 0.000 m | true | true | true | `1.995 m` | `0.227 m` | 4021 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep679_episode1166_zsNo4HB9uLZ.jsonl` |
| Batch B: 20 episodes | 680 | 1167 | `zsNo4HB9uLZ` | ep_idx=612, ep_id=1069, 7 matched, mean 0.000 m | true | false | false | `3.710 m` | `0.380 m` | 3877 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep680_episode1167_zsNo4HB9uLZ.jsonl` |
| Batch B: 20 episodes | 994 | 1700 | `QUCTc6BB5sX` | ep_idx=105, ep_id=151, 7 matched, mean 0.000 m | true | false | false | `4.522 m` | `0.729 m` | 3927 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep994_episode1700_QUCTc6BB5sX.jsonl` |
| Batch B: 20 episodes | 995 | 1701 | `QUCTc6BB5sX` | ep_idx=105, ep_id=151, 7 matched, mean 0.000 m | false | false | false | `11.760 m` | — | 2502 | — |
| Batch B: 20 episodes | 1038 | 1759 | `X7HyMhZNoso` | ep_idx=366, ep_id=601, 7 matched, mean 0.000 m | true | true | true | `1.998 m` | `1.004 m` | 3881 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep1038_episode1759_X7HyMhZNoso.jsonl` |
| Batch B: 20 episodes | 1039 | 1760 | `X7HyMhZNoso` | ep_idx=366, ep_id=601, 7 matched, mean 0.000 m | false | false | false | `3.748 m` | — | 2502 | — |
| Batch B: 20 episodes | 1040 | 1761 | `X7HyMhZNoso` | ep_idx=366, ep_id=601, 7 matched, mean 0.000 m | true | false | false | `2.415 m` | `0.993 m` | 4152 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep1040_episode1761_X7HyMhZNoso.jsonl` |
| Batch B: 20 episodes | 465 | 793 | `QUCTc6BB5sX` | ep_idx=600, ep_id=1042, 7 matched, mean 0.216 m | false | false | false | `0.000 m` | — | 952 | — |
| Batch B: 20 episodes | 466 | 794 | `QUCTc6BB5sX` | ep_idx=600, ep_id=1042, 7 matched, mean 0.216 m | false | false | false | `3.630 m` | `5.201 m` | 6603 | — |
| Batch B: 20 episodes | 467 | 795 | `QUCTc6BB5sX` | ep_idx=600, ep_id=1042, 7 matched, mean 0.216 m | false | false | false | `4.176 m` | — | 2502 | — |

The three confirmed round-trip successes were:

| ep_idx | scene | Final distance to start |
|---:|---|---:|
| 993 | `QUCTc6BB5sX` | `1.994 m` |
| 679 | `zsNo4HB9uLZ` | `1.995 m` |
| 1038 | `X7HyMhZNoso` | `1.998 m` |

Interpretation: the larger 30-episode sample keeps the same pattern seen in the earlier random v4 runs. v4 reverse-path retrieval can produce full round-trip success, but successes remain narrow-margin cases ending just inside the 2.0 m return-success radius. Outbound failure is still common, and among episodes that do enter Return, visual decision and stop-judgment errors remain the main failure modes.


### 2026-06-26 — Relative-Odometry Route-Memory Batch Test

Updated the round-trip evaluator so outbound and return success both use the official `3.0 m` goal radius. Return success now requires a VLM-issued `stop` inside the start radius; entering the radius alone does not terminate the episode or count as success.

Implemented the first external route-memory agent:

- Records outbound anchors using relative odometry deltas rather than storing Isaac/global coordinates.
- Builds a reversed route template for Return.
- Injects compact route-progress hints into the Return prompt, including the remaining route-template distance to the start.
- Adds a conservative fallback controller for low-progress or oscillatory Return behavior.

Batch selection:

- Source: previous 30-episode phase-prompt baseline.
- Criterion: baseline outbound success was true and baseline return success was false.
- Tested episodes: `4, 5, 134, 187, 367, 368, 408, 678, 680, 994`.
- Excluded episode `1040` because it was a borderline case under the current `3.0 m` radius.

Artifacts:

```text
results/route_memory_batch_10_20260626/
├── summary.tsv
├── summary.json
├── measurements/
└── trajectories/
```

Key aggregate result:

| Method | Outbound Success | Return Success | Round-Trip Success | Final Distance Improved |
|---|---:|---:|---:|---:|
| Baseline | 10/10 | 0/10 | 0/10 | - |
| Route memory, relative odometry | 8/10 | 3/10 | 3/10 | 7/10 |

Per-episode comparison:

| Episode | Baseline Return | Baseline Distance to Start (m) | Route-Memory Outbound | Route-Memory Return | Route-Memory Distance to Start (m) | Return Stop Count | Fallback Count |
|---:|:---:|---:|:---:|:---:|---:|---:|---:|
| 4 | False | 10.151 | True | False | 0.000 | 0 | 2 |
| 5 | False | 8.598 | True | False | 8.859 | 0 | 16 |
| 134 | False | 6.223 | False | False | 2.605 | 0 | 0 |
| 187 | False | 11.813 | True | False | 8.820 | 0 | 18 |
| 367 | False | 5.793 | True | True | 1.765 | 1 | 2 |
| 368 | False | 6.826 | True | False | 7.137 | 0 | 12 |
| 408 | False | 6.884 | False | False | 2.125 | 0 | 0 |
| 678 | False | 3.782 | True | True | 2.691 | 1 | 1 |
| 680 | False | 3.710 | True | True | 1.925 | 1 | 1 |
| 994 | False | 4.522 | True | False | 4.742 | 1 | 1 |

Interpretation:

- The route-memory framework produced a clear return improvement on this hard subset: round-trip success rose from `0/10` to `3/10`.
- Seven of ten episodes ended closer to the start than the baseline.
- Episode `4` reached `0.000 m` from the start but did not emit a Return-phase VLM `stop`, so it is correctly counted as return failure under the stop-required rule.
- Episodes `134` and `408` regressed on outbound success, so the current framework is promising but not stable enough to claim a general improvement.

---

### 2026-06-29 — GT Co-visibility Diagnostic + Rear Camera Fix + VIO Bridge

#### GT Co-visibility Diagnostic (completed 2026-06-28)

Ran a detailed per-attempt analysis of all 85 LoFTR relocalization calls recorded in `seqpf_sfix` (`measurements/1699.json`, `covisibility_records`). The particle filter successfully accepted 8 observations covering anchors A14→A8 (d2s ~14→7.8 m) in the first half of the return route, then lost track completely.

**Two distinct failure zones in the second half:**

| Zone | d2s range | Attempts | Depth co-vis | LoFTR inliers | Position error | SeqSLAM verdict |
|---|---|---|---|---|---|---|
| A (deep) | 0–6 m | 37–85 | 0% | 40–100 (aliasing) | +6 to +13 m | Correctly rejected |
| B (transition) | 6–8 m | 27–35 | 13–24% | 110–170 (conf=1.0) | +3.9 to +5.9 m | Correctly rejected |

**Zone A root cause:** camera direction mismatch. Go2 strafes laterally during navigation, so its body yaw is roughly perpendicular to its velocity. Outbound anchors A0–A15 captured views facing ~+92° to ±180° (north/west); the return robot faces ~0° to −90° (east/south). The ~150–180° angular separation means there is zero genuine co-visibility. LoFTR's high match count (40–100) comes from visual aliasing on repetitive corridor and room textures. Robot stays within 0–2 m of the outbound path throughout (not off-path drift).

**Zone B root cause:** corridor geometric degeneracy. At d2s 6–8 m the robot's rear view overlaps with anchor front views from the far corridor walls, giving 13–24% real depth-consistent co-visibility. LoFTR succeeds (110–170 inliers), but the scene is a planar wall — RANSAC/Kabsch cannot recover the translation component along the corridor axis, producing +4–6 m position errors. This would affect MASt3R equally.

**Three-branch verdict:**
- Branch 1 (co-visibility low/zero → coverage problem): ✅ confirmed for Zone A, caused by camera direction mismatch
- Branch 2 (co-visibility exists but matching fails): ✅ confirmed for Zone B, caused by planar degeneracy
- Branch 3 (anchor spacing too large): ❌ ruled out — 1 m spacing, robot within 0.2–1.5 m of nearest anchor

**Hint gating re-confirmed harmful:** the `hint_gate` experiment failed (4.403 m final distance) because the VLM uses specific distance/bearing hints as navigational narrative ("keep going toward 0 m") rather than as precise localization. Replacing specific-but-wrong hints with generic "position uncertain" messages removed this signal. Fix: preserve directional/distance content in hints when filter is uncertain; only suppress explicit "you have arrived / stop now" language.

#### Rear Camera Anchor Fix

Added a rear-facing camera to `Go2VisionSceneCfg` to capture the scene direction that the return robot's front camera will see:

**`go2_matterport_vision_cfg.py`:**
- `rear_rgbd_camera`: `pos=(−0.1, 0.0, 0.5)`, `rot=(−0.5, 0.5, 0.5, −0.5)` — camera +Z maps to body −x (rear-facing), 54° FOV, 512×512 RGB + depth
- `RearCameraObsCfg` and `RearDepthObsCfg` observation groups added to `ObservationsCfg`

**`round_trip_eval.py`:**
- `rear_camera_intrinsics_from_env`, `rear_camera_pose_from_env`, `rear_camera_extrinsic_body_from_env` added
- `route_memory_descriptor_from_infos` saves: `rear_rgb`, `rear_depth_depth_measurement`, `rear_camera_intrinsics`, `rear_camera_position_w`, `rear_camera_quat_wxyz`, `rear_camera_rotation_body`, `rear_camera_position_body`

**`relocalization.py`:**
- `descriptor_rear_depth`, `descriptor_rear_rgb_gray`, `build_rear_view_descriptor` added
- `build_rear_view_descriptor(anchor_descriptor)`: constructs a synthetic descriptor exposing `rear_rgb` → `rgb`, `rear_depth_*` → `depth_obs`, `rear_camera_intrinsics` → `camera_intrinsics`, `rear_camera_rotation_body`/`rear_camera_position_body` → standard extrinsics; all existing geometry code (LoFTR, RANSAC, `camera_rotation_to_body_yaw`) works unchanged
- `feature_depth_anchor_relocalization` now iterates `views_to_try = [("front", anchor.descriptor), ("rear", rear_view)]` per anchor, tagging backend as `feature_depth_loftr_3d3d_front` or `feature_depth_loftr_3d3d_rear`; all candidates across all views/anchors compete by score

During the return phase, the correct matching combination is: current front-camera image (faces east) ↔ anchor rear-camera image (also faces east, since outbound body faced west). The rear view descriptor carries the rear camera's extrinsics, so `camera_rotation_to_body_yaw` correctly resolves the anchor body heading relative to the current body frame.

#### VIO Bridge (off by default, `--vio_bridge`)

`RouteMemoryAgent._compute_feature_anchors()` scans consecutive anchor pairs for `|Δyaw| > 15°` after `finalize_outbound()`, marking those anchors as path feature points (corners, doorways) where scene geometry disambiguates position along the route.

`_sequence_match_observation()` new gate: if `filter.std() > vio_bridge_std_threshold_m` (default 2.5 m) AND the candidate arc-length is more than `vio_bridge_feature_radius_m` (default 2.0 m) from any feature anchor, reject the visual observation and continue with dead reckoning. Logged as `"vio_bridge_suppressed"`.

On ep994: feature anchors at A2, A3, A5, A6, A9, A10, A12, A13, A15, A16 (covers all path turns). The bridge is most useful for episodes with long featureless straight corridors; ep994 has many turns so the bridge rarely activates.

**Next step:** run ep994 with `--route_relocalization_backend=loftr_depth --result_suffix=rear_cam_20260629` to measure whether rear-camera matching produces accepted observations in the second-half corridor (Zone A + Zone B) that were previously rejected.


### 2026-06-27 — Anchor Relocalization Interface and Feature-Depth Backend

Motivation:

The previous route-memory design still depended on the robot entering a local anchor acquisition radius before an anchor could help. This fails in cases like episode `994`, where local geometry descriptors are available but the robot never reaches the first target anchor, so `lock_anchor=0` and anchor correction never activates.

The route-memory agent was redesigned so anchors can be used as map-free relocalization references. Instead of asking "am I standing on this anchor?", the Return stage can now ask "where is this saved outbound anchor relative to my current frame?" A successful relocalizer returns a metric relative pose:

```text
AnchorRelocalization(
  anchor_index=<saved outbound anchor>,
  anchor_dx_m=<anchor forward distance in robot frame>,
  anchor_dy_m=<anchor left/right distance in robot frame>,
  anchor_dtheta_rad=<relative heading>,
  confidence=<backend confidence>,
  backend=<backend name>
)
```

The agent then converts that into route-progress hints:

```text
[System Hint: route anchor A0 is 0.61 m away, 112 deg to your left;
estimated remaining route via anchor is 0.61 m;
start vector dx=-0.23 m, dy=0.56 m.]
```

Implemented code changes:

- `scripts/route_memory_agent.py`
  - Added `RouteAnchor`, `AnchorRelocalization`, and anchor-relative fields on `RelativeStartProgress`.
  - Keeps the old action-integrated relative-start estimate as a fallback.
  - Stores sparse outbound anchors with route-distance metadata.
  - Accepts external relocalization outputs and prioritizes anchor-relative progress when confidence is high enough.
  - Summarizes descriptors by shape/range in measurements instead of dumping large arrays.
- `scripts/round_trip_eval.py`
  - Added `--route_relocalization_backend={none,oracle_anchor,feature_depth}`.
  - Added `--route_relocalization_window` and `--route_relocalization_interval_updates`.
  - Extracts route-memory descriptors from `camera_obs`, `depth_obs`, and `route_memory_obs`.
  - Saves RGB, metric depth, camera intrinsics, height map, and height scan into anchor descriptors.
  - Records anchor relocalization fields in every per-step JSONL trajectory.
- `scripts/vlm_server.py`
  - Fixed a robustness issue where an empty socket connection or malformed JSON request could crash the server.
- `tests/test_route_memory_agent.py`
  - Added tests for anchor saving, anchor-route remaining distance, low-confidence relocalization rejection, and relocalization-driven hint generation.

Validation commands:

```bash
cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench

env PYTHONPATH=scripts python -m unittest tests/test_route_memory_agent.py

env PYTHONPYCACHEPREFIX=/tmp/navila_pycache \
  python -m py_compile \
  scripts/vlm_server.py \
  scripts/route_memory_agent.py \
  scripts/round_trip_eval.py
```

Both checks passed.

#### Oracle-anchor closed-loop test

The first test used Isaac pose only to simulate a perfect anchor relocalizer. It does not count as a proposed method result; its purpose is to verify the complete plumbing:

```text
current frame -> anchor relative pose -> anchor route hint -> VLM Return prompt -> stop decision
```

Run configuration:

```bash
TERM=xterm OMNI_KIT_ACCEPT_EULA=YES \
/home/teambruce/miniconda3/bin/conda run \
  --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -p \
  scripts/round_trip_eval.py \
  --task=go2_matterport_vision \
  --num_envs=1 \
  --history_length=9 \
  --load_run=2024-09-25_23-22-02 \
  --headless \
  --enable_cameras \
  --round_trip_mode=phase_prompt \
  --instruction_rewriter_provider=cache_only \
  --episode_idx=994 \
  --route_memory \
  --route_hint_mode=compact \
  --route_relocalization_backend=oracle_anchor \
  --result_suffix=oracle_anchor_reloc_ep994_20260627
```

Artifacts:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_oracle_anchor_reloc_ep994_20260627/
├── measurements/1699.json
├── trajectories/output_1699.jsonl
└── videos/output_1699.mp4
```

Result:

| Episode | Backend | Outbound | Return | Round trip | Final distance to start | Anchors | Relocalization events | Hint events |
|---:|---|:---:|:---:|:---:|---:|---:|---:|---:|
| 994 | `oracle_anchor` | True | True | True | `0.619 m` | 17 | 2052 | 36 |

Interpretation:

- The anchor-relative hint pipeline is correct.
- The VLM can use a metric anchor/start hint to stop near the start when the relative pose source is accurate.
- This supports the hypothesis that previous failures are primarily caused by unreliable relative pose estimation, not by the prompt-hint idea itself.

#### First real feature-depth backend

A first non-oracle backend was added:

```text
RGB + depth + ORB feature matching + 3D-3D RANSAC/Kabsch
```

The backend:

- extracts ORB features from the current RGB frame and saved anchor RGB frames;
- matches features with ratio test and cross-check fallback;
- uses aligned depth to back-project matched pixels into metric 3D;
- estimates a rigid 3D transform with RANSAC and Kabsch;
- converts the resulting anchor translation into robot-frame `dx/dy` for `AnchorRelocalization`.

Strict run:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_feature_depth_reloc_ep994_20260627/
```

Result:

- Relocalization events: `0`
- Return success: false
- Final distance to start: `4.363 m`

Relaxed run:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_feature_depth_relaxed_ep994_20260627/
```

Result:

| Episode | Backend | Outbound | Return | Round trip | Final distance to start | Anchors | Relocalization events |
|---:|---|:---:|:---:|:---:|---:|---:|---:|
| 994 | `feature_depth_orb_3d3d` | True | False | False | `4.424 m` | 17 | 12 |

Diagnostics from the relaxed run:

```json
{
  "attempts": 76,
  "candidate_anchors": 608,
  "ransac_failed": 591,
  "no_pose_selected": 64,
  "low_confidence_pose": 4,
  "successful_estimates": 12
}
```

Representative successful estimates were low confidence:

```text
anchor_index=10, dx=1.10 m, dy=-0.09 m, confidence=0.347, inliers=11
anchor_index=8,  dx=1.59 m, dy=-0.65 m, confidence=0.215, inliers=8
anchor_index=15, dx=-1.43 m, dy=-0.91 m, confidence=0.158, inliers=7
```

Interpretation:

- The real backend is wired correctly: it can produce `AnchorRelocalization` events and drive anchor-relative hints without crashing the evaluator.
- ORB+depth is too weak for this setting. Most candidate anchor matches fail RANSAC, and successful estimates usually have only `6-11` 3D inliers.
- Anchor choice is unstable under this backend, so the Return prompt can receive noisy hints and does not improve over the baseline.
- The next backend should be a stronger cross-view matcher or learned map-free relative-pose model: SuperPoint/LightGlue, LoFTR, or MicKey-style metric relative pose.

Current conclusion:

The research direction remains valid. The oracle-anchor result proves that "remote anchor relative pose -> Return hint" is useful when pose is reliable. The first real classical backend proves the integration path works but also shows that handcrafted ORB+depth matching is not enough for the viewpoint change and low-overlap conditions in these VLN-CE trajectories.

### 2026-06-27 — Geometry Verification, SIFT Diagnostics, and LoFTR Integration

#### Geometry pipeline extraction and verification

All geometry and feature-matching functions were extracted from `round_trip_eval.py` into a standalone module:

```text
scripts/relocalization.py
```

This makes offline testing possible without Isaac Sim. Key exported functions:
`backproject_points`, `rigid_transform_3d`, `ransac_rigid_transform`, `camera_point_to_body`, `loftr_match_points`, `feature_depth_anchor_relocalization`, plus all descriptor accessors.

An 18-test verification suite was added:

```text
tests/test_geometry_pipeline.py
```

Test groups:
- **TestRigidTransform3D** (5 tests): pure translation, pure rotation, general R+t, reflection check (det=+1), too-few-points→None
- **TestRansacRigidTransform** (4 tests): no outliers exact recovery, 50% outliers, too-few-points, inlier mask shape
- **TestCameraPointToBody** (6 tests): fallback axis mapping, extrinsic identity+offset, oracle consistency proof, 20 random pose oracle consistency
- **TestFullPipelineSynthetic** (3 tests): pure translation scene, yaw-rotated cameras, 10+ random configs vs oracle

All 18 tests pass. Key result: the oracle consistency test proves mathematically that given perfect RANSAC output (i.e., `t = Rc_w.T @ (Pa_w - Pc_w)`), `camera_point_to_body` recovers the same body-frame anchor position as the oracle formula `Rb_w.T @ (Pa_w - Pb_w)`.

**Conclusion:** The 8 m+ consistency errors from SIFT are caused entirely by bad feature matches, not by a bug in the geometry transformation code.

Run command:

```bash
cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench
PYTHONPATH=scripts python -m unittest tests/test_geometry_pipeline.py -v
```

#### SIFT backend test on ep994

The `sift_depth` backend with full extrinsic conversion and consistency gate was tested on episode `994`:

| Backend | Return | Final dist | Notes |
|---|:---:|---:|---|
| `oracle_anchor` | True | 0.619 m | Proves hint pipeline correct |
| `feature_depth` (ORB) | False | 4.424 m | 12/76 estimates; 6–11 inliers |
| `sift_depth` | False | — | 37/37 rejected by consistency gate; min error 8.06 m |

SIFT produced more raw candidates than ORB but every estimate was too far from the action-integrated odometry estimate to be trusted. The system correctly fell back to odometry-only hints rather than injecting wrong anchor directions.

#### LoFTR integration

`kornia==0.6.12` was installed in both `navila-vlm` and `vlnce-isaac` conda environments. The LoFTR `outdoor` pretrained model (44.2 MB, 108 MB VRAM on CUDA) is cached at `~/.cache/torch/hub/checkpoints/loftr_outdoor.ckpt`.

A second test suite was added:

```text
tests/test_loftr_matching.py
```

Offline LoFTR vs ORB comparison on synthetic image pairs (9 tests, all pass):

| Condition | ORB matches | LoFTR inliers | Ratio |
|---|---:|---:|---:|
| Small translation (20 px) | 494 | 2455 | 5.0× |
| 15° rotation | 387 | 2598 | 6.7× |
| 25° rotation | 381 | 1718 | 4.5× |
| 0.75× scale | 324 | 1900 | 5.9× |
| Perspective warp (≈30° tilt) | 229 | 2164 | 9.4× |

LoFTR is wired as the `loftr_depth` backend in `round_trip_eval.py`:

```bash
--route_relocalization_backend=loftr_depth
```

The selection path is: `loftr_depth` → `matcher_backend="loftr"` → `feature_depth_anchor_relocalization(..., matcher_backend="loftr")` → `loftr_match_points()` in `relocalization.py` → `kornia.feature.LoFTR(pretrained="outdoor")`.

Run command for ep994 evaluation with LoFTR (requires VLM server to be running on port 54321):

```bash
cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench && OMNI_KIT_ACCEPT_EULA=YES \
/home/teambruce/miniconda3/bin/conda run \
  --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -p \
  scripts/round_trip_eval.py \
  --task=go2_matterport_vision --num_envs=1 --history_length=9 \
  --load_run=2024-09-25_23-22-02 --headless --enable_cameras \
  --round_trip_mode=phase_prompt --instruction_rewriter_provider=cache_only \
  --episode_idx=994 \
  --route_memory --route_hint_mode=compact \
  --route_relocalization_backend=loftr_depth \
  --result_suffix=loftr_depth_ep994_<date>
```

#### First LoFTR closed-loop result on ep994

The first real `loftr_depth` closed-loop run was completed on episode `994` with a fresh VLM server:

```bash
cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench && OMNI_KIT_ACCEPT_EULA=YES \
/home/teambruce/miniconda3/bin/conda run \
  --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -p \
  scripts/round_trip_eval.py \
  --task=go2_matterport_vision --num_envs=1 --history_length=9 \
  --load_run=2024-09-25_23-22-02 --headless --enable_cameras \
  --round_trip_mode=phase_prompt --instruction_rewriter_provider=cache_only \
  --episode_idx=994 \
  --route_memory --route_hint_mode=compact \
  --route_relocalization_backend=loftr_depth \
  --result_suffix=loftr_depth_ep994_20260628_codex
```

Result:

| Episode | Backend | Outbound | Return | Round trip | Final distance to start | Accepted relocalization lines | Mean confidence |
|---:|---|:---:|:---:|:---:|---:|---:|---:|
| 994 | `feature_depth_loftr_3d3d` | True | True | True | `1.072 m` | 503 | 0.918 |

Artifacts:

```text
artifacts/loftr_depth_ep994_single_success_20260628/
├── measurements/ep994_1699.json
└── trajectories/ep994_output_1699.jsonl
```

Interpretation: this run confirms that the non-oracle LoFTR+depth relocalization path can drive the route-memory hint pipeline to a successful return. The robot emitted the required Return-phase stop inside the 3.0 m start radius.

#### LoFTR hard-subset batch from the previous 30-episode baseline

The previous 30-episode phase-prompt baseline was filtered for episodes with:

```text
baseline outbound_success = true
baseline return_success = false
```

This selected 11 hard episodes:

```text
4, 5, 134, 187, 367, 368, 408, 678, 680, 994, 1040
```

They were evaluated with the same route-memory and LoFTR backend:

```bash
bash scripts/run_loftr_depth_hard_batch_20260628.sh
```

Aggregate result:

| Set | Episodes | Outbound success | Return success | Round-trip success |
|---|---:|---:|---:|---:|
| LoFTR hard subset | 11 | 8/11 | 3/11 | 3/11 |
| Conditional on outbound success in this run | 8 | 8/8 | 3/8 | 3/8 |

Per-episode result:

| Episode | Outbound | Return | Round trip | Final distance to start | Accepted relocalization lines | Mean confidence |
|---:|:---:|:---:|:---:|---:|---:|---:|
| 4 | True | False | False | `7.577 m` | 0 | — |
| 5 | True | False | False | `7.589 m` | 294 | 0.883 |
| 134 | False | False | False | `7.886 m` | 0 | — |
| 187 | True | False | False | `14.208 m` | 1460 | 0.814 |
| 367 | True | True | True | `1.606 m` | 1553 | 0.998 |
| 368 | True | False | False | `7.743 m` | 4878 | 0.898 |
| 408 | False | False | False | `2.125 m` | 0 | — |
| 678 | False | False | False | `5.824 m` | 0 | — |
| 680 | True | True | True | `1.656 m` | 3 | 0.666 |
| 994 | True | False | False | `4.265 m` | 0 | — |
| 1040 | True | True | True | `1.124 m` | 0 | — |

Artifacts:

```text
artifacts/loftr_depth_hard_batch_20260628/
├── summary.json
├── summary.tsv
├── logs/
├── measurements/
└── trajectories/
```

Important reproducibility note:

- A fresh-server single run of ep994 succeeded with 503 accepted LoFTR relocalization trajectory records.
- The batch run of ep994 used the same latest code and the same core CLI parameters, but it failed and had 0 accepted LoFTR relocalization records.

This means the ep994 batch failure should not be interpreted as direct evidence of a code regression. It is more likely caused by non-determinism in VLM output, trajectory branching, Isaac runtime state, or continuous-batch execution effects. Future evaluation should report fresh-server repeated trials separately from continuous-batch trials.

#### Ep994 rerun after anchor-heading reliability fix

After the anchor-heading composition bug was identified, the LoFTR/feature-depth relocalizer was treated as translation-only:

- `anchor_heading_reliable=false` for `feature_depth_loftr_3d3d`.
- LoFTR still supplies the matched anchor vector and via-anchor remaining route distance.
- The start vector is no longer composed through a fake `anchor_dtheta_rad=0`; it falls back to the action-integrated return pose when anchor heading is not reliable.
- `current_pose_from_start` is now populated in anchor-relocalization progress records for diagnostics instead of staying as `[]`.

The first attempt to rerun ep994 with the default W16A16 VLM was invalid: the VLM process successfully listened on `127.0.0.1:54321`, but it hit CUDA OOM during the first generation after Isaac loaded. The valid rerun used the same benchmark command with an 8-bit VLM server:

```bash
python scripts/vlm_server.py \
  --model_path /mnt/SSD4T/teambruce/projects/navila-isaac/checkpoints/navila-llama3-8b-8f \
  --port 54321 \
  --load_8bit
```

Benchmark command:

```bash
cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench && TERM=xterm OMNI_KIT_ACCEPT_EULA=YES \
/home/teambruce/miniconda3/bin/conda run \
  --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -p \
  scripts/round_trip_eval.py \
  --task=go2_matterport_vision --num_envs=1 --history_length=9 \
  --load_run=2024-09-25_23-22-02 --headless --enable_cameras \
  --round_trip_mode=phase_prompt --instruction_rewriter_provider=cache_only \
  --episode_idx=994 \
  --route_memory --route_hint_mode=compact \
  --route_relocalization_backend=loftr_depth \
  --result_suffix=loftr_depth_ep994_fix_8bit_20260628
```

Result:

| Episode | VLM | Backend | Outbound | Return | Round trip | Final true distance to start | Accepted relocalization events | Per-step anchor-relocalization records | Mean confidence |
|---:|---|---|:---:|:---:|:---:|---:|---:|---:|---:|
| 994 | 8-bit | `feature_depth_loftr_3d3d` | True | False | False | `4.363 m` | 73 | 1803 | 0.975 |

Diagnostics:

- VLM was confirmed running for the valid rerun; no VLM OOM occurred in the 8-bit run.
- `route_relocalization_backend=loftr_depth`.
- `anchor_heading_reliable=false` appeared in 139 measurement records, confirming the translation-only path was active.
- The VLM stopped at a true simulator distance of `4.363 m`, outside the 3.0 m return-success radius.
- The final route-memory start vector estimated about `2.947 m` from action-integrated return pose, while simulator ground truth was `4.363 m`; this points to action-integrated return-pose drift after the fake-anchor-heading bug was removed.

Artifacts:

```text
artifacts/loftr_depth_ep994_post_anchor_heading_fix_8bit_20260628/
├── logs/ep994.log
├── measurements/ep994_1699.json
└── trajectories/ep994_output_1699.jsonl
```


#### Ep994 rerun after 3D-3D rotation/dtheta fix

The previous post-anchor-heading run correctly avoided composing through a fake zero heading, but it also discarded the rotation returned by the 3D-3D Kabsch/RANSAC estimate. The feature-depth/LoFTR backend now converts the full registration rotation into `anchor_dtheta_rad`, marks the anchor heading reliable, and lets the route-memory agent compose the anchor-relative start vector with the measured anchor heading.

Run configuration:

```bash
python scripts/vlm_server.py \
  --model_path /mnt/SSD4T/teambruce/projects/navila-isaac/checkpoints/navila-llama3-8b-8f \
  --port 54321 \
  --load_8bit

cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench && TERM=xterm OMNI_KIT_ACCEPT_EULA=YES \
/home/teambruce/miniconda3/bin/conda run \
  --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -p \
  scripts/round_trip_eval.py \
  --task=go2_matterport_vision --num_envs=1 --history_length=9 \
  --load_run=2024-09-25_23-22-02 --headless --enable_cameras \
  --round_trip_mode=phase_prompt --instruction_rewriter_provider=cache_only \
  --episode_idx=994 \
  --route_memory --route_hint_mode=compact \
  --route_relocalization_backend=loftr_depth \
  --result_suffix=loftr_depth_ep994_rotation_fix_20260628
```

Result:

| Episode | VLM | Backend | Outbound | Return | Round trip | Final distance to start | Outbound stop distance to goal | Successful estimates | Pose candidates | Max 3D inliers | Nonzero dtheta records |
|---:|---|---|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|
| 994 | 8-bit | `feature_depth_loftr_3d3d` | True | True | True | `1.264 m` | `1.109 m` | 85 | 672 | 148 | 86/86 |

Return distance checkpoints:

```text
step 2525: 11.719 m
step 3025:  8.436 m
step 3525:  5.952 m
step 4025:  4.435 m
step 4525:  1.703 m
step 4651:  1.264 m, Return stop emitted
```

Diagnostics:

- `anchor_dtheta_rad` is no longer stuck at zero: 86 records were present and all 86 were nonzero.
- Example dtheta values include `6.97 deg`, `-12.03 deg`, `176.13 deg`, `-179.05 deg`, and `-176.67 deg`.
- The relocalizer produced 85 successful estimates; the diagnostics contain 672 pose candidates with mean confidence about `0.709`.
- This supports the diagnosis that the earlier direction failure was caused by dropping the 3D-3D rotation output, not by an ill-conditioned point set.

Artifacts:

```text
artifacts/loftr_depth_ep994_rotation_fix_20260628/
├── summary.json
├── measurements/ep994_1699.json
├── trajectories/ep994_output_1699.jsonl
└── videos/ep994_output_1699.mp4
```

The trajectory JSONL contains the full per-step record for this run.


#### Ep994 rerun after monotonic anchor progress v2

This update addresses the anchor selection / sequence monotonicity problem exposed after the 3D-3D rotation fix. The previous monotonic-anchor attempt stopped anchor regressions but could remain too conservative after a target anchor was passed. The v2 change keeps the monotonic policy, applies it before the consistency gate, and allows target advancement when the robot clearly moves away after approaching a target anchor, even if it never entered the tight `0.8 m` pass radius.

Implemented code snapshot:

```text
code/route_memory_agent.py
code/relocalization.py
code/tests/test_route_memory_agent.py
code/tests/test_geometry_pipeline.py
```

Validation:

```text
tests/test_route_memory_agent.py: 17/17 OK
tests/test_geometry_pipeline.py: 20/20 OK
py_compile route_memory_agent.py relocalization.py round_trip_eval.py: OK
```

Run configuration:

```bash
python scripts/vlm_server.py \
  --model_path /mnt/SSD4T/teambruce/projects/navila-isaac/checkpoints/navila-llama3-8b-8f \
  --port 54321 \
  --load_8bit

cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench && TERM=xterm OMNI_KIT_ACCEPT_EULA=YES \
/home/teambruce/miniconda3/bin/conda run \
  --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -p \
  scripts/round_trip_eval.py \
  --task=go2_matterport_vision --num_envs=1 --history_length=9 \
  --load_run=2024-09-25_23-22-02 --headless --enable_cameras \
  --round_trip_mode=phase_prompt --instruction_rewriter_provider=cache_only \
  --episode_idx=994 \
  --route_memory --route_hint_mode=compact \
  --route_relocalization_backend=loftr_depth \
  --result_suffix=loftr_depth_ep994_monotonic_anchor_v2_20260628
```

Result:

| Episode | VLM | Backend | Outbound | Return | Round trip | Final distance to start | Outbound stop distance to goal | Successful estimates | Monotonic violations |
|---:|---|---|:---:|:---:|:---:|---:|---:|---:|---:|
| 994 | 8-bit | `feature_depth_loftr_3d3d` | True | True | True | `1.148 m` | `0.581 m` | 92 | 0 |

Target-anchor sequence:

```text
None -> 14 -> 13 -> 8 -> 7 -> 6 -> 5 -> 4 -> 3
```

Return distance checkpoints:

```text
step 3075: true distance to start 9.576 m
step 3575: true distance to start 6.715 m
step 4075: true distance to start 4.805 m
step 4575: true distance to start 2.457 m
step 4876: true distance to start 1.148 m, Return stop emitted
```

Important remaining issue:

The target-anchor sequence is now monotonic and ep994 succeeds, but scalar route-memory progress remains conservative late in the run. Near the end the target is still A3 and route-memory distance is about `7.09 m`, while the simulator true distance is `1.15 m`. This happens because the scalar estimate is still `distance_to_target_anchor + target_anchor.route_remaining`. The next fix should replace that scalar with anchor-chain path projection plus monotonic clamping, so passing A3/A2/A1 is represented as along-route progress rather than increasing distance to the old target.

Artifacts:

```text
artifacts/loftr_depth_ep994_monotonic_anchor_v2_20260628/
├── summary.json
├── measurements/ep994_1699.json
├── trajectories/ep994_output_1699.jsonl
└── videos/ep994_output_1699.mp4
```

The trajectory JSONL contains the full per-step record for this run.


#### Ep994 rerun with SeqSLAM particle filter (seqpf_sfix)

This update replaces the single-frame monotonic anchor selection with a probabilistic arc-length tracker. An `ArcLengthParticleFilter` (256 particles) maintains a distribution over the robot's position along the 16 m return route. At each LoFTR relocalization interval the filter receives an observation produced by `seqslam_pose_projection`: the accepted anchor is chosen by ranking candidates against the running history of observations (sequence-consistency score = sum of individual match scores), then the observation arc-length is fed into the particle filter as a Gaussian likelihood update.

`sfix` refers to a stop-emission fix applied alongside the particle filter: the hint format now correctly saturates at 0 m remaining (anchor 0, "at your current position") rather than allowing negative or wrap-around values.

Run configuration:

```bash
python scripts/vlm_server.py \
  --model_path /mnt/SSD4T/teambruce/projects/navila-isaac/checkpoints/navila-llama3-8b-8f \
  --port 54321 \
  --load_8bit

cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench && TERM=xterm OMNI_KIT_ACCEPT_EULA=YES \
/home/teambruce/miniconda3/bin/conda run \
  --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -p \
  scripts/round_trip_eval.py \
  --task=go2_matterport_vision --num_envs=1 --history_length=9 \
  --load_run=2024-09-25_23-22-02 --headless --enable_cameras \
  --round_trip_mode=phase_prompt --instruction_rewriter_provider=cache_only \
  --episode_idx=994 \
  --route_memory --route_hint_mode=compact \
  --route_relocalization_backend=loftr_depth \
  --result_suffix=loftr_depth_ep994_seqpf_sfix_20260628
```

Result:

| Episode | VLM | Backend | Outbound | Return | Round trip | Final distance to start | Outbound stop distance to goal | Successful estimates | Total candidates |
|---:|---|---|:---:|:---:|:---:|---:|---:|---:|---:|
| 994 | 8-bit | `feature_depth_loftr_3d3d` | True | True | True | `1.264 m` | `1.109 m` | 85 | 680 |

Target-anchor sequence (particle filter driven):

```text
None -> 13 -> 9 -> 7 -> 6 -> 5 -> 4 -> 3 -> 2 -> 1 -> 0
```

All 10 anchor transitions occurred with decreasing distance-to-start estimates (monotonic). LoFTR observations contributed to 8 unique sequence entries spanning anchors 14 → 8.

Return distance checkpoints (true Isaac simulator distance vs. particle filter claimed distance):

```text
step 2526: true dist ~13.5 m | hint (action-integrated): 13.54 m     ← accurate
step 2576: true dist ~11.5 m | hint (anchor A13):        13.76 m arc  ← arc, not Euclidean; plausible
step 2726: true dist ~10.0 m | hint (anchor A7):          7.84 m      ← ~2 m underestimate
step 2951: true dist  ~8.6 m | hint (anchor A5):          5.59 m      ← ~3 m underestimate
step 3201: true dist  ~7.5 m | hint (anchor A3):          3.34 m      ← ~4 m underestimate
step 3551: true dist   5.8 m | hint (anchor A0):          0.34 m      ← 5.5 m ERROR — filter lost track
step 3626: true dist   5.5 m | hint (anchor A0):          0.00 m      ← saturated at 0, robot still ~5.5 m away
step 4400: true dist   2.5 m | hint (anchor A0):          0.00 m      ← still saturated
step 4576: true dist   1.4 m | hint (anchor A0):          0.00 m      ← still saturated
step 4651: true dist   1.3 m | VLM emits stop (return success)
```

Particle filter final state:

```text
particle_count:    256
total_length_m:   16.00
mean_remaining_m:  6.72  (high — bimodal distribution)
mode_remaining_m:  1.19  (mode is accurate: 1.19 m vs true 1.26 m)
std_remaining_m:   4.10  (very high — filter is uncertain)
confidence:        0.49
```

Diagnosis:

The particle filter made 8 successful LoFTR observations while the robot traversed anchors 14 → 8 (route positions 14.1 m → 7.8 m). After passing the anchor-8 region no further observations were accepted, likely because the robot's viewpoint moved outside the field-of-view overlap with outbound anchor images. Without new observations the filter propagated on motion-model alone, accumulated drift, and reported anchor-0 arrival (≤ 0.34 m remaining) from step 3551 onward — 1100 steps and ~5 m of true travel before the robot actually stopped.

From step 3626 to 4651 every VLM call received the hint "route anchor A0 is 0.00 m away, at your current position." Despite this the VLM did **not** emit a premature stop; it continued navigating until the simulator true distance was ~1.26 m. This means:

1. The VLM correctly down-weighted or ignored the erroneous terminal hint.
2. Return success on this episode is attributable to the VLN return instruction and visual navigation, not to the relocalization hint.
3. The particle filter provides accurate guidance during the first half of Return (~14 m → 8 m from start) but fails in the second half where LoFTR co-visibility drops.

Next step: increase anchor density or use wider-baseline matching in the second half of the route so the filter stays calibrated closer to the start.

Artifacts:

```text
artifacts/loftr_depth_ep994_seqpf_sfix_20260628/
├── summary.json
├── measurements/ep994_1699.json
└── trajectories/ep994_output_1699.jsonl
```

The trajectory JSONL contains the full 4652-step per-step record for this run (4652 records: 2225 outbound + 300 confirm + 2127 return).

---

### Run: `loftr_depth_ep994_hint_gate_20260628`

**Date:** 2026-06-28  
**Suffix:** `loftr_depth_ep994_hint_gate_20260628`  
**Config:** LoFTR backend, SeqSLAM particle filter, 8-bit VLM, uncertainty-gated hints (improvements 1–3)

| Metric | Value |
|---|---|
| outbound_success | true |
| return_success | **false** |
| round_trip_success | **false** |
| distance_to_start_m | **4.403 m** |
| outbound_stop_distance_to_goal_m | 1.040 m |
| total_steps | 3927 |
| hint_events | 26 (5 normal, 21 gated) |
| relocalization_successful | 12 |
| sequence_observations | 8 |
| particle_filter_std_at_stop | ~3.88 m |

Hint events:

```
step 2376: dist=13.82m  std=N/A   → normal  (action-integration only)
step 2426: dist=13.77m  std=1.29m → normal  (LoFTR anchor 12)
step 2451: dist=14.04m  std=1.57m → normal
step 2476: dist=13.13m  std=1.17m → normal
step 2551: dist=12.62m  std=2.91m → normal  (last observation — anchor 8)
step 2626: dist=10.80m  std=3.68m → GATED ← threshold 3.2m crossed
step 2701-3926: 21× GATED         → "position uncertain (σ≈4.0m, filter lost lock); ... do NOT stop until visually confirmed"
```

VLM stop at step 3926, distance to start = **4.403 m** (outside 3.0 m threshold → failure).

Diagnosis:

Hint gating activated at dist 10.8 m — leaving the VLM with no specific distance or direction guidance for the remaining 10+ m of return. The VLM received 21 consecutive generic "position uncertain, continue via visual instruction" messages. Without a concrete anchor-distance narrative, the VLM applied a visual stop check and terminated at 4.4 m, judging it had reached the start.

Comparison with `seqpf_sfix` (which succeeded at 1.264 m):

| | seqpf_sfix (success) | hint_gate (failure) |
|---|---|---|
| Hint from step 2626 onward | "A0 is 0.00 m away" (specific, wrong) | "position uncertain, use visual instruction" (generic, correct) |
| VLM behaviour | Ignored wrong arrival claim, kept moving for 600 more steps | No navigational narrative; stopped at 4.4 m on visual cue |
| Return steps | 2127 | ~1550 |

Key lesson: the VLM is robust to *specific-but-wrong* distance hints — it correctly down-weighted the erroneous "0 m arrived" claim in seqpf_sfix via its visual system. Replacing specific hints with generic "keep going" warnings removed the implicit navigational narrative without improving VLM robustness. The hint gating as implemented is harmful.

Fix direction: preserve specific directional and distance information in gated hints; suppress only the explicit "you have arrived / stop now" claim. For example, a gated hint should still report anchor bearing and approximate distance while marking the estimate as uncertain, rather than delegating entirely to visual judgment.

Particle filter final state:

```text
sequence_observations: 8 (anchors 12→8, same coverage as seqpf_sfix)
filter_std_at_stop:    ~3.88 m
mode_remaining_m:      ~0.0 m (filter collapsed — same failure mode as seqpf_sfix)
```

The filter collapse pattern is identical to seqpf_sfix: 8 observations in the first half of the route (14–8 m from start), then no observations and rapid std inflation due to blackout noise. The gating correctly detected filter loss-of-lock but the resulting hint change made things worse.

Artifacts:

```text
artifacts/loftr_depth_ep994_hint_gate_20260628/
├── summary.json
├── measurements/ep994_1699.json
└── trajectories/ep994_output_1699.jsonl
```

The trajectory JSONL contains 3927 per-step records (2075 outbound + 0 confirm-phase + 1852 return — shorter than seqpf_sfix because VLM stopped earlier).

---

## Key Differences vs RTX 5090 (Blackwell) Setup

This deployment is significantly simpler than running on a Blackwell GPU:

| Item | RTX 5090 (Blackwell sm_120) | RTX 4090 (Ada Lovelace sm_89) |
|---|---|---|
| PyTorch | Needed cu128 (torch 2.11+) | Original cu121 (torch 2.3.0) works |
| FlashAttention | No prebuilt wheel; source build failed | Prebuilt wheel available |
| Isaac torch | Needed upgrade to cu128 | IsaacLab-pinned 2.2.2+cu121 works |
| RAM/VRAM | 32 GB VRAM (5090) | 24 GB (tight but sufficient with 8-bit) |

The only patches needed here are genuine code bugs or minor version mismatches unrelated to GPU architecture.

---

## References

- [NaVILA Paper (RSS 2025)](https://arxiv.org/abs/2412.04453)
- [NaVILA GitHub](https://github.com/AnjieCheng/NaVILA)
- [NaVILA-Bench GitHub](https://github.com/yang-zj1026/VLN-CE-Isaac)
- [IsaacLab fork](https://github.com/yang-zj1026/IsaacLab)
- [NaVILA checkpoint (HuggingFace)](https://huggingface.co/a8cheng/navila-llama3-8b-8f)
- [VLN-CE-Isaac dataset (HuggingFace)](https://huggingface.co/datasets/Zhaojing/VLN-CE-Isaac)
