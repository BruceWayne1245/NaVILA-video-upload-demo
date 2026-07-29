# Terminal v2 robust scene-held-out baseline

The estimator and arrived confirmation policy are calibrated from leave-one-scene-out predictions over every development scene. The test scene is never used for fitting, temperature selection, threshold selection, or streak selection.

- artifact: `/home/teambruce/navila-anchor-terminal-training-data-20260729/models/v2/terminal_decision_v2_robust.joblib`
- artifact SHA-256: `f033696bf632134c48edf3ce1734850833c98a93bfdadc7173780ef5ebef6bbb`
- development scenes: 7
- test scenes: 1

| Evaluation | Balanced accuracy | Macro F1 | Log loss |
|---|---:|---:|---:|
| development OOF | 0.7347 | 0.6817 | 0.3723 |
| untouched test | 0.7416 | 0.7095 | 0.1687 |

## Sequence safety

- OOF-selected threshold=0.7133, streak=4, arrived recall=0.3387, true-far false-arrived=0, boundary forced-arrived=0.
- Untouched test: arrived recall=0.2692, true-far false-arrived=5, boundary forced-arrived=0.

Status: shadow-only. A zero false-arrived result with negligible arrived recall is still not an activation pass.
