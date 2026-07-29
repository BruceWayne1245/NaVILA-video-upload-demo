# Terminal v2 shadow baseline

Absolute anchor-index features are removed. Boundary and arrived-without-stop rows receive extra training weight. Any arrived proposal still requires a validation-frozen consecutive sequence.

- selected estimator: `regularized_hgb`
- artifact: `/home/teambruce/navila-anchor-terminal-training-data-20260729/models/v2/terminal_decision_v2.joblib`
- artifact SHA-256: `00f805703df25d5ddf9fd26f6b98babb61c7b2153c7e3440964dfed64e6ad6ef`
- features: 373

| Split | Balanced accuracy | Macro F1 | Log loss |
|---|---:|---:|---:|
| validation | 0.7206 | 0.7147 | 0.4431 |
| test | 0.6438 | 0.6221 | 0.2338 |

## Consecutive arrived confirmation

- validation: threshold=0.5100, streak=3, arrived recall=0.6687, true-far false-arrived=0, boundary forced-arrived=0.
- test: threshold=0.5100, streak=3, arrived recall=0.1159, true-far false-arrived=6, boundary forced-arrived=1.

The threshold/streak are selected on validation only and reused unchanged on test. Status: shadow-only; no stop authority.
