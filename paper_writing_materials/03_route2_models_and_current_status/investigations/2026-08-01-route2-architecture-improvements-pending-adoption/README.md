# Route 2 architecture improvements — 8/1 pending adoption

Status: **proposal only / 8/1 待采纳改进**

Recorded: 2026-08-01 BST
Decision boundary: do not implement these structural changes merely because
they appear cleaner. Consider adoption only if the frozen development24 and
locked-validation20 evidence supports the stated hypotheses.

## Executive judgment

The corrected Route 2 Core architecture is a sound transitional architecture,
but it is not the best end state. Its most important invariant is now right:
Reliability V1.1 is the sole authority for judging ICP-derived reliability,
and raw ICP quality proxies cannot bypass it into Anchor, Hint, Terminal, or
promotion decisions. That invariant should be retained.

The remaining weakness is that the system converts each observation into
three reliability heads and then asks mostly independent, row-wise downstream
models to recover a temporal route state. Terminal exposes this limitation
most clearly: the safe Core V1 policy removed false arrivals on the locked old
test set, but also reduced arrived recall to zero. More threshold tuning on the
same row classifier is unlikely to solve a missing-state problem.

## Non-negotiable invariants to keep

1. V1.1 remains the sole reliability authority for ICP-derived evidence.
2. Raw ICP confidence, residual, inlier, overlap, ambiguity, basin and related
   quality proxies enter the Reliability layer only; there is no raw fallback.
3. Each operation has exactly one authorization head:
   promotion/Anchor uses pose, Hint uses bearing, and Terminal uses distance.
4. Other V1.1 heads may be admitted only as typed context, veto or verification
   signals. They may never authorize an operation owned by another head.
5. Causal runtime inputs remain separate from oracle labels and retrospective
   diagnostics.
6. Integration states are explicit: offline, shadow, bounded active and active.
   No component may silently change state.

## Proposed target architecture

```text
Sensors / ICP / geometry / visual observations
                    |
                    v
Reliability Observation Model (V1.1 heads + OOD/abstain)
                    |
                    v
Unified Temporal Route Belief Service
  - anchor posterior and transition consistency
  - home pose/distance posterior
  - evidence age, uncertainty and contradictions
  - action-integrated motion and observation history
          |                 |                 |
          v                 v                 v
  Promotion/Anchor      Hint policy      Terminal state model
     pose authority   bearing authority  distance authority
          \                 |                 /
           +----------------+----------------+
                            |
                            v
                  Safety execution layer
```

This is an evidence proposal, not a claim that one large opaque model should
replace the current typed contracts. The shared temporal service should expose
auditable state and uncertainty; head-specific controllers retain separate
authorization boundaries.

## Proposed improvements

### 1. Replace strict head isolation with typed cross-head context

The Core V1 firewall correctly prevents wrong-head authorization, but complete
feature invisibility is unnecessarily rigid. Pose reliability can veto a
distance-based arrival when the pose is contradictory; distance trend can
request more evidence during a promotion; neither can positively authorize the
other operation. Implement this only through a declarative permission table
with `authorize`, `veto`, `verify`, `context`, and `forbidden` roles.

### 2. Add a unified temporal route-belief service

V1.1 estimates whether a current ICP-derived observation is reliable; it does
not by itself maintain belief across time. Introduce a causal state updater
that carries anchor posterior, home pose/distance posterior, evidence age,
cross-head consistency, missingness, OOD and action-integrated motion. Every
update must retain source timestamps and allow abstention.

### 3. Replace row-wise Terminal classification with a sequential state model

Model the return sequence explicitly:

```text
far -> approaching -> boundary -> verify_home -> arrived
                         |              |
                         +-> overshot <-+
                              |
                         moved_away / reject
```

The policy outputs should be `continue`, `request_evidence`, `hold_verify`,
`safe_stop`, and `reject_false_near`. Candidate inputs may include the V1.1
distance posterior, pose veto, trends, action-integrated motion, A0 visual
evidence, VLM stop evidence, evidence age and OOD. Terminal remains the last
component considered for active authority.

### 4. Make Anchor a constrained topology/posterior updater

Anchor should evolve from an independent transition classifier into a bounded
state update over route topology. A promotion proposal must be consistent with
the anchor posterior, permitted adjacency/rebase semantics, pose-head
reliability and recent motion. The learned component may initially veto or
defer but may not create promotion.

### 5. Split Hint into evidence correctness and action risk

Separate “is this bearing hint supported?” from “is the proposed action safe
and useful now?”. The first stage consumes bearing-authorized belief; the
second consumes clearance/action-risk evidence. This avoids treating a
geometrically correct hint as automatically executable.

### 6. Extend V1.1 with dependency-health outputs

Because every Route 2 consumer depends on V1.1, add explicit OOD, drift,
per-scene/policy calibration, missing/stale evidence, cross-head inconsistency
and abstain outputs. A V1.1 failure must degrade to evidence collection,
safe-hold or VLM-only behavior, never to raw ICP quality authority.

### 7. Strengthen evaluation design

Use geometry-, route/policy- and scene-grouped splits; preserve prospective
locked cohorts; and run multiple stochastic repetitions where simulator or VLM
variance matters. Development24 may generate hypotheses and future training
data. Locked-validation20 is opened once for a frozen evaluation and must not
be used for fitting, threshold selection, feature selection or early stopping.

### 8. Establish a single architecture registry and promotion ledger

The registry should bind immutable artifact hashes, feature contracts, head
permissions, calibration versions, runtime flags and integration state in one
machine-checkable configuration. Preflight must fail closed on a mismatch.
Every shadow/active transition requires an explicit decision record and a
rollback target.

## What the 24+20 evidence must test

Development24 is for diagnosis and hypothesis generation. Before opening the
locked20 outcomes, freeze the candidate architecture, feature set, temporal
state definition, thresholds and scoring code. Locked20 is then evaluated once.

| Hypothesis | Supporting evidence | Evidence against adoption |
|---|---|---|
| Temporal belief is needed | Reliability errors cluster over time; stale/missing evidence and trends explain errors that row features cannot separate | Head-specific row models generalize with safe useful recall and calibrated confidence |
| Sequential Terminal is needed | False-near, boundary, overshot or moved-away cases require transition history; the threshold/streak Pareto front remains zero-safe but near-zero recall | A frozen simple policy achieves zero true-far false arrivals and useful arrived recall on locked20 |
| Typed cross-head veto is useful | Counterfactual veto/verify context prevents observed mistakes without creating any unsafe authorization | Cross-head context adds no grouped benefit, or causes new unsafe positive decisions |
| Unified belief improves generalization | Frozen temporal features improve scene/route/geometry-grouped calibration and decision metrics on locked20 | Gains exist only on development24, disappear out of group, or depend on oracle/noncausal inputs |
| V1.1 health outputs are needed | Errors concentrate in OOD, stale, missing or inconsistent-head states and abstention isolates them | These states are rare and have no predictive relationship with failures |

The most important Terminal safety gate remains zero true-far false arrivals.
A zero-error result with zero or negligible arrived recall is not a successful
Terminal model; it is a safe abstainer. Conversely, improved recall with even
one unexplained unsafe far acceptance does not justify active STOP authority.

## Adoption sequence if evidence supports the proposal

1. Offline replay and grouped cross-validation using development24 only.
2. Freeze code, feature contracts, thresholds and artifact hashes.
3. Open locked-validation20 once and publish every result, including missing
   and infrastructure-invalid episodes.
4. If supported, implement the smallest separable component first: temporal
   belief logging and typed veto/context contracts in shadow.
5. Move Anchor veto and Hint advisory behavior to bounded active only after a
   new prospective confirmation cohort and explicit authorization.
6. Keep Terminal shadow-only until it demonstrates both safe far rejection and
   useful arrived recall on new prospective data. Activate Terminal last.

## Interpretation boundary

The 24+20 run can justify investing in and implementing these changes; it
cannot by itself authorize full active deployment. A safety-critical wiring or
contract bug may be fixed independently, but the structural proposal above
must not be smuggled into the currently frozen run. If the evidence falsifies
the hypotheses, retain the corrected Core architecture and improve only the
specific component supported by the data.

No credential, model binary, raw simulator log bundle or video is stored here.
