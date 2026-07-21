# Reliability V1 and V1.1 — complete work summary

## 1. Intended service, inputs, and outputs

The model is a selective reliability layer for sequential-pair ICP. It does
not estimate navigation actions and it does not replace ICP. Its position in
the dataflow is:

```text
anchor/current geometry -> ICP candidates -> reliability probabilities
                                      -> shadow recommendations
                                      -> future reviewed consumers only
```

One scored row is one ICP candidate (`current` or `next`) from one
relocalization attempt. The three labels are:

- `bearing_bad`: absolute bearing error is greater than 30 degrees;
- `distance_bad`: absolute anchor-distance error is greater than 0.5 m;
- `pose_bad`: either of the above is true.

The output contract is three calibrated bad-probabilities, a trusted/not-trusted
decision for each head, schema/OOD status, and shadow-only temporal
recommendations. A trusted decision means only that the row passed that head's
frozen risk threshold. It is not a navigation command and it does not mean
zero-error pose.

The expected eventual consumers are ordered by risk:

1. logging and diagnosis;
2. hint confidence or hint suppression;
3. stop-authority deferral;
4. promotion/quarantine/current-eviction recommendations;
5. only after separate prospective evidence, an individually reviewed
   enforcement experiment.

## 2. Work completed

The original eight-step effort is complete through offline V1.1 development:

1. rebuilt a labeled, episode-aware dataset from three historical batches;
2. trained and calibrated a three-head V1 bundle;
3. replayed 13 pinned-current and 8 missed-stop cases;
4. integrated V1 into a completely separate candidate runtime in shadow mode;
5. exported a dependency-free portable V1 artifact and checked sklearn parity;
6. ran an isolated live smoke and a group-aware offline validity audit;
7. diagnosed V1 calibration transfer, role, scene, and feature shift;
8. built and nested-evaluated V1.1 with basin, pair, and causal temporal inputs.

No authoritative live navigation file was changed by this model work.

## 3. Shared data foundation

- 91,003 labeled candidate readings;
- 89 usable episode-runs from 183 discovered runs;
- 56 unique physical CLI episode IDs after grouping repeated IDs across
  batches;
- 9 scenes;
- 100/100 independently reloaded raw-label checks passed;
- 89/89 attempt schedules passed.

The usable-run filter is a real limitation: missing and corrupt historical logs
can create selection bias that an episode bootstrap cannot remove.

## 4. Reliability V1

### Design

V1 uses 19 scalar ICP/geometry diagnostics plus deterministic one-hot encodings
of `match_class` and `icp_ambiguity`. It deliberately excludes episode, batch,
scene, ground truth, downstream outcome, current/next disagreement, and future
observations.

- bearing head: regularized logistic regression;
- distance and pose heads: histogram gradient boosting;
- calibration: weighted monotonic Platt calibration on a separate middle
  partition;
- evaluation: chronological, episode-disjoint latest-batch test.

### Frozen test result

| Head | AUC | AP | Brier | Trusted coverage | Trusted bad rate | Target |
|---|---:|---:|---:|---:|---:|---:|
| bearing | 0.8159 | 0.6873 | 0.1824 | 67.13% | 25.72% | <=10% |
| distance | 0.9343 | 0.8931 | 0.1262 | 50.91% | 13.56% | <=5% |
| pose | 0.9734 | 0.9717 | 0.0681 | 45.70% | 12.94% | <=5% |

Ranking remained useful, but all trusted-set safety gates failed. V1 detected
all 13 known pinned-current cases with zero false evictions in 113 audited
healthy segments, but its replay policy was selected after viewing historical
cases and recovered 0/8 missed-stop cases. It therefore cannot own any
consumer decision.

### Runtime evidence

- portable JSON matched the sklearn bundle on 939 sampled rows;
- maximum absolute probability difference: `6.66e-16`;
- trusted-decision mismatches: 0;
- one isolated shortened episode produced 402 candidate records;
- mean latency: 1.139 ms/candidate;
- enforced actions: 0.

That run was a plumbing/latency smoke, not a full episode benchmark.

## 5. Why V1 failed

The dominant failure was threshold transfer, not total absence of ranking
signal. Calibration used only 3 episodes from 2 scenes. On the historical test
partition, the model systematically underestimated risk:

| Head | Observed bad rate | Mean predicted risk | Prediction bias |
|---|---:|---:|---:|
| bearing | 39.92% | 33.92% | -5.99 points |
| distance | 49.77% | 35.56% | -14.21 points |
| pose | 57.32% | 49.60% | -7.72 points |

Thresholds were highly unstable when estimated from single calibration
episodes or two-episode leave-one-out subsets. `next` readings were also
consistently worse than `current` readings. The largest calibration-to-test
feature shifts included corridor degeneracy, best/second score ratio, anchor Z
span, localizability, estimated distance, and residual statistics.

This diagnosis motivated episode-grouped nested selection, richer ambiguity
features, current/next pair consistency, causal histories, and conservative
cluster-aware thresholding.

## 6. Reliability V1.1

### Input and leakage controls

V1.1 expands to 249 numeric features:

- the complete top-4 ICP basin fields and basin spread/gap summaries;
- yaw-curve, Scan Context, and extended localizability fields;
- same-attempt `current`/`next` pair differences;
- strictly causal histories over 4/8/16/32 readings, containing current and
  past only.

Temporal state is grouped by episode and anchor. Repeated physical episode IDs
across different batches are kept in the same fold. Current and next candidates
from an attempt cannot cross folds. Batch/episode/scene identity, labels,
ground-truth errors/outcomes, and anchor-progress identity proxies are absent
from model inputs.

### Evaluation design

- 4 outer folds x 3 inner folds;
- `StratifiedGroupKFold` grouped by 56 physical episode IDs;
- candidate selection and Platt calibration use inner OOF predictions only;
- outer rows remain untouched until evaluation;
- trusted thresholds use a one-sided 95% physical-episode-cluster bootstrap
  upper risk bound;
- all four outer folds selected `hgb_full_temporal` for all three heads.

### Same-fold ablation evidence

This is the fairest evidence for *why* V1.1 improved:

| Candidate | Bearing AUC | Distance AUC | Pose AUC |
|---|---:|---:|---:|
| Logistic + V1 features | 0.8489 | 0.9387 | 0.9631 |
| HGB + V1 features | 0.8634 | 0.9340 | 0.9745 |
| HGB + full basins | 0.8811 | 0.9406 | 0.9776 |
| HGB + basins + pair | 0.8955 | 0.9547 | 0.9815 |
| HGB + basins + pair + temporal | **0.9005** | **0.9643** | **0.9834** |

Changing model family alone was not a consistent win: HGB slightly reduced
distance AUC with V1 features. The repeatable gains came from representing the
multi-basin ambiguity, comparing current and next jointly, and adding causal
temporal consistency.

### Nested outer-OOF result

| Head | AUC | AP | Brier | ECE | Trusted coverage | Trusted bad | Episode-macro AUC | Scene-macro AUC |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| bearing | 0.9135 | 0.8225 | 0.1133 | 0.0132 | 49.64% | 4.75% | 0.8979 | 0.8953 |
| distance | 0.9687 | 0.9407 | 0.0593 | 0.0146 | 50.57% | 2.07% | 0.9536 | 0.9641 |
| pose | 0.9847 | 0.9808 | 0.0389 | 0.0083 | 44.46% | 2.03% | 0.9817 | 0.9829 |

On historical OOF rows, V1.1 therefore accepts roughly half the readings per
head and 95-98% of those accepted rows satisfy that head's label threshold.
These are **separate per-head operating points**. The joint coverage and joint
risk when all three heads must pass have not yet been reported and cannot be
inferred by multiplying or averaging the table.

The final all-development characterization is selection-biased and is not the
primary estimate. Its cluster-bootstrap upper 95% trusted-risk bounds were
6.78% bearing, 2.25% distance, and 2.67% pose at 50%, 50%, and 45% coverage.

## 7. What can and cannot be concluded

Supported by historical evidence:

- the historical logs contain a strong reliability signal;
- the ambiguity landscape contains information lost by a single best ICP fit;
- current/next should be scored jointly rather than as unrelated rows;
- short causal history adds useful information, especially for distance;
- bearing remains the hardest head;
- no obvious identity, ground-truth, future-state, or repeated-episode leakage
  was found by the implemented checks.

Not yet supported:

- that V1.1 will reproduce these numbers on new episodes;
- that it generalizes to unseen scenes or a changed capture/runtime pipeline;
- that per-head acceptance implies a safe joint pose decision;
- that accepting/rejecting rows improves full navigation outcomes;
- that any consumer may be enabled.

V1 uses a fixed historical test partition, whereas V1.1 uses nested OOF across
all historical runs. Their headline numbers are not a direct prospective A/B.
The same-fold ablation table is the valid causal evidence for the V1.1 feature
direction; a new frozen prospective batch is required for the final claim.
