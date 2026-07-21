# Reliability V1 acceptance gates

Status: **shadow-only; enforcement locked**.

## Evidence from the strict 2026-07-21 evaluation

The split is chronological and episode-disjoint: 9,596 training readings from
11 oldest-batch episode IDs, 2,740 calibration readings from 3 middle-batch
episode IDs, and 52,027 test readings from 42 latest-batch episode IDs. There
is no episode-ID overlap between the three partitions.

| Gate | Required | Observed | Status |
|---|---:|---:|:---:|
| Bearing test AUC | ≥ 0.75 | 0.8159 | PASS |
| Distance test AUC | ≥ 0.85 | 0.9343 | PASS |
| Pose test AUC | ≥ 0.90 | 0.9734 | PASS |
| Bearing trusted bad rate | ≤ 10% | 25.7% | **FAIL** |
| Distance trusted bad rate | ≤ 5% | 13.6% | **FAIL** |
| Pose trusted bad rate | ≤ 5% | 12.9% | **FAIL** |
| Pinned-current detection | 13/13 | 13/13 | PASS |
| False eviction on healthy current segments | 0 | 0/113 | PASS* |
| Missed-stop recovery | > 0/8 | 0/8 | **FAIL** |
| False-stop streak episodes | 0 | 0 | PASS |

The group-aware offline audit adds 95% episode-cluster confidence intervals:
bearing trusted bad rate 20.0–32.2%, distance 8.9–19.2%, and pose 8.6–18.4%.
All remain above their targets. The test partition has 42 episodes but only
8 scenes, with scene overlap across train/calibration/test, so this is not an
unseen-scene generalization result. See `OFFLINE_AUDIT_REPORT.md`.

`*` The eviction policy (`p_pose_bad >= 0.7` for 10 consecutive attempts) was
selected after inspecting the 7/20 replay. It therefore requires a new,
untouched prospective batch before it can be treated as validated.

## Unlock requirements

All of the following are required before adding an enforcement choice:

1. A new prospective batch not used in feature, threshold, or policy design.
2. Episode-disjoint reporting plus a separate full-batch operational report.
3. Trusted bad rates meet their consumer-specific targets with useful coverage.
4. Pinned-current detection remains high with zero healthy-current eviction
   recommendations under the frozen `0.7 × 10` policy.
5. Stop changes demonstrate recoveries without a false-stop streak. The current
   anchor-distance head alone does not satisfy this condition.
6. A full prospective live shadow batch confirms runtime feature parity and no
   inference-induced latency or logging corruption. A one-episode shortened
   smoke run passed the plumbing check (402 records, no enforced action,
   1.139 ms/candidate), but is not sufficient to clear this gate.

Until then, reliability output may be logged and analyzed but must not change
hint arbitration, promotion, quarantine, current identity, or stop behavior.
