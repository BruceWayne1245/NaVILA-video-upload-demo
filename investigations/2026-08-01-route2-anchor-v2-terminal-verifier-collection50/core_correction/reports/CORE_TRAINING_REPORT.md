# Route 2 Core V1 retraining report

Date: 2026-08-01

## Result

The old Anchor, Terminal, and Hint datasets were re-vectorized through a
head-specific Reliability V1.1 firewall and all three downstream models were
retrained on CPU. The immutable source captures were not rewritten. “Cleaning”
means that forbidden columns are removed before fitting and the resulting
feature names are frozen inside each artifact.

| Model | Required V1.1 head | Old test metric | Core V1 test metric | Change | Raw ICP quality proxies | Wrong-head V1.1 features |
|---|---|---:|---:|---:|---:|---:|
| Anchor Transition | pose | BA 0.770984 | BA 0.783471 | +0.012487 | 0 | 0 |
| Terminal Decision | distance | BA 0.741555 | BA 0.774424 | +0.032869 | 0 | 0 |
| Hint Action | bearing | BA 0.679023, AP 0.787164 | BA 0.737399, AP 0.806911 | +0.058376 BA, +0.019747 AP | 0 | 0 |

The split remains scene-disjoint: seven development scenes, `EU6Fwq7SyZv`
validation, and `zsNo4HB9uLZ` test. No GPU was used. The training environment
was Python 3.10.20, scikit-learn 1.7.2, and NumPy 1.26.4.

## Safety interpretation

Classifier accuracy improved for Terminal, but its locked-test safe sequence
policy produced zero false arrivals and also zero arrived recall. The old model
had 0.269 arrived recall but five true-far false arrivals. Core V1 therefore
remains shadow-only: the result is safer, but not useful enough to control
stopping. The new development cohort is intentionally optimized to collect
reachable return trajectories with near-home, boundary, far, and false-near
sequences for the next Terminal iteration.

Hint Core V1's clearance-gated execution policy had test precision 1.0 and
recall 0.051. It also remains shadow-only. Anchor Core V1 remains a bounded
shadow observer. These statuses do not disable Reliability V1.1: the V1.1 core
consumer itself is active and owns promotion through pose, hints through
bearing, and stopping through distance.

## Frozen artifacts

| Artifact | SHA256 | Feature count | Matching V1.1 features |
|---|---|---:|---:|
| `anchor_transition_core_v1.joblib` | `cf920f45852c3ed7e0d15068c7e67a943bb01372ce9d922c7dfaa7531f73fa37` | 270 | 57 pose |
| `terminal_decision_core_v1.joblib` | `49358cb7b53397469792718fc33765f87617b009290727c0cfac23eae0d1fa5b` | 275 | 96 distance |
| `hint_action_core_v1.joblib` | `2829784b30920a9e270a5c9f7050303f7ef2488cbedabb3a8c9c4901b9e97e7e` | 192 | 38 bearing |

Machine-readable provenance, training-source hashes, and old/new comparisons
are in `core_training_audit.json`. Per-model reports preserve confusion
matrices, scene metrics, thresholds, and sequence-policy outcomes.

## Data handling contract

- Raw source captures remain immutable audit evidence.
- Raw ICP confidence, residual, inlier, overlap, basin, ambiguity,
  localizability, scan-context, yaw-curve, and legacy-U reliability proxies
  cannot enter a Core V1 model.
- Anchor can consume only pose-head V1.1 reliability features; Terminal only
  distance-head features; Hint only bearing-head features.
- Development cohort outcomes may be used in a future fit.
- Locked validation cohort rows and outcomes may never enter training or
  threshold selection.
