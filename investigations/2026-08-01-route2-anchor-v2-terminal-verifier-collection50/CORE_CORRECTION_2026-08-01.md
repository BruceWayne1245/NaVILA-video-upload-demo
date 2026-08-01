# Route 2 Core correction — 2026-08-01

## Superseding finding

The original collection50 and the downstream development that preceded it did
not implement the intended Route 2 architecture. The launcher explicitly set
`--reliability_v11_consumer_mode=off` and
`--reliability_v11_derived_evidence_mode=off`. Reliability V1.1 still emitted
shadow observations, but downstream control consumed legacy/raw ICP authority
paths rather than mandatory V1.1 head-specific authority.

This was an architecture and communication failure: V1.1 had been treated as
optional shadow infrastructure even though Route 2 was understood to be built
on it. There was no evidence-backed downgrade record and no explicit approval
for that demotion. The old results remain valid only as evidence about the old
configuration; they must not be represented as results of a V1.1-core system.

## Why the downstream models were affected

The old learned artifacts had partial V1.1 fields but also enough raw ICP
quality features to reconstruct their own hidden reliability logic:

| Old artifact | Total features | V1.1-derived | Raw ICP quality proxies |
|---|---:|---:|---:|
| Anchor Transition V1 | 411 | 77 | 121 |
| Terminal V2 robust | 377 | 77 | 121 |
| Hint binary V2 | 364 | 75 | 135 |

Terminal was affected most severely because a row classifier, thresholds and
streaks were being asked to decide the highest-consequence outcome—STOP—while
the intended distance reliability authority was not enforced. The observed
false-near, low-recall and inconsistent terminal behavior cannot be attributed
only to this wiring error, but the old experiments cannot isolate the Terminal
model from it.

## Corrected system contract

Raw ICP produces geometry, not reliability authority. Every high-consequence
ICP-derived action must carry a fresh Reliability V1.1 envelope for the exact
source anchor and causal attempt/step:

| Operation | Authorization head | Missing/untrusted behavior |
|---|---|---|
| promotion and Anchor transition | pose | hold/request bounded recovery; no raw fallback |
| route hint and hint override | bearing | omit hint or preserve VLM action |
| Terminal near/far and STOP | distance | no numeric authority; use bounded visual/VLM verification |

Raw confidence, residual, inlier, overlap, ambiguity, basin,
localizability, scan-context quality, yaw-curve and legacy `U` fields are
forbidden as downstream reliability proxies. Geometry and causal motion remain
legal task inputs. Reconstructed distance never gains positive STOP authority.
A0 remains an independent visual verifier and cannot silently replace a V1.1
head.

The frozen V1.1 artifact itself was not retrained. Its portable artifact SHA is
`3fa7fe22cd5427fdabd19646361a88f0ef24942e64289280e0339268e6bf131a`.
Its prospective evidence contains 37,189 readings from 59 physical episodes:

| Head | AUC | AP | Trusted coverage | Bad rate among trusted |
|---|---:|---:|---:|---:|
| bearing | 0.9196 | 0.8674 | 44.90% | 4.68% |
| distance | 0.9453 | 0.8899 | 45.79% | 0.95% |
| pose | 0.9743 | 0.9585 | 40.48% | 1.29% |

## Data cleaning and CPU retraining

The immutable source captures under the 2026-07-29 training dataset were not
rewritten. Cleaning occurred during vectorization: a head-specific feature
firewall removed forbidden raw reliability proxies and wrong-head V1.1 fields
before fit, and each artifact froze its resulting feature names.

Source accounting:

- 112,733 Anchor rows and 10,900 Terminal rows;
- 282 captures across nine scenes;
- 155 captures with exact V1.1 step metadata and 127 with documented
  approximate interpolation;
- scene-disjoint split: seven training scenes, `EU6Fwq7SyZv` validation and
  `zsNo4HB9uLZ` test;
- CPU-only training; no GPU was required.

| Core V1 model | Required head | Features | Old test metric | New test metric | Change | Raw / wrong-head features |
|---|---|---:|---:|---:|---:|---:|
| Anchor Transition | pose | 270 | BA 0.770984 | BA 0.783471 | +0.012487 | 0 / 0 |
| Terminal Decision | distance | 275 | BA 0.741555 | BA 0.774424 | +0.032869 | 0 / 0 |
| Hint Action | bearing | 192 | BA 0.679023, AP 0.787164 | BA 0.737399, AP 0.806911 | +0.058376 BA, +0.019747 AP | 0 / 0 |

Frozen artifact hashes:

- Anchor Core V1:
  `cf920f45852c3ed7e0d15068c7e67a943bb01372ce9d922c7dfaa7531f73fa37`;
- Terminal Core V1:
  `49358cb7b53397469792718fc33765f87617b009290727c0cfac23eae0d1fa5b`;
- Hint Core V1:
  `2829784b30920a9e270a5c9f7050303f7ef2488cbedabb3a8c9c4901b9e97e7e`.

The artifacts are referenced by hash but are not stored in GitHub.

## Model interpretation after retraining

### Anchor Core V1

Cross-scene balanced accuracy improved modestly. It remains an online bounded
shadow observer with zero controller authority. Its first possible active role
would be negative-only veto/deferral under the pose-head contract.

### Terminal Core V1

Balanced accuracy improved, but the safety/utility trade-off is unresolved.
The locked old test sequence policy had zero true-far false arrivals and zero
arrived recall. The old policy had 0.269155 arrived recall but five true-far
false arrivals. Development arrived recall was 0.231735. Core V1 is therefore
a safer abstainer, not an active Terminal solution, and remains post-episode
shadow.

### Hint Core V1

Balanced accuracy and average precision improved. The clearance-gated test
policy achieved precision 1.0 but recall 0.051136, so it also remains shadow.

### Root versus downstream state

Downstream shadow status does not demote the root reliability layer. In the
corrected run, V1.1 inference and head-specific consumer enforcement are
active; Anchor, Terminal and Hint Core V1 are separately shadow-only.

## Verification

The corrected implementation passed static architecture/launcher preflight
and 91 automated tests. The tests cover the head map, forbidden raw fallback,
wrong-head rejection, artifact/hash contracts, cohort isolation, evaluator
wiring, capture integrity and scoring/export paths.

The exact small source/config/report snapshot is archived under
`core_correction/`. Large raw captures, model binaries, videos and environment
copies are intentionally excluded.
