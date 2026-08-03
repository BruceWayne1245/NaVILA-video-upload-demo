# Route 2 consolidated implementation plan — Anchor V2 full active

Date: 2026-08-02

## Decision

The Route 2 plan is consolidated around a learned temporal belief layer and a
deterministic safety executor. Reliability V1.1 remains frozen and is the sole
authority for ICP-derived reliability. Anchor Core V2 is promoted from a
shadow/negative-only candidate to a **full-active anchor transition
controller**. Hint and Terminal keep their previously approved deployment
boundaries while their task designs are rebuilt.

This document supersedes the earlier proposal to activate Anchor V2 only as a
bounded negative deferral. It does not supersede the Core correction's
head-specific authority contract.

## Consolidated architecture

```text
ICP / A0 / VLM / action-integrated motion
                    |
                    v
      Reliability V1.1 + dependency health
          pose / bearing / distance
                    |
                    v
          Temporal Route Belief
     anchor posterior / home posterior / age
       contradictions / motion / OOD state
                    |
        +-----------+-----------+
        |           |           |
        v           v           v
 Anchor V2 active  Hint split   Terminal sequence
   controller      models       model (shadow)
        |           |           |
        +-----------+-----------+
                    |
                    v
       deterministic safety executor
```

## Frozen component decisions

- Reliability V1.1 is not retrained. Pose is the only ICP reliability head
  that may authorize Anchor evidence, bearing is the only such Hint head, and
  distance is the only such Terminal head.
- The retrained Hint V2 is not promoted. The pre-retraining Hint Core V1
  remains the runtime baseline while Hint is split into evidence support and
  action utility, followed by a deterministic clearance gate.
- Terminal V2 remains shadow-only. The deterministic Terminal state machine
  retains STOP authority until a sequential model achieves both zero
  true-far false arrivals and useful arrived recall on prospective data.
- Raw ICP confidence/quality proxies cannot bypass V1.1 into a downstream
  authorization decision.

## Anchor V2 full-active authority

The current `anchor_transition_guard_mode=active` implementation is not full
active: it can only defer a baseline heuristic promotion twice and then fails
open. The replacement controller must make the executed anchor-transition
decision itself. The legacy heuristic remains computed only as a logged
counterfactual.

The model emits `advance_one`, `hold`, `rebase`, `rollback`, and
`skip_or_rebase`. These are corrections of the observed candidate selector
relative to the oracle look-ahead target, not unconditional direct index
assignments. The active controller therefore uses them as follows:

- `hold`, `advance_one`, and `skip_or_rebase` support forward progression of
  the observed next candidate; multi-anchor lag triggers expanded recovery
  evidence rather than an unobserved blind jump.
- `rollback` blocks forward commitment and requests bounded backward recovery
  evidence. It does not blindly increment the committed anchor from one row.
- `rebase` requests bounded candidate recovery because the model input lacked
  a valid observed next candidate.
- Low-confidence, stale, pose-untrusted, pair-mismatched, or OOD evidence
  holds and collects bounded recovery evidence. It never silently falls back
  to the legacy heuristic.

The model owns promotion/hold/recovery decisions. Deterministic code owns only
software and topology invariants: valid indices, legal route adjacency,
artifact/schema integrity, finite probabilities, bounded recovery, oscillation
protection, kill switch, and explicit safe failure.

## Anchor V2 activation sequence

1. Implement a separate `AnchorTransitionControllerV2`; do not reinterpret the
   old bounded promotion guard as full active.
2. Preserve causal timing: a complete attempt `t` may affect attempt `t+1`,
   never the attempt that generated its features.
3. Use class-group probabilities, class-specific confidence requirements and
   repeated-candidate temporal confirmation. Freeze their values using only
   development replay.
4. Suppress legacy heuristic authority in full-active mode while logging every
   heuristic vote and its counterfactual disagreement with V2.
5. Add bounded recovery for rollback/rebase/low-confidence states and explicit
   exits for long hold, candidate exhaustion, oscillation and dependency
   failure.
6. Run causal replay on historical plus development24/locked20 captures. The
   locked cohort is evaluation-only and cannot select thresholds.
7. Run a small wiring canary in full-active mode, followed by the separately
   agreed prospective cohort. A wiring canary is active from its first episode;
   it is not another shadow phase.

## Anchor evaluation

Report exact, off-by-one and off-by-two-or-more anchor state; harmful catches,
safe delays, false advances, false rollbacks, longest dwell/freeze, recovery
success and duration, oscillation, candidate exhaustion, Anchor0 reach rate,
return success, and per-scene worst cases. Separately report successes and
failures created only by V2 decisions.

## Remaining model work

### Hint

Rebuild decision-event labels around the final stateful hint, not the latest
raw candidate. Train separate `direction_supported` and `action_beneficial`
models. Keep collision/clearance and execution budgets deterministic. Require
useful coverage as well as high precision; a zero-action policy does not pass.

### Terminal

Replace row-wise arrival thresholding with the sequence
`far -> approaching -> boundary -> verify_home -> arrived`, including
`overshot`, `moved_away`, and `safe_fail`. Build a production-candidate-time
dataset with matched arrived/boundary/far controls and deployable motion.
Terminal activates last.

### V1.1 health and liveness

Add explicit OOD, missing, stale, contradictory-head and abstention-reason
telemetry. Map pose/bearing/distance abstention to different bounded recovery
paths. `Untrusted` means missing authority, not proof that the proposed action
is false and not permission to stall indefinitely.

## Live-run boundary

Implementation, tests, causal replay, launchers and acceptance reports may be
prepared immediately. No new live cohort starts until its episode list,
baseline/control comparison, activation switches, automatic supervision and
success/rollback gates are reviewed with the project owner.

## Implementation status

The first implementation pass is complete in the isolated runtime workspace
`/home/teambruce/navila-route2-v11-core-20260801`:

- added a causal `AnchorTransitionControllerV2` that can create a promotion
  when the legacy heuristic votes no, and can hold/request recovery when the
  legacy heuristic votes yes;
- legacy promotion and quarantine remain counterfactual telemetry in
  `full_active` mode; the normal low-confidence path does not fail open;
- V1.1 pose trust is mandatory, topology and artifact/head-authority firewalls
  are enforced, and the emergency kill switch is the only legacy fallback;
- copied the frozen robust V2 artifact with SHA-256
  `461577a982e3cd4a551e321741cb21bf5b0ac167d83252e67fb6d8cd5877a9cd`;
- added a preflight-only canary launcher. It requires a second explicit launch
  arm and uses the 3,600-second episode timeout; no live episode was queued;
- the complete local test suite passed `101/101`.

The validation-selected full-active policy uses progress threshold `0.60`,
recovery threshold `0.70`, one complete causal observation, and a 12-attempt
unconfirmed-hold budget. One-step held-out results were:

| Cohort | Promotion precision | Recall | Promotion rate |
|---|---:|---:|---:|
| EU6 validation | 0.9971 | 0.3917 | 0.3575 |
| x8 test | 0.9850 | 0.5524 | 0.4255 |
| locked20 (never used for threshold selection) | 0.9969 | 0.3691 | 0.3538 |

Locked20's five weighted false-promotion rows were one contiguous ep304 A5 to
A4 dwell. They represent one prospective state-changing risk, not five
independent active failures. The threshold remains frozen; ep304 is registered
as an active recovery watch case rather than used for post-hoc tuning.
