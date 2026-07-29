# Hint-action v2 robust shadow model

The estimator predicts movement-direction preference. A separate deterministic clear-path gate decides whether a recommendation is executable. The untouched test scene and prospective 5ep are not used for fitting or policy selection.

- artifact: `/home/teambruce/navila-anchor-terminal-training-data-20260729/models/v2/hint_action_decision_v2_robust.joblib`
- artifact SHA-256: `21fc7d0a28a5c66c531480abcbdd79cfdcf5af5f943eca188fd24be00576df23`
- features: 364
- hard negatives in development fit: 620

| Evaluation | Balanced accuracy | Macro F1 | ROC AUC |
|---|---:|---:|---:|
| development OOF | 0.5287 | 0.5299 | 0.7271 |
| untouched test | 0.4872 | 0.4795 | 0.7167 |

## Frozen execution policy

- threshold=0.772780, same-kind streak=2, same-target streak=1;
- development OOF executable precision/recall=1.0000/0.1532, false-positive weight=0.00;
- untouched test executable precision/recall=1.0000/0.0852, false-positive weight=0.00;
- untouched test route-recommendation precision/recall before clearance=1.0000/0.0522.

## Frozen advisory policy

- threshold=0.895150; development OOF precision/recall=0.9286/0.0075;
- untouched test precision/recall=0.0000/0.0000.

Status: shadow-only.
