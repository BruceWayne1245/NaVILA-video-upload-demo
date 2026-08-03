# 2026-07-13 (continued 5) — Two fusion-reconciliation variants tested live on ep368; Variant 1 ("no fusion at all") adopted as the new main configuration; LoFTR-rear closing note

## Two variants tested against `FUSION_MECHANISM_ANALYSIS.md`'s findings

Per the user's request, implemented and live-tested two fixes on `ep368` (all runs also carry `--sequential_pair_loftr_rear_yaw_check`):

- **New flags**: `--sequential_pair_disable_temporal_smoothing` (skips `_temporally_smooth_relocalization`, the mechanism responsible for 93.5% of measured corruption) and `--sequential_pair_closure_reconciliation_signal={dtheta,bearing}` (switches the closure-check/temporal-smoothing trust signal from rotation to bearing agreement, and stops circular-averaging dtheta in either mechanism — see code in `relocalization.py`/`route_memory_agent.py` snapshots in this folder's `code/`).
- **Variant 1**: `--sequential_pair_disable_temporal_smoothing` + `--sequential_pair_closure_check` omitted → no cross-anchor fusion, no temporal EMA, every accepted attempt reports its raw selected `(dx, dy, dtheta)` unmodified.
- **Variant 2**: closure-check + temporal smoothing both left on, `--sequential_pair_closure_reconciliation_signal=bearing`.

**Bearing-error result (ground-truth-checked, same methodology as this folder's other documents):**

| variant | n | median | mean | >10° | >45° |
|---|---|---|---|---|---|
| Baseline (current default, dtheta fusion) | 321 | 4.78° | 23.67° | 39.6% | 15.3% |
| **Variant 1 (no fusion at all)** | 356 | **1.79°** | **8.24°** | **11.2%** | 5.9% |
| Variant 2 (bearing reconciliation) | 306 | 3.32° | 10.24° | 19.0% | **4.2%** |

Both round trips succeeded (outbound/return both `True`), with final `distance_to_start` closer to the goal than baseline in both cases (1.56m/1.62m vs 1.82m). Variant 1 wins on median/mean/>10°; Variant 2 has the lowest severe-error (>45°) rate, consistent with retaining *some* cross-anchor check (just bearing-based, not dtheta-based) still catching a few of the worst single-anchor failures Variant 1's complete removal can no longer catch.

**Decision (user, 2026-07-13): Variant 1 ("no fusion at all") is adopted as the new main configuration** going forward — simpler, and the best result on the metric that matters operationally (bearing).

## LoFTR-rear closing note: valuable for rotation, not usable for bearing

Extended `_loftr_rear_yaw_check` to also report its own translation-derived bearing (`loftr_rear_dx_m`/`dy_m`/`bearing_to_anchor_deg`, via the same `camera_point_to_body` this project's retired `feature_depth_loftr_3d3d_rear` backend already used), then re-ran `ep368` on the new main (Variant 1) configuration to check LoFTR-rear's own bearing accuracy, not just its already-confirmed rotation accuracy.

**Result: LoFTR-rear's bearing is much worse than ICP's, the opposite of the rotation finding:**

| | mean | median | >10° | wins vs the other |
|---|---|---|---|---|
| ICP bearing | 15.99° | **2.02°** | 23.4% | — |
| LoFTR-rear bearing | 60.17° | 28.76° | 89.0% | LoFTR-rear beats ICP only **12.6%** of readings |
| ICP dtheta (rotation, for reference) | 53.3° | 39.6° | — | — |
| LoFTR-rear dtheta (rotation) | 24.0° | 18.4° | — | LoFTR-rear beats ICP **93.8%** of readings |

On the 163 readings where ICP's own bearing was already >10° (i.e. exactly the population a rescue mechanism would need to help), LoFTR-rear's own bearing only lands under 10° in 6.1% of them — not a usable rescue signal.

**Interpretation**: LoFTR-rear's 3-D RANSAC fit constrains rotation well (bearing-invariant, well-conditioned by matched feature directions) but its translation/scale estimate is comparatively noisy (rear-camera geometry, monocular-depth-derived point scale) — good for cross-checking *rotation*, not for supplying *bearing*. **Given Variant 1 has already removed fusion (the only place rotation accuracy mattered downstream), LoFTR-rear's practical role in the current architecture has evaporated**: nothing downstream consumes dtheta anymore to reconcile with, and LoFTR-rear cannot substitute for or rescue ICP's bearing. This closes out the LoFTR-rear investigation line — it correctly diagnosed and confirmed the rotation problem (and reinforced that RGB carries real independent information LiDAR lacks), but the practical fix that emerged (removing fusion) solved the operationally-important metric directly, without ending up needing LoFTR-rear as a live component.

## Reproducibility

Scripts and code snapshots in this folder's `code/`: `run_no_fusion_ep368_20260713.sh`, `run_bearing_reconciliation_ep368_20260713.sh`, `run_no_fusion_loftr_bearing_ep368_20260713.sh` (launchers), current `relocalization.py`/`route_memory_agent.py`/`round_trip_eval.py` (full snapshots including the reconciliation-signal and disable-temporal-smoothing changes).
