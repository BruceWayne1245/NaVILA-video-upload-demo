# Route 2 model and consumer audit

Audit date: 2026-08-01.  Scope is Route 2 only.  Route 1's learned promotion
controller, its 30-episode experiment, queue, services, and source are not
Route 2 assets and are not changed here.

## Executive finding

The frozen Reliability V1.1 model has strong prospective discrimination and
portable-runtime evidence.  There is no recorded evidence supporting a global
downgrade of V1.1 to observational shadow.  The historical failure was Policy
V1's hard removal of reversible relocalization updates, not the root model.
Policy V2 correctly preserved candidates but still used `jointly_trusted` too
broadly.  The current batch then disabled all V1.1 consumers, creating the
architecture regression addressed in this workspace.

## Version inventory

| Component | Current artifact/version | What it consumes now | Current authority before this correction | Audit result |
|---|---|---|---|---|
| ICP reliability | frozen full-temporal V1.1, portable SHA `3fa7fe22...` | 249 causal raw ICP, multi-basin, pair and temporal features | online prediction, but current launcher made it shadow-only | root model; must be core |
| legacy reliability `U` | deterministic hand-written score | raw confidence, ambiguity and history | quarantine/demote/downstream confidence changes | incompatible as authority; diagnostic only |
| RouteMemory relocalization | deterministic state estimator | raw ICP geometry and legacy confidence | reversible updates and hypotheses | preserve observations, attach V1.1 envelope; no high-consequence authority |
| Route 2 promotion | deterministic baseline proposer + V1.1 guard | proposed next-anchor pose and V1.1 pose head | current branch used baseline/legacy logic because consumer was off | use `pose_trusted`; hold/recover when absent |
| Anchor Transition | `anchor_transition_v1.joblib`, bounded Guard V2 policy | geometry/motion, 77 V1.1 features, and 121 raw quality proxies | shadow; conditionally bounded defer in queued design | transitional; bounded negative authority only |
| Hint action | binary V2 model plus Hint recheck policy V3 | VLM/action/geometry, 75 V1.1 features, and 135 raw quality proxies | advisory/shadow; production arbiter used legacy confidence | transitional; production gate must use bearing head |
| Terminal probability | `terminal_decision_v2_robust.joblib` | route/A0/motion, 77 V1.1 features, and 121 raw quality proxies | post-episode/shadow probability sensor | transitional; not STOP authority |
| Terminal state machine | current `ReturnStopGate` | route distance, freshness, VLM STOP, A0 and `evidence_trusted` | correctly required V1.1, but received `None` with consumers off | wire directly to distance head |
| A0 visual verifier | LoFTR/RGB-D direct visual probe | start view and current view/depth | independent verification/fallback | required complement, not replacement |
| Anchor-support recovery | active policy V1, cohort-scoped approvals | temporal V1.1 joint/pose evidence | off in current branch | useful recovery layer; must be re-approved by scope |
| NaVILA VLM | `navila-llama3-8b-8f` | camera history, instruction, optional V1.1-authorized route hint | active motion/STOP proposal | independent controller; its ICP-derived prompt additions require bearing authority |
| low-level Go2 locomotion | frozen RSL-RL policy from run `2024-09-25_23-22-02` | parsed velocity command and proprioception | active actuator policy | no ICP input and no V1.1 head; bounded by collision/clearance supervision |
| stuck/wedge recovery | deterministic supervisor V1 | physical no-progress, raw believed distance and raw bearing | active in the previous terminal launcher | not core-compliant; disabled in the candidate until distance-trigger and bearing-face paths are separately head-gated |
| active scan / integrated candidate selector | policy prototypes | V1.1 temporal state plus candidate geometry | shadow/off | remain off; not needed to make the root layer active |

## Root model evidence

Frozen prospective V1.1 results on 37,189 scoreable readings from 59 physical
episodes:

| Head | AUC | AP | trusted coverage | bad rate among trusted |
|---|---:|---:|---:|---:|
| bearing | 0.9196 | 0.8674 | 44.90% | 4.68% |
| distance | 0.9453 | 0.8899 | 45.79% | 0.95% |
| pose | 0.9743 | 0.9585 | 40.48% | 1.29% |

The evidence is bounded by represented scenes, capture-integrity failures in
three files/episodes, and weak bearing behavior in `EU6Fwq7SyZv`.  These are
reasons to add scene monitoring and A0 corroboration.  They are not evidence
that raw ICP confidence is a better global authority.

Portable online evidence: 698 calls / 1,244 candidate rows with exact offline
parity, no non-finite output or runtime exception, about 3.26 ms average
latency and under 3.91 ms observed maximum.

## Consumer-by-consumer target contract

### Reversible relocalization

- Input: unchanged raw geometry plus V1.1 envelope.
- V1.1 effect: mark authority/risk; do not delete the observation.
- Rationale: Policy V1 generated 3,768/7,375 full defers and streaks up to 900.
- Failure behavior: preserve non-authoritative observation; deny downstream
  high-consequence use.

### Route 2 promotion

- Proposer input: sequence/geometry evidence.
- Required authority: proposed-next `pose_trusted` and exact attempt linkage.
- Positive effect: permit the already-proposed vote/commit; V1.1 alone does
  not invent a promotion.
- Negative effect: hold.  At a bounded streak request recovery; never restore
  raw-confidence authority.
- Route 1's learned promotion classifier is outside this contract.

### Anchor Transition

- Required head: pose for current and proposed next.
- Existing model: 411 total features, 77 V1.1, 121 raw quality proxies.
- Current validation/test balanced accuracy: 0.7346/0.7710, with material
  train-to-cross-scene gap.
- Authority: at most bounded deferral; cannot authorize a transition that
  V1.1 pose evidence denies.
- Required successor: retrain on geometry/motion plus V1.1 pose envelope,
  excluding raw quality proxies.

### Hint and hint-action

- Required head: bearing from the exact source anchor.
- One-hop reconstructed hint: source-anchor bearing head, one hop, age at most
  25 updates.
- Independent requirement: clear-path/collision gate.
- Missing/untrusted behavior: omit hint or preserve VLM action.
- Existing binary V2 has useful advisory precision but remains transitional
  because it can learn around V1.1 from 135 raw quality proxy features.

### Terminal

- Required head: distance from fresh raw `next` evidence.
- Near/STOP: V1.1 distance trust is necessary but not sufficient; temporal
  confirmation and/or independent VLM/A0 evidence remain required.
- Far veto: requires fresh distance trust.
- Reconstructed distance: no positive terminal or far-veto authority.
- Missing/invalid behavior: no numeric authority; use the bounded visual/VLM
  verification state machine.
- Existing Terminal V2 held-out test has five sequence-gate false arrivals and
  missed all arrived rows in prospective ep319; it remains a probability
  sensor, not final authority.

### Quarantine and recovery

- Entry/release head: temporal pose evidence.
- Legacy `U` cannot independently enter, release, demote, or blacklist.
- Quarantine is reversible but can destroy liveness; it needs bounded scope,
  explicit recovery, and telemetry.
- Anchor-support recovery is preserved as a separately versioned consumer,
  not folded invisibly into reliability inference.

### A0 visual verification

- Consumes no V1.1 head and is intentionally independent.
- Covers visually distinguishable symmetric/wrong-basin cases that scalar
  V1.1 can miss.
- May corroborate terminal and trigger resampling/recovery.
- Cannot silently override an untrusted pose or promote an anchor.

### VLM and low-level locomotion

- The VLM is not an ICP reliability model.  Its camera-driven motion remains
  available when V1.1 is missing; any route hint injected into its prompt must
  first pass the bearing head.
- A VLM STOP is only a proposal.  The terminal state machine decides whether
  it is accepted, rejected, held for verification, or converted to safe-fail.
- The low-level policy consumes the already-selected motion command, not ICP
  quality.  It therefore has no V1.1 input contract of its own.

### Stuck/wedge recovery

- Physical no-progress is independent evidence, but the current trigger also
  consumes a raw believed-distance threshold and the `face_next` phase uses a
  raw bearing.  Those two fields are ICP-derived authority inputs.
- It is therefore disabled in the V1.1 core canary.  A compliant successor
  must gate the far trigger with the distance head and gate `face_next` with
  the bearing head; once a physical escape maneuver is latched, its bounded
  collision-safe completion does not need repeated ICP authorization.

## Existing learned-model feature leakage around the root layer

The three downstream artifacts contain V1.1 output, but they also see enough
raw ICP quality diagnostics to construct their own reliability logic:

| Artifact | total features | V1.1-derived | raw ICP quality proxies |
|---|---:|---:|---:|
| Anchor Transition V1 | 411 | 77 | 121 |
| Terminal V2 robust | 377 | 77 | 121 |
| Hint binary V2 | 364 | 75 | 135 |

Therefore these versions are retained for shadow comparison and bounded
negative interventions only.  Core-compliant successors must receive:

- the geometry value needed for their task;
- movement/sequence/freshness/source/role context;
- the matching V1.1 probabilities and trusted flags;
- independent VLM/A0/clearance evidence where applicable;
- no raw ICP confidence, residual, inlier, overlap, basin, localizability,
  scan-context-quality, corridor-degeneracy, or legacy `U` proxy.

## Authority hierarchy

1. Collision/clearance safety may always block motion.
2. V1.1 controls whether an ICP-derived claim has task-specific authority.
3. A downstream model may refine what to do with an authorized claim but may
   not bypass the required head.
4. A0/VLM can provide independent evidence through explicitly declared paths.
5. No model, heuristic, or fallback may silently substitute raw confidence
   for V1.1.

## What is active versus shadow

- V1.1 root inference and head-specific consumer enforcement: core/active in
  the new candidate policy.
- Anchor/Hint/Terminal learned artifacts: shadow or bounded negative authority
  until core-compliant retraining and prospective validation.
- A0: active only through its existing bounded verifier contract.
- Recovery policies: separately scoped and gated; never implied by V1.1 being
  active.
- Stuck recovery: off until its two ICP-derived inputs are split by head.

This separation prevents the prior mistake: a downstream model can remain
shadow without downgrading the root reliability layer.
