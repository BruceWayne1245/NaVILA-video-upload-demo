# Terminal v2 robust scene-held-out baseline

The estimator and arrived confirmation policy are calibrated from leave-one-scene-out predictions over every development scene. The test scene is never used for fitting, temperature selection, threshold selection, or streak selection.

- artifact: `/home/teambruce/navila-route2-v11-core-20260801/models/core_v1/terminal_decision_core_v1.joblib`
- artifact SHA-256: `49358cb7b53397469792718fc33765f87617b009290727c0cfac23eae0d1fa5b`
- development scenes: 7
- test scenes: 1

| Evaluation | Balanced accuracy | Macro F1 | Log loss |
|---|---:|---:|---:|
| development OOF | 0.7281 | 0.6713 | 0.3656 |
| untouched test | 0.7744 | 0.7043 | 0.2000 |

## Sequence safety

- OOF-selected threshold=0.9386, streak=10, arrived recall=0.2317, true-far false-arrived=0, boundary forced-arrived=0.
- Untouched test: arrived recall=0.0000, true-far false-arrived=0, boundary forced-arrived=0.

Status: shadow-only. A zero false-arrived result with negligible arrived recall is still not an activation pass.
