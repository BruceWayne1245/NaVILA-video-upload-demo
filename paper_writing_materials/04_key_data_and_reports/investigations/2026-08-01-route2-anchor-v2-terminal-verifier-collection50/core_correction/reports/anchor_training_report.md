# Anchor and terminal model training report

Generated from `navila-anchor-terminal-training-v1`.

## anchor_transition

- artifact: `/home/teambruce/navila-route2-v11-core-20260801/models/core_v1/anchor_transition_core_v1.joblib`
- SHA-256: `cf920f45852c3ed7e0d15068c7e67a943bb01372ce9d922c7dfaa7531f73fa37`
- features: 270
- temperature: 1.350
- training iterations: 120

| Split | Rows | Balanced accuracy | Macro F1 | Log loss |
|---|---:|---:|---:|---:|
| train | 58368 | 0.9727 | 0.9726 | 0.1723 |
| validation | 12865 | 0.7528 | 0.7466 | 0.7494 |
| test | 16019 | 0.7835 | 0.7780 | 0.6517 |
