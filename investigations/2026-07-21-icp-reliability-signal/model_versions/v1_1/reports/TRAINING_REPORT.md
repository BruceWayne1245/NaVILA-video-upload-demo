# Reliability V1 training report

- Model version: `reliability-v1-8f2097ec5028`
- Dataset SHA-256: `8f2097ec50287d6c4b4bca71adba9563275483fee020e608e65f0d8ac6028b78`
- Split: `strict_chronological_episode_disjoint`
- Rows: `{'train': 9596, 'calibration': 2740, 'test': 52027}`
- Episode overlaps: `{'train_calibration': [], 'train_test': [], 'calibration_test': []}`

| Head | Model | Test AUC | Test AP | Test Brier | Trusted coverage | Trusted bad rate |
|---|---|---:|---:|---:|---:|---:|
| bearing | LogisticRegression | 0.8159 | 0.6873 | 0.1824 | 0.6713 | 0.2572 |
| distance | HistGradientBoostingClassifier | 0.9343 | 0.8931 | 0.1262 | 0.5091 | 0.1356 |
| pose | HistGradientBoostingClassifier | 0.9734 | 0.9717 | 0.0681 | 0.4570 | 0.1294 |

Thresholds were selected only on the episode-disjoint calibration partition; the latest batch was not used for fitting or calibration.
