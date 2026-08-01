# Route 2 V1.1 core migration and validation

This plan is Route 2 only.  It does not wait for, append to, stop, inspect as
an owner, or modify Route 1's 30-episode experiment.

## State at the migration boundary

The prior runtime can score Reliability V1.1 online, but its current launcher
sets every V1.1 consumer to off.  Existing learned Anchor, Hint, and Terminal
artifacts contain V1.1 features but also contain enough raw ICP quality
features to bypass it.  They are transitional and cannot be the authority in
the corrected system.

The isolated candidate changes the control boundary, not the frozen root
model:

1. score every raw candidate with frozen V1.1;
2. preserve raw geometry as a reversible observation;
3. use pose only for promotion, bearing only for hint/action, and distance
   only for terminal;
4. log exact envelope, head, probability, source, freshness, and effect;
5. deny the affected ICP-derived action if V1.1 is missing/invalid, while
   preserving VLM, collision, A0, and observation flow.

## Activation ladder

### Stage 0 — static contract (complete)

- machine-readable consumer/head and downstream-model contracts;
- active V3 policy artifact with no raw fallback;
- hash-locked, Route-2-only launcher whose default is preflight;
- evaluator wiring, invalid-output, wrong-head, derived-evidence, terminal,
  and capture-integrity tests;
- old learned-model input audit and head-specific training feature firewall.

### Stage 1 — one-episode active canary (prepared, not launched)

Episode 368 is a known Route 2 development episode.  The canary activates the
root consumer policy only.  Anchor/Hint/Terminal learned artifacts, legacy
quarantine/demote/distrust, stuck recovery, candidate selector/controller,
and active-scan prototypes remain off.

Acceptance requires:

- frozen artifact SHA `3fa7fe22...` and zero inference exception/nonfinite;
- core policy active, no invalid-state event and no fail-open;
- every consumer event uses its declared head and has a complete envelope;
- reconstructed distance never gains terminal authority;
- reversible relocalization continues producing candidate scores;
- capture validator passes and the episode terminates without a new
  promotion/terminal liveness deadlock.

The canary launcher does not run unless explicitly invoked with `--launch`.

### Stage 2 — small prospective safety set

Only after Stage 1 passes, select a small Route 2 set spanning scenes and
known failure modes: trusted/untrusted pose transitions, EU6 bearing cases,
near/far terminal cases, A0 disagreements, and symmetric wrong-basin cases.
Do not mix this set with Route 1's queue or claim its outcomes for Route 1.

Evaluate by operation, not only pooled navigation success:

- promotion: holds, veto streaks, recovery requests, false/late promotions;
- hint: authorized/omitted hints and direction error by scene;
- terminal: accepted/forced/veto/verify/blind/safe-fail, false-stop and missed
  arrival counts;
- liveness: longest hold streak, queries and path length added by each gate.

### Stage 3 — core-compliant downstream successors

Retrain three separate models behind the feature firewall:

- Anchor successor: geometry/motion/sequence plus pose head only;
- Hint successor: task bearing/VLM/clearance plus bearing head only;
- Terminal successor: task distance/VLM/A0/motion plus distance head only.

Required training data records one row per causal decision opportunity with:

- physical episode/scene and immutable attempt/step/source identifiers;
- exact V1.1 envelope and head probability available online at that time;
- task geometry, motion, freshness, VLM and independent A0/clearance fields;
- the proposed action before gating and the executed action after gating;
- post-hoc oracle labels attached only after decision logging;
- explicit false-stop, missed-arrival, wrong-hint and wrong-promotion labels.

Group splits are by physical episode, with a cross-scene report.  No frames,
attempts, temporal windows, paired arms, or retried physical episode may cross
train/calibration/test boundaries.  Raw confidence/residual/inlier/overlap,
basin, localizability, scan-context quality and legacy `U` are rejected by
the feature firewall.

### Stage 4 — downstream authority

The clean models first run shadow while V1.1 core enforcement stays active.
Promotion may then receive bounded negative authority; Hint may replace a VLM
action only after bearing and clearance gates; the Terminal model remains an
advisory probability input to the deterministic state machine.  None may
authorize an action that its required V1.1 head denied.

## Why not activate the existing learned models

Opening them would create more controller-effect data, but it would also
confound the experiment: their 121/135 raw quality proxies let them recreate
a second reliability model around V1.1.  The informative active intervention
now is the V1.1 head-specific guard itself.  It supplies action-level effects
and counterfactuals while clean successors are trained.  Existing learned
artifacts remain shadow/bounded-negative comparators until their inputs are
clean.

## Downgrade control

No code branch or launcher edit may demote V1.1 globally.  A downgrade record
must name the exact artifact and policy hashes, head, consumer, scene/scope,
prospective harm, replacement authority, user approval, expiry, and rollback.
A policy defect is repaired or scoped; it does not silently demote the root
model.
