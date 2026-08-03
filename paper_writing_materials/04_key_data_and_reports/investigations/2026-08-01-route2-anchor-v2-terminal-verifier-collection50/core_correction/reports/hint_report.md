# Hint-action v2 binary shadow model

This estimator answers only `override_hint` versus `do_not_override`. The separate clear-path gate remains mandatory for execution. Prospective ep1008 is not part of training.

- artifact: `/home/teambruce/navila-route2-v11-core-20260801/models/core_v1/hint_action_core_v1.joblib`
- SHA-256: `2829784b30920a9e270a5c9f7050303f7ef2488cbedabb3a8c9c4901b9e97e7e`
- selected estimator: `regularized_hgb`

| Evaluation | Balanced accuracy | Macro F1 | Average precision |
|---|---:|---:|---:|
| development OOF | 0.7184 | 0.7183 | 0.8208 |
| untouched test | 0.7374 | 0.7331 | 0.8069 |

## Advisory

- OOF threshold=0.679871, precision/recall=0.8512/0.5045;
- test precision/recall=0.8234/0.4075.
- with the independent clearance gate: OOF precision/recall=0.9270/0.7441, test=0.8442/0.5540.

## Clearance-gated execution

- OOF threshold=0.784276, streak=3, precision/recall=1.0000/0.1784;
- test precision/recall=1.0000/0.0511, false-positive weight=0.00.

Status: shadow-only.
