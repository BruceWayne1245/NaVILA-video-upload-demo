# Pending work and execution order

## Status boundary

As of this archive update:

- V1 is frozen and rejected for enforcement.
- V1.1 is frozen as a development-only offline candidate.
- all 89 historical runs are development data;
- no untouched prospective model result exists;
- no V1.1 online/portable runtime exists;
- a separate 16-episode capture rerun is reported as running in
  [`../2026-07-21-gating-diagnosis-fix-and-capture/FINDINGS.md`](../2026-07-21-gating-diagnosis-fix-and-capture/FINDINGS.md);
- the main-repository code has advanced beyond the V1/V1.1 source baseline.

## Required sequence

### 1. Finish and audit the capture path

Wait for the separate capture work to complete, then verify:

- exact attempt-step and current/next linkage;
- no dropped scalar, basin, temporal, point-cloud, or RGB-D records;
- episode-state reset and deterministic sample reasons;
- raw clouds/top basins contain the fields required by V1.1;
- capture does not change navigation behavior or timing materially;
- at least 100 recomputed labels match with zero discrepancy.

The capture subsystem and runtime/navigation integration are owned by the
separate gating/capture workstream. They must be reviewed, not copied blindly
into the model snapshots.

### 2. Build a V1.1 online shadow runtime in an isolated candidate

Implement, without touching live code:

- exact top-4 basin/yaw/scan/localizability feature extraction;
- current/next same-attempt pair construction;
- causal 4/8/16/32 histories keyed by episode and anchor;
- explicit state reset at every episode boundary;
- the exact frozen 249-feature order;
- a portable artifact compatible with Isaac's Python environment;
- hard locks that keep all enforcement fields false.

### 3. Prove offline/online feature and probability parity

Replay recorded attempt sequences through both the dataset builder and runtime
state machine. Require:

- identical or tolerance-bounded features in the frozen order;
- negligible portable-vs-sklearn probability error;
- zero trusted-decision mismatch;
- zero NaNs or silent default substitutions;
- no future-state use and no state crossing episode boundaries.

### 4. Run a short real-episode shadow canary

The canary is for engineering validity only:

- artifact loads in Isaac;
- all records are emitted;
- no navigation behavior is changed;
- latency/control-loop impact is measured;
- no logging corruption or memory growth occurs.

It does not count as prospective model performance.

### 5. Freeze before opening new outcomes

Freeze commit, artifact hash, feature order, category map, temporal reset rules,
thresholds, episode list, capture schema, and report code. Do not tune anything
after prospective labels or aggregate outcomes are opened.

### 6. Run the prospective shadow evaluation

Primary statistical unit: physical CLI episode ID. The predeclared gates are:

| Head | Minimum AUC | Maximum one-sided 95% cluster-UCB trusted risk | Minimum coverage |
|---|---:|---:|---:|
| bearing | 0.80 | 10% | 35% |
| distance | 0.92 | 5% | 35% |
| pose | 0.96 | 5% | 30% |

Also report current/next role, scene, early/middle/late return, worst scene,
episode-macro and scene-macro metrics. Unusable episodes remain in the
operational denominator with explicit reasons.

### 7. Add the missing joint operating point

Before any consumer uses “trusted pose,” report:

- coverage when bearing, distance, and pose all pass simultaneously;
- joint bad rate and cluster upper bound;
- consecutive trusted/untrusted streak lengths;
- per-attempt availability after current/next selection;
- whether rejection means wait, retry, switch candidate, or fall back.

The current per-head 45-51% coverages do not determine joint availability.

### 8. Evaluate consumer value separately

Passing the model gates only permits a reviewed experiment. Test one consumer
at a time, in increasing risk order. Full episode outcomes must compare frozen
shadow-on/off or enforcement-on/off configurations with all other settings
identical. In particular, model accuracy alone does not establish missed-stop
recovery or navigation improvement.

## Decision branches after prospective evidence

- **Passes with useful coverage:** consider a narrowly scoped shadow-to-action
  experiment, starting with confidence reporting or deferral, not current
  identity ownership.
- **Ranking passes but calibration/risk fails:** do not tune on the prospective
  test set; create V1.2 using that batch as new development data and collect a
  later untouched batch.
- **Scalar/basin/temporal model plateaus:** use the newly captured raw point
  clouds and RGB-D for a point-cloud/vision model; do not keep increasing HGB
  capacity on indistinguishable scalar rows.
- **LiDAR remains irreducibly ambiguous:** route to vision fusion or
  motion-integrated mapping rather than claiming a classifier can resolve
  physically identical corridor geometry.
