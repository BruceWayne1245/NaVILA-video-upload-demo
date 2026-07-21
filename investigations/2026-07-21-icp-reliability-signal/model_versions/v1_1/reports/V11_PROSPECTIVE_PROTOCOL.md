# Reliability V1.1 prospective shadow protocol

Status: **predeclared; not yet executed**.

## Freeze boundary

Before any new-batch labels or aggregate outcomes are opened, freeze:

1. the V1.1 repository commit and tag;
2. dataset and artifact SHA-256 values;
3. feature order, causal history construction, calibrators, thresholds, and
   temporal reset rules;
4. the episode list, scene allocation, capture schema, and report code.

No threshold, feature, model, or exclusion rule may change during the batch.

## Statistical unit and replay paths

- Primary independent unit: physical CLI episode ID, not ICP reading and not
  repeated episode-run.
- All current/next candidates from one attempt remain in the same unit.
- If capture stores every exact V1.1 input with no drops, frozen offline replay
  is valid for the statistical model report.
- A separate full-episode online shadow canary is still required for runtime
  loading, causal-state parity, latency, and logging integrity.

## Label and data-integrity gates

- `drop_count == 0` for all required scalar/basin/temporal input records.
- Attempt count and persisted attempt-step linkage agree for every usable run.
- At least 100 deterministic stratified labels are recomputed from raw robot and
  anchor poses with zero mismatches.
- Missingness and unseen-category drift are reported before outcome metrics.
- Unusable episodes remain in the operational denominator and are reported by
  failure reason; they are never silently discarded.

## Predeclared model gates

All risk bounds use a one-sided 95% physical-episode-cluster bootstrap.

| Head | Minimum AUC | Maximum trusted bad-rate upper bound | Minimum trusted coverage |
|---|---:|---:|---:|
| bearing | 0.80 | 10% | 35% |
| distance | 0.92 | 5% | 35% |
| pose | 0.96 | 5% | 30% |

Additionally report episode-macro, scene-macro, worst-scene, current-role,
next-role, and early/middle/late-return metrics. No consumer can unlock if its
role-specific risk materially violates the corresponding pooled gate.

## Runtime shadow gates

- Every enforcement field remains false for the entire run.
- Shadow on/off navigation configuration and behavior are compared on the
  canary episodes.
- No inference exception, NaN probability, state leakage between episodes, or
  dropped output is allowed.
- Per-candidate latency distribution and control-loop impact are reported; a
  single shortened smoke is not sufficient.

## Decision rule

Passing this protocol permits consideration of a separately reviewed consumer
experiment. It does not automatically enable hint, stop, promotion, quarantine,
or current-identity enforcement.
