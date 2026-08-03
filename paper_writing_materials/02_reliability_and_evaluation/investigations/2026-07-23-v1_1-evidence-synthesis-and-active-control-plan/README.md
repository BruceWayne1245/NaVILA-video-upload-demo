# Reliability V1.1 evidence synthesis and active-control plan — 2026-07-23

## Bottom line

V1.1 has strong prospective evidence that it separates reliable from unreliable
raw sequential-pair ICP readings. It does **not** yet have evidence that a
particular way of consuming those predictions improves navigation, because all
online observations so far were non-enforcing.

The next combined Route-1/V1.1 100-episode run is therefore instrumented as a
decision-complete shadow experiment. It evaluates one exact proposed consumer:
the role-safe pre-controller filter in the companion handoff directory. If and
only if all frozen integrity, risk, availability, and starvation gates pass,
the next step is a 10-episode guarded **active** canary. A clean canary then
authorizes a predeclared 100-episode active A/B; it does not authorize an
uncontrolled global rollout.

This distinction matters:

- The previous prospective 100ep says the model itself is promising.
- The 5ep online canary says the portable implementation is fast and exactly
  reproducible on the three episodes that reached return scoring.
- Neither run tells us whether hard rejection starves the controller or
  improves round-trip success.
- The new decision-shadow framework is designed to answer the missing
  consumer-policy questions without letting V1.1 affect Route 1.

## Contents

- `FINDINGS.md`: all model, capture, online-runtime, navigation, and policy
  conclusions reached on 2026-07-23.
- `NEXT_STEP.md`: frozen experiment sequence and activation decision tree.
- `DATA_INDEX.md`: provenance and interpretation of every included dataset.
- `CONTROL_READINESS_GATES.json`: copy of the exact pass/fail contract.
- `data/prospective_100ep/`: complete analyzable prospective V1/V1.1 datasets,
  predictions, reports, manifests, and integrity audits.
- `data/online_canary/`: 5ep operational summary, per-episode validation
  results, policy replay summary, and master log.
- `tools/`: the analysis tools used for the prospective dataset.
- `DATA_MANIFEST.sha256`: package-relative hashes for this evidence directory.

Raw Isaac captures and point-cloud frame trees are not duplicated into Git.
Their reconciliation results, hashes/manifests, complete model-ready datasets,
and row-level frozen predictions are included. The raw source locations are
recorded in the reports and manifests.

## Companion implementation

The exact runnable shadow/control-readiness framework is archived separately
at:

`../2026-07-23-v1_1-control-readiness-shadow-handoff/`

That directory contains the candidate entry point, runtime, portable artifact,
policy, gates, validators, readiness scorer, tests, runner arguments, and
activation plan as one hash-locked snapshot.

## Scope boundary

V1.1 scores scalar/geometric ICP diagnostics. It can reject many dangerous
readings, but cannot reliably identify a rotationally symmetric wrong basin
when that basin also looks geometrically clean. Visual rotation verification
remains the root-cause path for that failure family. V1.1 should be treated as
a selective-use safety layer, not as a replacement for visual verification.

