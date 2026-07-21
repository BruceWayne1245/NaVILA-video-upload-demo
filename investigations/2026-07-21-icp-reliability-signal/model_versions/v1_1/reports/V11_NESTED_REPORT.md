# Reliability V1.1 nested development report

## Status

Development-only shadow candidate. All 89 historical runs are development data; no prospective validation has occurred and enforcement is prohibited.

## Leakage controls

- Outer CV: 4 folds; inner model selection: 3 folds.
- Group unit: physical CLI episode ID across all batches (56 unique), not episode-run.
- Scene count: 9; every fold records its scene composition.
- Current and next candidates from one attempt remain together because the entire physical episode is held out.
- Calibration and conservative threshold selection use inner OOF predictions only; outer-fold rows remain untouched.

## Nested outer-OOF performance

| Head | AUC | AP | Brier | ECE | Trusted coverage | Trusted bad | Episode-macro AUC | Scene-macro AUC |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| bearing | 0.9135 | 0.8225 | 0.1133 | 0.0132 | 0.4964 | 0.0475 | 0.8979 | 0.8953 |
| distance | 0.9687 | 0.9407 | 0.0593 | 0.0146 | 0.5057 | 0.0207 | 0.9536 | 0.9641 |
| pose | 0.9847 | 0.9808 | 0.0389 | 0.0083 | 0.4446 | 0.0203 | 0.9817 | 0.9829 |

## Candidate evidence and final development choice

| Head | Final candidate | Logistic V1 AUC | HGB V1 AUC | Basin AUC | Basin+pair AUC | Full temporal AUC | Final threshold target met |
|---|---|---:|---:|---:|---:|---:|:---:|
| bearing | `hgb_full_temporal` | 0.8489 | 0.8634 | 0.8811 | 0.8955 | 0.9005 | YES |
| distance | `hgb_full_temporal` | 0.9387 | 0.9340 | 0.9406 | 0.9547 | 0.9643 | YES |
| pose | `hgb_full_temporal` | 0.9631 | 0.9745 | 0.9776 | 0.9815 | 0.9834 | YES |

## Final all-development OOF characterization

This section is selection-biased and is provided only to characterize the frozen candidate. The nested table above is the less-biased model-selection estimate.

| Head | AUC | AP | Brier | ECE | Conservative coverage | Empirical trusted bad | Bootstrap upper 95% | Target |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| bearing | 0.9100 | 0.8114 | 0.1152 | 0.0205 | 0.5000 | 0.0479 | 0.0678 | 0.1000 |
| distance | 0.9686 | 0.9437 | 0.0599 | 0.0136 | 0.5000 | 0.0146 | 0.0225 | 0.0500 |
| pose | 0.9839 | 0.9804 | 0.0417 | 0.0083 | 0.4500 | 0.0204 | 0.0267 | 0.0500 |

## Decision

The artifact may be used only for offline replay and future shadow integration. It must be frozen before the next batch is opened, and it cannot unlock any consumer until a new prospective batch clears the predeclared risk and runtime gates.
