# Reliability V1 calibration and domain-shift diagnosis

## Main finding

V1's primary failure is threshold transfer: ranking remains useful on the latest batch, while the three-episode calibration partition systematically understates the risk of the accepted test subset. Feature and role/scene drift are secondary contributors.

## Partition calibration

| Split | Head | Observed bad | Mean predicted | Bias (predicted − observed) | ECE | Brier | Trusted coverage | Trusted bad |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| train | bearing | 0.2991 | 0.2486 | -0.0504 | 0.0537 | 0.0917 | 0.7510 | 0.1256 |
| train | distance | 0.3075 | 0.2698 | -0.0378 | 0.0602 | 0.0157 | 0.6925 | 0.0002 |
| train | pose | 0.3929 | 0.3574 | -0.0355 | 0.0505 | 0.0103 | 0.6099 | 0.0046 |
| calibration | bearing | 0.2887 | 0.2887 | 0.0000 | 0.0190 | 0.1028 | 0.7093 | 0.1000 |
| calibration | distance | 0.1922 | 0.1922 | 0.0000 | 0.0221 | 0.0864 | 0.7410 | 0.0497 |
| calibration | pose | 0.3349 | 0.3349 | -0.0000 | 0.0250 | 0.0624 | 0.6466 | 0.0495 |
| test | bearing | 0.3992 | 0.3392 | -0.0599 | 0.0950 | 0.1824 | 0.6713 | 0.2572 |
| test | distance | 0.4977 | 0.3556 | -0.1421 | 0.1429 | 0.1262 | 0.5091 | 0.1356 |
| test | pose | 0.5732 | 0.4960 | -0.0772 | 0.0798 | 0.0681 | 0.4570 | 0.1294 |

## Test role breakdown

| Role | Head | Rows | AUC | Trusted coverage | Trusted bad | ECE |
|---|---|---:|---:|---:|---:|---:|
| current | bearing | 26291 | 0.8291 | 0.7089 | 0.2177 | 0.0699 |
| current | distance | 26291 | 0.9552 | 0.5519 | 0.1033 | 0.1343 |
| current | pose | 26291 | 0.9803 | 0.5013 | 0.1181 | 0.0789 |
| next | bearing | 25736 | 0.8005 | 0.6328 | 0.3023 | 0.1205 |
| next | distance | 25736 | 0.9084 | 0.4654 | 0.1747 | 0.1514 |
| next | pose | 25736 | 0.9649 | 0.4118 | 0.1434 | 0.0787 |

## Threshold instability

The table below gives the range produced when thresholds are estimated from each single calibration episode or each two-episode leave-one-out subset, then replayed on the already-seen historical test batch.

| Head | Threshold range | Test coverage range | Test trusted-bad range |
|---|---:|---:|---:|
| bearing | 0.3761–0.5599 | 0.5706–0.7097 | 0.2060–0.2733 |
| distance | 0.1885–0.5159 | 0.4380–0.6216 | 0.0407–0.2593 |
| pose | 0.3783–0.6504 | 0.4375–0.5042 | 0.1006–0.1910 |

## Largest calibration-to-test feature shifts

| Rank | Feature | PSI | Calibration missing | Test missing |
|---:|---|---:|---:|---:|
| 1 | `corridor_degeneracy_ratio` | 0.4293 | 0.0000 | 0.0000 |
| 2 | `icp_best_to_second_score_ratio` | 0.4074 | 0.0000 | 0.0000 |
| 3 | `anchor_z_span_m` | 0.3820 | 0.0000 | 0.0000 |
| 4 | `localizability_min_normalized_eigenvalue` | 0.2908 | 0.0000 | 0.0000 |
| 5 | `localizability_condition_number` | 0.2908 | 0.0000 | 0.0000 |
| 6 | `estimated_distance_to_anchor_m` | 0.2552 | 0.0000 | 0.0000 |
| 7 | `median_residual_m` | 0.2215 | 0.0000 | 0.0000 |
| 8 | `mean_residual_m` | 0.1903 | 0.0000 | 0.0000 |
| 9 | `localizability_min_eigenvalue` | 0.1867 | 0.0000 | 0.0000 |
| 10 | `icp_near_tie_basin_count` | 0.1769 | 0.0000 | 0.0000 |

## Implications for V1.1

1. Treat all three historical batches as development data; the old latest batch is no longer an untouched test set.
2. Produce out-of-fold probabilities with episode-grouped, scene-aware folds before fitting any calibrator or threshold.
3. Add full basin and causal temporal features, with current/next candidates from one attempt kept in the same fold.
4. Select thresholds using cluster-aware upper risk bounds and minimum coverage, not a three-episode empirical prefix.
5. Freeze V1.1 before opening results from the next prospective batch.
