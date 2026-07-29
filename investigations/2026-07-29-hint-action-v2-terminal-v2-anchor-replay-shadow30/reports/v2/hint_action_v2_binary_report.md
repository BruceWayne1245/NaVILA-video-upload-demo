# Hint-action v2 binary shadow model

This estimator answers only `override_hint` versus `do_not_override`. The separate clear-path gate remains mandatory for execution. Prospective ep1008 is not part of training.

- artifact: `/home/teambruce/navila-anchor-terminal-training-data-20260729/models/v2/hint_action_decision_v2_binary.joblib`
- SHA-256: `567e24aef5036e3310a36a8333ab8cc40ee467a293506973fa544fb1baa49603`
- selected estimator: `regularized_hgb`

| Evaluation | Balanced accuracy | Macro F1 | Average precision |
|---|---:|---:|---:|
| development OOF | 0.7169 | 0.7159 | 0.7818 |
| untouched test | 0.6790 | 0.6781 | 0.7872 |

## Advisory

- OOF threshold=0.706886, precision/recall=0.8514/0.3425;
- test precision/recall=0.8410/0.3723.
- with the independent clearance gate: OOF precision/recall=0.9257/0.6396, test=0.8372/0.6136.

## Clearance-gated execution

- OOF threshold=0.798865, streak=2, precision/recall=1.0000/0.1568;
- test precision/recall=1.0000/0.1335, false-positive weight=0.00.

Status: shadow-only.
