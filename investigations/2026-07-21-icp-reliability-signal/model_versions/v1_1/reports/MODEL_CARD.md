# Reliability V1 model card

- Training artifact: `artifacts/reliability_v1.pkl`
- Live shadow artifact: `artifacts/reliability_v1_portable.json` (standard-library runtime; no sklearn dependency)
- Model version: `reliability-v1-8f2097ec5028`
- Schema: `reliability-v1.0`
- Intended use: shadow scoring of one sequential-pair ICP reading.
- Prohibited use: direct navigation action, stop, promotion, quarantine, or
  current-anchor eviction without a later prospective approval.

## Heads

- Bearing error >30°: regularized logistic regression.
- Anchor-distance error >0.5 m: histogram gradient boosting.
- Either error: histogram gradient boosting.
- Calibration: weighted monotonic Platt calibration on an episode-disjoint
  middle-batch partition.

## Input and output contract

One inference input is one current-vs-anchor sequential-pair ICP candidate. It
contains 19 scalar geometry/quality diagnostics (overlap, degeneracy, basin
ambiguity/separation, confidence, inliers, residuals, cloud counts/z-spans,
estimated anchor distance, and localizability) plus `match_class` and
`icp_ambiguity`. It excludes episode/batch identity, ground truth, downstream
outcome, current-vs-next disagreement, and future observations.

The output contains calibrated probabilities for bearing error >30°, distance
error >0.5 m, and either error; per-head trusted flags; missing/OOD status; and
shadow-only temporal recommendations. Every enforcement field is hard-coded
false in this version.

## Runtime evidence

The portable JSON export matched the sklearn bundle on 939 sampled readings:
maximum absolute probability difference `6.66e-16` and zero trusted-decision
mismatches.

The 2026-07-21 isolated episode-20 smoke run used the portable JSON artifact in
Isaac Python without sklearn. It scored 402 candidates in 201 calls at 1.139 ms
mean per candidate and 2.480 ms maximum per call. All 402 records were written,
all were feature-valid (`status=trusted`), and no enforcement field became true.

## Known limitations

The latest batch preserves strong ranking performance but violates all three
trusted-set bad-rate targets. The replay-tuned pose policy detects the known
pinned anchors, but the current artifact recovers none of the eight missed-stop
cases. Scalar diagnostics also cannot distinguish every confidently-wrong
corridor match. The runtime therefore locks the model to shadow mode.
