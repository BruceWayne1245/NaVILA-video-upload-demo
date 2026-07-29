# Hint-action v2 follow-up

## Failure analysis

The two Hint v1 false recommendations in prospective ep1008 occur at steps
4001 and 4251. Step 4001 has `clear_path=false`; step 4251 combines a
near-behind route bearing with falling confidence. This showed that model
direction quality and executable action safety must be reported separately.

Prospective ep1008 remains an untouched acceptance set. V2 training instead
upweights analogous development hard negatives and adds causal circular
bearing, query-gap reset, target/direction stability, and motion-response
features. Absolute anchor indices are removed.

## Model comparison

Metrics are weighted. Prospective values pool the four scoreable episodes;
ep430 failed outbound.

| Policy | Untouched test precision | Untouched test recall | Prospective precision | Prospective recall |
|---|---:|---:|---:|---:|
| historical gate | 0.6466 | 0.3905 | 0.9130 | 0.3000 |
| Hint v1 route recommendation | 0.7464 | 0.4711 | 0.9000 | 0.6429 |
| Hint v2 binary advisory | 0.8410 | 0.3723 | 0.9655 | 0.4000 |
| Hint v2 binary + clearance | 0.8372 | 0.6136 | 1.0000 | 0.3810 |

The clearance-gated rows have a different denominator: recall is evaluated
only where current clearance evidence allows execution.

The strict v2 execution point has zero false-positive weight on development
OOF and untouched test, but makes no prospective interventions. It is safe by
inactivity and therefore fails liveness.

Prospective clearance availability is itself a major liveness bottleneck:
weighted rows split into 11.5 clear, 13.0 occupied, and 20.5 unavailable.
Occupied rows must remain blocked. The next controller iteration should turn
`clearance unavailable` into a bounded scan/recheck state instead of treating
it as a permanent hint veto.

## Decision

- Keep Hint v1 as the higher-recall shadow comparator.
- Use Hint v2 binary as the more conservative advisory comparator.
- Keep clear-path as an independent mandatory execution gate.
- Do not activate either model until a scene-held-out policy simultaneously
  preserves intervention recall and eliminates high-cost false override.

Artifacts:

- `models/v2/hint_action_decision_v2_binary.joblib`
- `reports/v2/hint_action_v2_binary_report.json`
- `reports/v2/prospective5_hint_v2_binary.json`
