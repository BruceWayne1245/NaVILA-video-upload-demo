# Route-2 anchor-support recovery implementation

Date: 2026-07-28

## Outcome

The accumulated design decisions have been implemented in a new isolated
candidate tree:

`/home/teambruce/navila-reliability-v1_1-anchor-support-recovery-20260728`

The frozen 2026-07-27 Active-50 source tree was not edited.  The new candidate
has not been launched as a live batch.

This implementation corrects an earlier interpretation in the 2026-07-27
terminal-recovery design: routing double-untrusted state into active scan was
not a valid terminal behavior.  Scan is a shadow observer only and cannot be
an execution dependency.

## Authoritative sequential-pair semantics

`current` and `next` are independent support roles.  They are not an estimate
that the robot is physically located between two adjacent anchor identities.

- `current`: a trustworthy rear support from which fixed outbound route
  geometry may be composed.
- `next`: a trustworthy forward guide used by navigation.
- The indices may be non-adjacent.
- A bad anchor may remain eligible for ICP/model probing while being forbidden
  from promotion to `current`.  Its raw ICP is barred from hint authority while
  the model still considers it bad; that raw-hint block clears if later motion
  supplies enough trusted evidence, while the promotion block remains.

This separation is implemented in `RouteMemoryAgent`; it no longer requires
the Route1 `_target_anchor_index` to simultaneously represent both roles.

## Implemented transitions

### Trusted current, untrusted next

The bad `next` is:

1. added to a persistent promotion/raw-hint block set;
2. reconstructed from the trusted `current` and the fixed outbound
   anchor-to-anchor edge chain;
3. retained as the forward geometric target without ever being promoted to
   `current`.

Pass detection uses the reconstructed next distance with the existing
minimum-distance plus hysteresis rule.  Once the robot passes it, only `next`
advances by one index; `current` remains fixed.

Multi-hop reconstruction now carries explicit provenance:

- `estimate_kind=geometry_reconstructed`
- `source_anchor_index`
- `edge_hop_count`
- source and raw-target confidence

Navigation bearing authority can be configured for a bounded number of fixed
edge hops.  Forced-stop authority is still never granted to derived distance.

### Trusted next, untrusted current

The trusted `next` is used without allowing the bad `current` to veto it.
Normal trusted promotion can advance the pair.  This implements the intended
fact that forward guidance is the important role; current is supporting
evidence, not an exact-position identity constraint.

### Both current and next untrusted

For an initial pair `C10/N9`, the active search is exactly:

1. `C11/N9`
2. `C11/N8`
3. `C12/N8`
4. `C12/N7`
5. `C12/N6`

The offsets are policy-validated and cannot silently be reordered.

At each pair:

- a trusted current plus bad next enters reconstruction;
- a trusted next plus bad current enters next-only guidance;
- only another confirmed double-untrusted result advances the alternating
  search.

### Bounded search exhausted

The system enters `vlm_only_probing`.

All route-derived navigation consumers are paused:

- route hint injection;
- hint-action override;
- stuck/wedge scripted recovery;

The VLM navigation command passes through unchanged.  A VLM-issued STOP does
not bypass terminal safety: the follow-up investigation
`investigations/2026-07-28-terminal-stop-evidence-state-machine/` supersedes
the earlier stop-gate behavior described here.  Terminal verification remains
active in VLM-only mode and requires independent positive evidence before it
can report success.

At the same time, ICP and Route-2 scoring run on every forward anchor from the
original failed `next - 1` down to anchor 0.  These candidates are probes only:
they are explicitly labeled `anchor_role=other` and are excluded from all
Route1 closure, trend, quarantine, selection and promotion bookkeeping.

When one or more forward probes becomes trusted, the closest forward trusted
anchor (highest index) becomes `next`, route consumers resume, and the bad
current is not allowed to veto it.

## Scan invariant

The new active state machine contains no scan transition, scan latch,
controller-disable action or scan recovery dependency.

It emits only `shadow_scan_recommended`, which is copied into diagnostics.
The field does not feed back into role selection, blacklists, hints, stop
logic, motor commands or fallback.  The obsolete 2026-07-27 active candidate
controller is rejected at startup when anchor-support recovery is active,
because that controller disabled itself on scan requests.

Therefore scan shadow enabled/disabled changes logs only.

## Main code changes

- `reliability/v11_anchor_support_recovery.py`
  - new policy-validated active state machine;
  - exact alternating search;
  - VLM-only probe pool and trusted-probe recovery;
  - persistent promotion/raw-hint blocks.
- `policy_v2_live_candidate/scripts/route_memory_agent.py`
  - independent support-current and guidance-next indices;
  - probe eligibility separated from blacklist semantics;
  - multi-hop trusted-current reconstruction;
  - reconstructed-next pass handling;
  - probes excluded from every Route1 consumer.
- `policy_v2_live_candidate/scripts/relocalization.py`
  - supports additional probe anchors;
  - records explicit current/next/other role.
- `reliability/v11_runtime.py`
  - honors explicit role labels, preventing a numerically higher probe from
    being mistaken for `next`.
- `reliability/v11_consumer_policy_v2.py`
  - configurable bounded-hop authority for reconstructed navigation bearing;
  - derived estimates still cannot force STOP.
- `policy_v2_live_candidate/scripts/round_trip_eval.py`
  - active-mode validation and explicit arming;
  - scores expanded probes;
  - atomically applies support directives;
- pauses route-derived navigation consumers in VLM-only mode while keeping the
  terminal evidence state machine active;
  - logs every support transition and VLM-only pass-through.

The checked-in policy is deliberately an unapproved template.  A reviewed copy
must set `enforcement_approved=true`, and the command must also include
`--reliability_v11_anchor_support_recovery_active_armed`.  This prevents an
unreviewed live launch while leaving the implementation complete and testable.

## Verification

Targeted regression result:

```text
76 passed in 0.18s
```

Coverage includes:

- current-good/next-bad reconstruction and promotion block;
- current-bad/next-good no-veto behavior;
- exact five-step alternating pair sequence;
- VLM-only probe pool from `next-1` through A0;
- trusted-probe recovery;
- independent support-role application;
- blacklisted anchor remaining probe-eligible;
- geometry reconstruction provenance;
- bounded multi-hop bearing authorization;
- explicit expanded-probe role preservation.

All modified Python modules also pass `py_compile`.

The full isolated-tree run reports `110 passed, 2 failed`.  The two broader
checks below are not candidate regressions:

- the isolated candidate intentionally does not copy the historical
  `prospective_v1_1.npz` dataset required by one portable-parity test;
- the pre-existing active-scan-plan duration test expects 9 seconds while the
  current unchanged scan policy produces 12 seconds.  Scan code was not
  modified and is outside the new active path.

## Active-50 isolation check

The frozen Active-50 source hashes remained:

```text
23cea0bedaf69434a4aa0d7b6abe00d1a361b49a9eaa82764c2f623cf3462065  v11_integrated_anchor_state.py
3f29596146143fbc7628f76c740895d4e45c909dadf942e75e379ab349f9c498  v11_integrated_candidate_selector.py
8cec196b8aa39520105ddd0f1a5ba8e0dca32189784b94c073075f7e4c504b1a  v11_integrated_candidate_controller.py
d1f1c5f924fd05e346ef9c027977046290f42539c124c0e37c1d407888184cb1  route_memory_agent.py
```

The latest batch log shows 48 summary rows including infrastructure retry
rows, with ep785's second attempt started but no longer running at the time of
this implementation check.  No residual process was modified or killed while
implementing this candidate.

## 2026-07-28 live follow-up

ep89 exposed an out-of-range recovery request on a short route:
`unknown V11 support current anchor 6`. The runtime now receives the available
anchor-index set, skips every invalid recovery pair, retains the last valid
pair and enters VLM-only probing if no later valid stage exists. Missing route
anchors are treated as missing evidence, not a fatal invariant.

The fixed run crossed the old crash point and continued until it was
deliberately terminated after a separate pre-STOP blind-navigation loop was
proven. The short-route boundary case is covered by regression.

The exact 50-episode policy copy and hash-locked runner are in
`../2026-07-28-anchor-stop-active50-readiness/`. Scan is observer-only and all
obsolete integrated active-controller paths remain off.
