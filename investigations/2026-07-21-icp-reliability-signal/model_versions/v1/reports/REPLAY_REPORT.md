# Reliability V1 counterfactual replay

- Model: `reliability-v1-8f2097ec5028`
- Batch: `canonical_report_next_stopgate_100ep_20260720`
- Pinned cases detected: **13/13**
- Healthy current false evictions: **0/113**
- Missed-stop cases found: **8**
- Counterfactual stop recoveries: **0**
- False-stop streak episodes: **0**

## Pinned-current cases

| Episode | Anchor | Readings | Actual bad rate | High-risk rate | First eviction recommendation |
|---:|---:|---:|---:|---:|---:|
| 5 | 11 | 302 | 1.000 | 0.957 | 285 |
| 20 | 8 | 181 | 0.928 | 0.740 | 24 |
| 319 | 4 | 558 | 1.000 | 0.683 | 560 |
| 367 | 11 | 914 | 0.766 | 0.748 | 331 |
| 498 | 5 | 882 | 0.934 | 0.870 | 137 |
| 500 | 10 | 636 | 1.000 | 1.000 | 375 |
| 669 | 4 | 843 | 0.802 | 0.737 | 344 |
| 680 | 6 | 728 | 0.967 | 0.760 | 390 |
| 813 | 6 | 343 | 0.793 | 0.790 | 82 |
| 889 | 9 | 475 | 1.000 | 1.000 | 349 |
| 994 | 6 | 781 | 0.931 | 0.951 | 246 |
| 1038 | 4 | 803 | 0.786 | 0.790 | 382 |
| 653 | 10 | 833 | 0.804 | 0.733 | 379 |

## Missed-stop cases

| Episode | Final true distance | Recovery attempt | Recovered |
|---:|---:|---:|:---:|
| 5 | 0.000 m | n/a | False |
| 20 | 0.000 m | n/a | False |
| 89 | 2.655 m | n/a | False |
| 382 | 1.693 m | n/a | False |
| 498 | 0.000 m | n/a | False |
| 537 | 2.423 m | n/a | False |
| 680 | 0.286 m | n/a | False |
| 889 | 1.622 m | n/a | False |

This is an offline counterfactual, not a claim of live navigation success. It does not model a changed robot trajectory after an earlier decision.
