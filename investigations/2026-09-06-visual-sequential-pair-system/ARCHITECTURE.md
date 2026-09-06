# Complete architecture

## 1. Outbound route memory

Outbound navigation remains controlled by NaVILA.  Route memory samples a new
anchor every approximately `0.2 m`.  Each visual anchor contains:

- rear RGB image;
- rear depth image;
- rear-camera intrinsics;
- rear-camera world pose and body extrinsics;
- outbound route index and accumulated distance;
- relative edge geometry from the preceding anchor;
- analysis-only Isaac world pose in metadata.

The final outbound pose is always flushed as anchor `N`, even if it is less
than `0.2 m` from the previous anchor.  Anchor 0 is backfilled with the first
real sensor descriptor, preserving the existing fix for an empty start anchor.

During outbound, the rear camera looks back along the traversed path.  After
the robot turns for return, its front camera looks in approximately the same
world direction, giving the intended front-to-rear visual overlap.

## 2. Return initialization

No global retrieval is performed.  `finalize_outbound()` initializes:

```text
current = anchor N
next    = anchor N-1
```

The route-memory agent owns anchor identity.  The visual backend cannot modify
the candidate set directly.

## 3. Ordered-pair visual relocalization

At every relocalization update:

```text
return front RGB-D
   |-- match against outbound rear RGB-D(current)
   `-- match against outbound rear RGB-D(next)
```

For each side independently:

1. LoFTR creates 2-D feature correspondences.
2. Valid depth pixels are back-projected through the calibrated intrinsics.
3. A robust 3-D rigid transform is estimated with RANSAC.
4. The transform is converted from camera coordinates to robot-body axes.
5. The measurement reports anchor-relative translation, yaw, bearing,
   distance, inlier count, residual diagnostics, and confidence.

The backend explicitly removes all `rear_*` aliases from the temporary anchor
descriptor after promoting the rear view to the primary view, preventing the
generic matcher from processing the same image twice.  It does not request or
read the local LiDAR-map descriptor.

## 4. Dual-anchor consistency and promotion

The existing route-memory state machine receives zero, one, or two visual
measurements.  When both are present, their implied relative geometry is
cross-checked against the outbound current-to-next edge.  An unresolved pair
disagreement becomes a failed promotion vote rather than an arbitrary winner.

The state machine emits one of two normal transitions:

- `KEEP`: retain the current pair;
- `PROMOTE`: make next the new current and expose exactly one preceding anchor
  as the new next.

Normal operation cannot move more than one anchor per decision.  Missing
visual evidence causes retention/abstention, not a full-route search.

The first implementation retains the M50 bounded-evidence mechanism so the
sensor-backend change can be isolated.  Its numerical thresholds are not yet
claimed to be optimal for `0.2 m` anchors.

## 5. Hint, arbiter, and NaVILA action

The accepted visual state is converted into the existing compact route hint:

```text
visual current/next estimate
    -> bearing, distance, route remaining, freshness/confidence
    -> compact system hint
    -> Hint/Arbiter
    -> NaVILA action
```

A stale next-anchor estimate is suppressed rather than repeatedly injected.
The arbiter may override an action only under its normal confidence and local
clear-path conditions.  The VLM remains the return action generator; this is
not the separate deterministic-waypoint-controller baseline.

Because a `0.2 m` next anchor can produce unstable bearing near zero distance,
a route-chain look-ahead target of approximately `0.6–1.0 m` remains a planned
follow-up.  It is deliberately not mixed into this first sensor-backend fork,
which preserves M50 next-anchor hint semantics for causal isolation.

## 6. Terminal handling

Pair progression eventually reaches `(1, 0)`.  Visual evidence can corroborate
route progress, but identifying anchor 0 does not directly declare success.
The existing stop gate and benchmark success radius remain authoritative, and
the robot must still satisfy the configured stopping behavior.

## 7. Ground-truth monitoring boundary

`VisualGroundTruthMonitor` reads Isaac state only after control decisions and
writes an append-only analysis sidecar.  It is not passed into relocalization,
route memory, Hint/Arbiter, NaVILA, or stop gate and exposes no method that
returns truth to those components.

Each step records:

- phase and step;
- true robot world pose and yaw;
- current/next indices;
- true body-frame vector, distance, and bearing to both anchors;
- online estimated progress and confidence;
- online bearing and distance error against Isaac truth;
- VLM output and executed command.

It also records anchor creation and pair-transition events and saves every
anchor's rear RGB-D/calibration fields as compressed NPZ data.

Expected result layout:

```text
<episode result>/visual_ground_truth/
  ground_truth_monitor.jsonl
  ground_truth_monitor_summary.json
  anchors/anchor_00000_rear_rgbd.npz
  anchors/anchor_00001_rear_rgbd.npz
  ...
```

