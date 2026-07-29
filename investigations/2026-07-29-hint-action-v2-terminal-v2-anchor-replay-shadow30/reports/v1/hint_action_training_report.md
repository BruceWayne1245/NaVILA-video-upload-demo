# Dedicated hint-action model — first shadow baseline

This model decides only whether to prefer a conflicting movement hint over the VLM movement direction. Stop authority stays with the terminal model/state machine; collision clearance remains a hard safety gate.

- artifact: `/home/teambruce/navila-anchor-terminal-training-data-20260729/models/v1/hint_action_decision_v1.joblib`
- artifact SHA-256: `1851c727534f943396c7f74ec6b47f8da0695753cb0edc17fd957cdc532f03ca`
- dataset SHA-256: `9d2ab50076b0e8dadf99cca6f27ef188b43d160f013f45be2fd1485fafd28e6f`
- features: 380
- temperature: 1.400

## Three-class quality

| Split | Rows | Balanced accuracy | Macro F1 | Log loss |
|---|---:|---:|---:|---:|
| train | 1982 | 0.9505 | 0.9523 | 0.2788 |
| validation | 443 | 0.5097 | 0.5034 | 0.8396 |
| test | 589 | 0.4869 | 0.4808 | 0.8351 |

## Intervention comparison

| Split/policy | Precision | Recall | Coverage |
|---|---:|---:|---:|
| validation historical gate | 0.7491 | 0.2942 | 0.2226 |
| validation model `precision_0p90` | 0.9006 | 0.5628 | 0.3542 |
| validation model `precision_0p95` | 0.9501 | 0.4885 | 0.2915 |
| validation model `zero_validation_false_positive` | 1.0000 | 0.2227 | 0.1262 |
| test historical gate | 0.6466 | 0.3905 | 0.3188 |
| test model `precision_0p90` | 0.7464 | 0.4711 | 0.3331 |
| test model `precision_0p95` | 0.7640 | 0.3859 | 0.2666 |
| test model `zero_validation_false_positive` | 0.9231 | 0.1362 | 0.0779 |

Thresholds are selected on validation only. Test entries reuse the frozen validation thresholds; no test-set tuning is performed.

Status: shadow-only. This artifact is not wired into the active evaluator.
