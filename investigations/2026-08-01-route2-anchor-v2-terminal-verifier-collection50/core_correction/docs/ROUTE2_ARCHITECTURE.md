# Route 2 architecture: Reliability V1.1 as the mandatory observation layer

Status: isolated implementation candidate, 2026-08-01.  This workspace does
not own, modify, launch, stop, or queue any Route 1 experiment.

## Non-negotiable system invariant

Raw ICP produces geometry, not authority.  Every ICP-derived bearing,
distance, pose, anchor identity transition, hint, or terminal claim must carry
the matching frozen Reliability V1.1 assessment before a high-consequence
consumer may act on it.

Raw ICP confidence, residual, overlap, inlier count, basin scores, the legacy
hand-written `U` score, and a downstream classifier trained on those values do
not substitute for V1.1.  They may remain inside V1.1 and in diagnostic logs.
They must not independently authorize a Route 2 action.

The geometry value itself still comes from ICP.  "Consume V1.1" means that a
downstream component receives the value together with the correct V1.1 head,
source anchor, role, attempt/step, and freshness, and cannot bypass that
assessment with raw confidence.

## Data flow

```text
LiDAR/current scan + saved anchor scan
              |
              v
raw multi-basin ICP diagnostics and geometry
              |
              v
frozen Reliability V1.1 (249 causal features)
     bearing head | distance head | pose head
              |
              v
versioned Reliability Envelope per anchor/attempt
              |
      +-------+---------+------------------+
      |                 |                  |
      v                 v                  v
pose consumers     bearing consumers   distance consumers
anchor state       route hint          terminal near/far
promotion          hint action         STOP veto/accept
quarantine
      |                 |                  |
      +-----------------+------------------+
                        v
             Route 2 controller/state machine
                        |
                        v
          VLM motion + collision/clearance layer

Independent visual A0 verification complements V1.1 for confidently-wrong
rotationally symmetric ICP basins.  It never changes which V1.1 head applies.
```

## Head ownership

The machine-readable source of truth is `config/route2_consumer_contract_v1.json`.

| Consumer | Required V1.1 head | Authority | Missing/untrusted behavior |
|---|---|---|---|
| reversible relocalization observation | none for admission | preserve raw candidates and attach envelope | continue as non-authoritative observation |
| route-progress/pose hypothesis | pose | raw target/source matching the estimate | update hypothesis only; no identity commit |
| anchor promotion | pose | proposed next anchor | hold; request recovery after bounded streak |
| anchor transition model | pose | current and proposed next | advisory/deferral only; cannot override V1.1 |
| quarantine entry/release | pose | affected anchor | temporal V1.1 evidence; never legacy `U` alone |
| route hint | bearing | anchor that supplied the bearing | omit hint |
| hint-action override | bearing | anchor that supplied the bearing | preserve VLM action |
| one-hop reconstructed hint | bearing | reconstruction source anchor | allow only bounded fresh one-hop evidence |
| terminal near/forced STOP | distance | fresh raw `next` anchor | no numeric STOP authority; verify visually/VLM |
| terminal far veto | distance | fresh raw `next` anchor | no numeric veto authority |
| geometry-reconstructed distance | none | n/a | never positive terminal authority |

`jointly_trusted` is reserved for consumers that genuinely require the full
transform.  It is not the default gate for every operation.

## Model contracts

### Reliability V1.1

The frozen three-head model is the root model.  It runs for every scored raw
candidate and emits probabilities plus trusted flags.  Route 2 has no
supported configuration in which downstream ICP authority is active while
V1.1 consumers are globally off.

Model/runtime failure is split by consequence:

- reversible candidate capture and relocalization observation continue;
- ICP-derived high-consequence actions fail closed;
- sensor-independent VLM motion, collision handling, and A0 verification
  remain available;
- a high-severity event is mandatory and the episode cannot pass acceptance.

There is no automatic fallback from V1.1 to raw ICP confidence.

### Anchor transition

The existing model includes V1.1 features, but it also includes raw ICP
quality proxies.  It is therefore a transitional model, not a clean core
model.  Its current legal authority is bounded deferral of an otherwise
eligible promotion.  A replacement must consume geometry/motion plus V1.1
pose outputs and must not learn a second hidden reliability classifier from
raw ICP diagnostics.

### Route 2 promotion and quarantine

Route 2 does not consume Route 1's raw-ICP promotion classifier.  Its
promotion contract is: the baseline geometric/sequence proposer may nominate
a transition; V1.1 `pose_trusted` for the proposed next anchor is mandatory
before evidence enters a promotion commit.  Quarantine requires temporal
high pose risk and bounded recovery; legacy `U` is diagnostic only.

### Hint and hint-action

The existing learned hint model contains V1.1 fields but also raw quality
proxies and remains advisory.  Production route hints and overrides require
`bearing_trusted` from the exact source of the bearing plus the independent
clear-path gate.  Bearing trust never authorizes STOP.

### Terminal

The existing Terminal V2 model contains V1.1 fields but is a shadow
probability sensor and is not final authority.  The online terminal state
machine consumes fresh `distance_trusted` for the exact raw next-anchor
distance.  Positive terminal decisions additionally require temporal and/or
independent A0/VLM evidence.  Reconstructed distance is never positive
terminal authority.

### A0 visual verification

A0 is an independent verifier, not a replacement reliability head.  It is
required because V1.1 cannot reliably separate every symmetric, geometrically
clean wrong ICP basin.  A0 may corroborate terminal or trigger a resample; it
may not silently promote an untrusted pose measurement.

## Control modes

Route 2 defines three distinct concepts and must not conflate them:

1. `model_inference`: V1.1 produces an envelope.
2. `consumer_enforcement`: the correct head gates a proposed action.
3. `downstream_model_authority`: Anchor/Hint/Terminal model output changes
   control.

V1.1 model inference and consumer enforcement are core requirements.  A
downstream learned model may separately remain shadow while it is being
validated.  Turning a downstream model off is not permission to turn the
root reliability layer off.

## Deployment and downgrade rules

V1.1 may be downgraded from core enforcement only with an explicit, recorded
decision containing:

- the exact model and consumer artifact hashes;
- the affected head, scene/scope, and consumer;
- prospective evidence that the active consumer is harmful or unsafe;
- the replacement authority and its evidence;
- user approval and an expiry/review condition.

A pooled navigation regression without per-consumer attribution is not enough
to globally disable V1.1.  A bad consumer policy must be fixed or scoped; it
does not demote the root model.

## Acceptance invariants

- Every high-consequence ICP-derived decision logs the envelope id, anchor,
  head, probability, trust flag, attempt, step, age, and executed effect.
- The head/consumer mapping is checked mechanically in tests.
- No active Route 2 launcher may combine active ICP consumers with
  `reliability_v11_consumer_mode=off`.
- No Route 2 launcher may enable the legacy reliability quarantine/demote/
  downstream-distrust controls.
- Missing or invalid V1.1 cannot fall back to raw confidence authority.
- Reversible relocalization candidate flow is preserved.
- Active promotion, hint, and terminal decisions must be attributable to one
  exact source anchor and one exact V1.1 assessment.
