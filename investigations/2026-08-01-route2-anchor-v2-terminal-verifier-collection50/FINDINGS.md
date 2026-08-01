# Findings — 2026-08-01 Route 2 optimization

> **Status amendment:** sections below document the earlier V1.1-off system.
> They remain useful forensic evidence but do not characterize the corrected
> Route 2 Core architecture. See `CORE_CORRECTION_2026-08-01.md` for the
> superseding finding and retraining results. No old metric was deleted or
> rewritten.

## 1. Frozen Unified50 accounting

The frozen retry4 run produced 48 per-episode scoring summaries. Ep855 is not
imputed: it remained an infrastructure-missing episode. Twenty-eight fresh
episodes contained the artifacts needed by the joint Hint/Terminal scorer.
All reported consumers were read-only and `control_effect=none`.

### Hint v3 bounded evidence recheck

Across the 28 scoreable fresh episodes:

| Requests | Weighted beneficial | Weighted non-beneficial | Beneficial fraction |
|---:|---:|---:|---:|
| 10 | 8.5 | 1.0 | 0.8947 |

This is the best result among the three learned Route 2 components, but it is
below the registered 0.90 gate and is based on only ten requests. Hint v3
remains a read-only evidence-request candidate with no movement or STOP
authority.

### Frozen Terminal/A0 first-accept outcomes

Counts below are episode-level first accepts in the 28 scoreable fresh
episodes:

| Policy | Arrived | Boundary | Direct far | No accept |
|---|---:|---:|---:|---:|
| Terminal model only | 10 | 0 | 2 | 16 |
| Legacy A0-sufficient fallback | 5 | 2 | 3 | 18 |
| Strong A0-sufficient fallback | 4 | 0 | 0 | 24 |
| A0 hard-required with Terminal | 1 | 0 | 0 | 27 |
| Conditional hierarchy | 4 | 0 | 0 | 24 |

The apparent zero-false-accept rows are not sufficient activation evidence:
they retain only one or four arrived accepts. A global Anchor0 requirement
would exchange the observed far failures for unacceptable arrived-recall
loss. The frozen Terminal model itself still produces direct-far first
accepts.

### Frozen Anchor V1

Physical promotion truth was reconstructed for 126 scoreable fresh promotion
votes. There were 11 harmful promotions in the evaluation population.

| Policy | Deferrals | Harmful catches | Safe delays | Precision | Harmful-catch recall |
|---|---:|---:|---:|---:|---:|
| Frozen V1 | 2 | 1 | 1 | 0.50 | 1/11 = 0.091 |

This is far below the earlier Shadow30 result and blocks activation. The safe
delay was ep555; the frozen adjacent-only semantics also missed a useful
non-adjacent rollback signal on ep1016.

## 2. Anchor V2 semantic candidate

The frozen model, feature timing, 0.90 threshold and two-deferral cap remain
unchanged. Only the counterfactual guard semantics change:

- `rollback` is over-advance risk;
- `skip_or_rebase` is treated as a lagging/rebase signal and does not veto;
- high-confidence rollback can flag non-adjacent candidates;
- the guard still cannot create promotion and fails open after its bounded
  counterfactual deferrals.

Offline comparison on the locked fresh truth set:

| Candidate | Deferrals | Harmful catches | Safe delays | Precision | Recall |
|---|---:|---:|---:|---:|---:|
| Frozen V1 | 2 | 1 | 1 | 0.50 | 1/11 |
| Rollback-only, adjacent, 0.90 | 1 | 1 | 0 | 1.00 | 1/11 |
| Rollback-only, adjacent + non-adjacent, 0.90 | 2 | 2 | 0 | 1.00 | 2/11 |
| Rollback-only, all identities, 0.85 | 4 | 4 | 0 | 1.00 | 4/11 |

The 0.85 row is sensitivity analysis only and is ineligible for threshold
selection because the fresh outcomes had already been inspected. The 0.90
non-adjacent candidate is the only actionable semantic candidate. It is being
collected in shadow and must not be interpreted as active improvement.

## 3. Rejected Terminal reliability-masking experiment

The hypothesis was that absolute route-progress fields should be masked when
their causal authority was not `trusted_next_raw` or
`trusted_bounded_reconstruction`. The model was fit only on historical
train+validation data; threshold/streak selection used leave-one-development-
scene-out predictions. Unified50 fresh rows were opened only after fitting.

Selected policy: threshold `0.8662`, streak `3`.

| Evaluation | Arrived accepts | Boundary accepts | Far accepts | Arrived-opportunity recall |
|---|---:|---:|---:|---:|
| Untouched historical test | 4 | 0 | 2 | 4/15 = 0.267 |
| Unified50 fresh28 | 8 | 1 | 5 | 8/15 = 0.533 |

Fresh row-level sequence errors included 21 direct-far confirmed rows and two
boundary confirmed rows. The candidate is rejected. Untrusted route numbers
are unsafe as authority but still contain ranking information; deleting them
caused the classifier to lean more heavily on other correlated proxies.

## 4. Terminal verifier evidence audit

The next design keeps frozen Terminal V2 as the proposal generator and adds a
candidate-time verifier over genuinely new evidence. A leakage-safe extractor
was implemented and tested. It rejects legacy `inputs.movement` because the
historical builder derived translation/yaw change from simulator ground-truth
trajectory poses.

| Dataset | Candidate events | Arrived | Boundary | Far | A0 recorded | Strong A0 | Deployable motion | Multi-view computable |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Historical train/validation/test | 55 | 46 | 2 | 7 | 0 | 0 | 0 | 0 |
| Unified50 fresh28, audit only | 16 | 11 | 1 | 4 | 7 | 2 | 0 | 0 |

Both strong-A0 fresh events were arrived; every fresh far/boundary candidate
lacked strong A0. But a strong-A0 requirement would retain only 2/11 arrived
candidates, and historical candidates contain no A0 at all. This is useful
evidence, not a standalone gate or fit-ready dataset.

Only 2/55 historical candidates had trusted route authority and none of the 16
fresh candidates did. Existing rows also lack deployable motion provenance, so
repeated A0 observations cannot be distinguished from stationary repeated
views.

Raw route-memory trajectories do retain action-integrated
`return_pose_from_return_start`, allowing deployable query-to-query motion and
viewpoint change to be reconstructed offline without simulator ground truth.
The new collection therefore logs A0 eagerly at every return query while
retaining the existing raw trajectory state.

## 5. Interpretation boundary

- Unified50 Fresh49 remains evaluation-only and cannot enter fitting,
  threshold choice, early stopping or policy selection.
- The new 50 is an explicit repeated-scenario development collection using
  episodes already represented in return data. It is not a prospective OOD
  performance estimate.
- Missing return phases are valid system outcomes, not automatically
  infrastructure failures.
- Anchor V2 and eager A0 are shadow/observation mechanisms. They provide no
  claim of navigation improvement while `controller_effects=0`.

## 6. Boundary with concurrent Route 1 work

The same-day Route 1 investigation found that its synthetic A0 could remain
`descriptor=None` and become an unmatchable last candidate after a quarantine
cascade. Route 1 fixed that path by backfilling the first real outbound
descriptor and added a conservative model quarantine-veto AND-gate.

This collection is not running that new Route 1 code. Its frozen Route 2
snapshot predates those commits but already has a separate opt-in reset-time
A0 capture method, enabled by
`--route_memory_capture_start_anchor_descriptor`. The observed 251/252
available A0 probes confirm that the Route 2 collection is obtaining usable
A0 observations. No conclusion about which A0 initialization mechanism is
preferable should be made until the collection finishes and descriptor timing
is compared explicitly.

The Route 1 follow-up batch is queued behind, rather than inside, this Route 2
service. Results from the two runs must retain their separate runtime
provenance and must not be pooled as though they used one controller snapshot.
