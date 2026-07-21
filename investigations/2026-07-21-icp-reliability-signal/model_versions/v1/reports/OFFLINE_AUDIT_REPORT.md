# Reliability V1 offline audit

## Verdict

The frozen V1 artifact retains useful ranking power, but its trusted-set error rates remain above the declared safety targets. It stays shadow-only.

## Provenance and label audit

- Model: `reliability-v1-8f2097ec5028`
- Dataset SHA-256: `8f2097ec50287d6c4b4bca71adba9563275483fee020e608e65f0d8ac6028b78`
- Artifact SHA-256: `3fc7c2ebc6f2732ab787c137c31d1e54b2883c658858daafb5a82a78eef0eab2`
- Raw labels rechecked: **100/100 passed** across 64 episode-runs and 8 scenes.
- Attempt schedules checked in all usable runs: **89/89 passed**.
- Human-readable audit rows: `/home/teambruce/navila-reliability-v1/reports/label_audit_samples.csv` (`6fd7221c69bb`).

The raw audit reloads each measurement and trajectory, traces the runtime schedule (attempt 1 at the first return row; later attempts at interval multiples), recomputes body-frame ground truth and both error labels, and compares them with the frozen CSV.

## Test composition and leakage scope

- Test rows: 52027; test episodes: 42; test scenes: 8.
- Episode overlaps: `{'train_calibration': [], 'train_test': [], 'calibration_test': []}`.
- Scene overlaps: `{'train_calibration': ['QUCTc6BB5sX'], 'train_test': ['2azQ1b91cZZ', 'EU6Fwq7SyZv', 'QUCTc6BB5sX', 'TbHJrupSAjP', 'x8F5xyUWy9e', 'zsNo4HB9uLZ'], 'calibration_test': ['QUCTc6BB5sX', 'X7HyMhZNoso']}`.

Episode identities are disjoint, but scenes overlap across partitions. This is a same-benchmark, seen-scene evaluation—not evidence of unseen-scene generalization.

## Frozen-model test metrics

All pooled values use episode-balanced weights. Confidence intervals resample whole episodes, never individual readings.

| Head | AUC (95% CI) | AP (95% CI) | Brier (95% CI) | Trusted coverage (95% CI) | Trusted bad rate (95% CI) | Target |
|---|---:|---:|---:|---:|---:|---:|
| bearing | 0.8159 [0.7693, 0.8510] | 0.6873 [0.6169, 0.7429] | 0.1824 [0.1581, 0.2103] | 0.6713 [0.5977, 0.7419] | 0.2572 [0.2001, 0.3215] | 0.1000 |
| distance | 0.9343 [0.9087, 0.9529] | 0.8931 [0.8495, 0.9279] | 0.1262 [0.1046, 0.1462] | 0.5091 [0.4125, 0.6044] | 0.1356 [0.0890, 0.1917] | 0.0500 |
| pose | 0.9734 [0.9644, 0.9807] | 0.9717 [0.9559, 0.9823] | 0.0681 [0.0538, 0.0860] | 0.4570 [0.3620, 0.5565] | 0.1294 [0.0861, 0.1838] | 0.0500 |

## Episode and scene macro view

| Head | Episode-macro AUC | Episode-macro trusted bad | Scene-macro AUC | Scene-macro trusted bad |
|---|---:|---:|---:|---:|
| bearing | 0.7720 (42/42 valid) | 0.2882 | 0.7754 (8/8 valid) | 0.2948 |
| distance | 0.8978 (42/42 valid) | 0.1853 | 0.9087 (8/8 valid) | 0.2056 |
| pose | 0.9638 (42/42 valid) | 0.1503 | 0.9699 (8/8 valid) | 0.1506 |

## Simple ICP baseline

For each head, one scalar ICP signal is selected by calibration AUC only. Its trusted threshold is then selected on the same calibration partition using the same bad-rate target. The test batch is untouched by both choices.

| Head | Calibration-selected signal | Model test AUC | Baseline test AUC | Model Brier | Baseline Brier | Model trusted bad | Baseline trusted bad |
|---|---|---:|---:|---:|---:|---:|---:|
| bearing | `negative_confidence` | 0.8159 | 0.7943 | 0.1824 | 0.1682 | 0.2572 | 0.2392 |
| distance | `negative_confidence` | 0.9343 | 0.9137 | 0.1262 | 0.1916 | 0.1356 | 0.2496 |
| pose | `negative_confidence` | 0.9734 | 0.9420 | 0.0681 | 0.1021 | 0.1294 | 0.2191 |

## Risk–coverage conclusion

| Head | Target bad rate | Largest 5%-grid coverage meeting target | Deployed coverage | Deployed bad rate |
|---|---:|---:|---:|---:|
| bearing | 0.1000 | 0.4000 | 0.6713 | 0.2572 |
| distance | 0.0500 | 0.4000 | 0.5091 | 0.1356 |
| pose | 0.0500 | 0.3500 | 0.4570 | 0.1294 |

The numeric curves are in `reports/risk_coverage.csv` and the plot is in `reports/risk_coverage.png`. Low predicted risk does isolate a much safer subset, but the calibration-selected deployed thresholds accept too much. The grid values above are post-hoc test diagnostics and must not be reused as deployment thresholds.

## Remaining validity limits

- Only 89 of 183 discovered runs were usable; missing/corrupt logs can create selection bias that bootstrap intervals do not capture.
- Calibration contains 3 episodes and 2 scenes, so threshold uncertainty is substantial.
- Episode-cluster intervals quantify sampling variability across available episode-runs; scene-cluster intervals are in JSON, but only eight test scenes make them coarse.
- The raw audit validates the code-derived schedule and sampled labels, but old logs lack an independent relocalization timestamp. Future capture should persist the attempt step directly.
- The scalar baseline is selected from a small candidate family on calibration data; it is a sanity comparator, not a production rule.

## Decision

Keep all enforcement switches off. Use the next unchanged 100-episode run as a prospective shadow/data-collection batch after the capture canary passes.
