# Anchor and terminal model training report

Generated from `navila-anchor-terminal-training-v1`.

## anchor_transition

- artifact: `/home/teambruce/navila-anchor-terminal-training-data-20260729/models/v1/anchor_transition_v1.joblib`
- SHA-256: `4d37f9bcb341f093d4cdc87e92c041db7d582a912acdb629963039cf7b27dc55`
- features: 411
- temperature: 1.600
- training iterations: 120

| Split | Rows | Balanced accuracy | Macro F1 | Log loss |
|---|---:|---:|---:|---:|
| train | 58368 | 0.9830 | 0.9829 | 0.1736 |
| validation | 12865 | 0.7346 | 0.7155 | 0.8813 |
| test | 16019 | 0.7710 | 0.7708 | 0.6309 |

## terminal_decision

- artifact: `/home/teambruce/navila-anchor-terminal-training-data-20260729/models/v1/terminal_decision_v1.joblib`
- SHA-256: `1b7bbc2fab5211c9b6422c70103735b89a8f3d75fa7c23beacfb8ea3b64cab84`
- features: 424
- temperature: 1.200
- training iterations: 58

| Split | Rows | Balanced accuracy | Macro F1 | Log loss |
|---|---:|---:|---:|---:|
| train | 5755 | 0.9880 | 0.9803 | 0.0480 |
| validation | 1103 | 0.6943 | 0.7165 | 0.3676 |
| test | 1588 | 0.7368 | 0.7534 | 0.1366 |

Decision-policy calibration:

- `arrived_zero_false_positive`: threshold=0.753178, validation false positives=0, recall=0.3465
- `far_zero_false_positive_on_nonfar`: threshold=0.975345, validation false positives=0, recall=0.4926

## Terminal zero-false-positive policy evaluation

| Split | Arrived false positives | Arrived-vs-far false positives | Arrived recall | Far false positives | Far recall | Uncertain |
|---|---:|---:|---:|---:|---:|---:|
| validation | 0 | 0 | 0.3465 | 0 | 0.4926 | 0.5748 |
| test | 16 | 13 | 0.4943 | 0 | 0.6741 | 0.3577 |
