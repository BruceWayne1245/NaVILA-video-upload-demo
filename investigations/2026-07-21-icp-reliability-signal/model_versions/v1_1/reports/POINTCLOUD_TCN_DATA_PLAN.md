# Point-cloud and temporal-model data plan

This is the next-data plan, not authorization to train a larger model now.

## Raw capture format

Store arrays outside the measurement JSON. Use one compressed NPZ (or an
equivalent chunked HDF5/LMDB record) per `(batch, episode, attempt, anchor)`:

- `anchor_points_xyz`: sampled room-scale anchor cloud, preserving z.
- `current_points_xyz`: sampled current cloud before ICP.
- point-valid masks and original point counts.
- ICP transform, top basins, scalar diagnostics, and feature-schema version.
- labels and simulator ground truth in a separate offline-only metadata table.

Measurement JSON should contain only the relative record path, checksum, shape,
and capture version. This avoids repeating the existing giant-JSON corruption
failure mode. Capture must be asynchronous or bounded so it cannot perturb the
navigation control loop.

## Point model milestone

After collecting enough independent scenes and episodes, benchmark a shared
two-tower PointNet++ encoder over fixed-size anchor/current clouds, concatenate
the relative embedding with the scalar diagnostics, and retain the same three
heads: bearing risk, distance risk, and joint-pose risk. DGCNN and point
transformers are later comparisons, not the first implementation.

The split unit remains episode ID and scene; repeat measurements from one route
must never cross train/calibration/test. Report scalar-only and point-model
results on the same untouched prospective batch.

## Temporal milestone

Keep the current bounded deterministic controller until there are many
independent pinned and healthy recovery sequences. A later causal TCN can use a
16–32 attempt window containing per-candidate probabilities, residual/overlap
statistics, distance trend, variance, role dwell, and staleness. It must never
consume future attempts, episode identity, batch identity, or outcomes.

## Residual ambiguity

Geometrically identical corridors can remain indistinguishable even with raw
LiDAR. Preserve synchronized rear/front RGB-D or compact visual embeddings so a
future fusion model can resolve the confidently-wrong residual that point
geometry alone cannot separate.
