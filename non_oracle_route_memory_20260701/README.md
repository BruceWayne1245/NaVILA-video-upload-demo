# Non-oracle route-memory code snapshot

Date: 2026-07-01

This folder is a focused copy of the non-oracle route-memory, relocalization, local-map, and hint-arbiter code used for the `oracle_shadow_loftr_v4_30_return_anchor_fix_20260701` batch.

The evaluation still feeds oracle hints to the VLM, but the non-oracle pipeline runs in shadow and logs its anchor selection, distance, bearing, and route-progress estimates for comparison.

Files:

```text
route_memory_agent.py
relocalization.py
local_map.py
hint_action_arbiter.py
round_trip_eval.py
run_oracle_shadow_loftr_v4_30_batch_20260701.sh
tests/
```

Main return-start fixes included here:

- `finalize_outbound()` now preserves the final outbound descriptor and metadata, so the return-start anchor is matchable by the non-oracle relocalizer.
- The first return update forces relocalization instead of waiting for the normal interval.
- Oracle direct-route target-anchor selection and route-memory target selection now share the same lookahead helper, reducing code-induced anchor-index mismatch.
- The relocalization candidate window default is now unlimited (`--route_relocalization_window=0`); pass a positive value only when an explicit cap is desired.

Known remaining non-oracle limitations:

- LoFTR candidate search is still ordered from the outbound end backward. The fixed 8-anchor cap has been removed, but long routes may still need expected-progress candidate ordering for speed and stability.
- Bearing and target-vector estimates are noisy even when the anchor index is correct, mainly from pose projection/yaw error.
- The next implementation step should use an expected-progress candidate window plus stronger progress hysteresis.
