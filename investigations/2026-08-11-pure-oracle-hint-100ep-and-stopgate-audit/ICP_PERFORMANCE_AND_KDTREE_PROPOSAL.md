# ICP relocalization performance: root cause + proposed KD-tree fix (proposal only, not yet implemented)

Arose while comparing `pure_oracle_hint_100ep_20260811`'s per-episode wall-clock time against non-oracle batches (see `README.md` in this folder) — non-oracle episodes were taking 4-7x longer wall-clock time despite nearly identical simulated step counts for the same episode. This file documents the root cause and a proposed fix. **Nothing here has been implemented or tested yet** — try it when running the next non-oracle batch (planned 2026-08-12 or 2026-08-13).

## Evidence: it's per-query compute overhead, not extra simulated motion

Same-episode comparison, `pure_oracle_hint_100ep_20260811` (route_relocalization_backend=none) vs `reliability_fixon_100ep_20260721_accumulated` (route_relocalization_backend=sequential_pair):

| episode_idx | oracle_hint: wall time / sim steps | non-oracle: wall time / sim steps | slowdown |
|---|---|---|---|
| 4 | 2.7 min / 2627 | 13.3 min / 2802 | ~4.9x |
| 5 | 6.5 min / 6159 | 47.3 min / 6852 | ~7.3x |
| 367 | 6.0 min / 7052 | 25.9 min / 5977 (fewer steps!) | ~4.3x |
| 680 | 3.6 min / 3977 | 18.9 min / 4427 | ~5.25x |

Step counts differ by ~15% at most (367 even has *fewer* steps for the slower run), so the extra time isn't the robot travelling further or wandering more — it's pure compute overhead per relocalization query. Separately confirmed: `round_trip_eval.py`'s main loop has no `time.sleep`/real-time-sync — it's fully lockstep (sim time only advances via explicit `env.step()` calls), so none of this wall-clock overhead leaks into simulated time, robot motion, or what the VLM perceives — it's purely extra wall-clock cost to whoever is waiting on the batch.

## Root cause: brute-force CPU nearest-neighbor, swept across 24 yaw seeds, per candidate anchor

`scripts/relocalization.py` has no `torch`/`open3d`/`cupy` import anywhere — the whole ICP stack is plain CPU `numpy`. The RTX 4090 is not involved in this code path at all (it's busy with Isaac Sim rendering + VLM inference, which are separate from this).

- `_nearest_neighbor_2d()` (`relocalization.py:534`) is brute-force: chunked (128 rows at a time) but still O(N×M) pairwise distance computation, no spatial index (no KD-tree/octree).
- `icp_rigid_transform_2d()` (`relocalization.py:1278`) runs up to `max_iterations` (16-24 depending on call site) ICP iterations, each calling `_nearest_neighbor_2d()` once.
- `icp_seed_sweep_2d()` (`relocalization.py:828`) runs `icp_rigid_transform_2d()` once per entry in `yaw_initializers` — a Python `for` loop, not vectorized/batched across seeds.
- `yaw_initializers = [math.radians(deg) for deg in range(-180, 180, 15)]` (defined identically at `relocalization.py:1718`, `1954`, `2207`) — **24 seeds**, one every 15°.
- The seed sweep itself runs **once per candidate anchor** being evaluated per relocalization query (the call at `relocalization.py:1758` sits inside a `for` loop over anchor candidates) — non-oracle batches typically evaluate at least "current" and "next" anchors per query, sometimes more with alias-aware promotion checking.

Net cost per relocalization query ≈ `num_candidate_anchors × 24 seeds × ≤16 iterations × O(N×M) brute-force NN search` (point clouds capped at `route_local_map_max_points=512` in the `reliability_fixon` config used above) — entirely single-threaded CPU Python, run at `--route_relocalization_interval_updates=5` (every 5th VLM-query step in that config), plus `--capture_icp_replay_dataset` disk I/O on top for batches that enable it.

## Proposed fix: swap the nearest-neighbor search for `scipy.spatial.cKDTree`

Replace `_nearest_neighbor_2d()`'s brute-force loop with a KD-tree query (`cKDTree(target).query(source)`), O(N log M) instead of O(N×M). This is the standard ICP acceleration technique and, importantly, is **exact** — a KD-tree nearest-neighbor query returns the identical correspondences brute force does, just faster. Should have **zero accuracy/behavior impact** on any of the existing ambiguity diagnostics, basin-clustering, or downstream promotion/quarantine logic that consume `icp_rigid_transform_2d`'s output — it's a pure speed win with no expected change to `theta`/`translation`/`median_residual_m`/`overlap_ratio` results (modulo floating-point tie-breaking on exact-distance ties, which should be rare with continuous point-cloud data).

**Not proposed for now** (higher-risk trade-offs, flagged but deliberately out of scope for this pass):
- Reducing the 24-seed sweep count — the sweep exists specifically to avoid ICP converging to a wrong local minimum from a bad initial yaw guess, which is exactly the project's recurring "confidently-wrong ICP" failure mode (see e.g. `2026-07-24-confidently-wrong-reanalysis`). Cutting seeds trades speed for a real accuracy risk that would need separate validation.
- Parallelizing the seed sweep (multiprocessing across CPU cores, or batching onto GPU as a tensor op) — each seed is independent so this is technically straightforward, but is a bigger structural change than a drop-in KD-tree swap and wasn't attempted here.

## To try next (2026-08-12/13, when running the next non-oracle batch)

1. Implement the `cKDTree` swap in `_nearest_neighbor_2d()`.
2. Sanity-check on a handful of episodes that ICP outputs (theta/translation/residuals/overlap_ratio) are unchanged vs. the brute-force version — same input point clouds should produce bit-for-bit-comparable-ish correspondences.
3. Re-run the same same-episode wall-clock comparison done above to quantify the actual speedup.
4. Only after that's confirmed clean, consider whether the seed-count/parallelism trade-offs above are worth pursuing.
