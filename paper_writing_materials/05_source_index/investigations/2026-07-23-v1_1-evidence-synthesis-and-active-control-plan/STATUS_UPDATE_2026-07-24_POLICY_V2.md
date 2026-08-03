# 2026-07-24 evidence and plan update: Policy V2

GitHub authority used for this update: private repository `main` at
`63f541df43de7e393f83513add855736fb20929b`.

This is an append-only update to the frozen 2026-07-23 evidence package. The
original `DATA_MANIFEST.sha256`, findings, gates, and Policy V1 plan remain
unchanged historical evidence. This file records the later partial-data audit,
the Policy V2 design decision, and the operational handoff.

The full implementation, hashes, runner behavior, and acceptance contract are
recorded in:

`../2026-07-23-v1_1-control-readiness-shadow-handoff/STATUS_UPDATE_2026-07-24_POLICY_V2.md`

## Updated bottom line

The current evidence separates two questions:

1. **Is V1.1 useful?** Yes, as a selective signal for whether a downstream
   consumer should trust the authoritative raw ICP anchor.
2. **Is the original whole-update Policy V1 consumer usable?** No. Its
   starvation behavior is too severe to make it the active-control target.

This does not reverse the 2026-07-23 model conclusion. It changes the consumer
architecture.

## Current-data model audit

At the audit snapshot, the running 100ep batch had produced 72 result
directories. Forty episodes were integrity-valid and contained scoreable
return decisions; 26 valid episodes contained no return rows; four had
unparseable measurement JSON; and two lacked completion manifests.

Across the 40 eligible episodes:

| Metric | Result |
|---|---:|
| scoreable current rows | 10,327 |
| jointly trusted current coverage | 48.21% |
| pose-bad block recall | 99.37% |
| trusted current pose-bad rate | 0.603% |
| one-sided 95% Wilson risk upper bound | 0.812% |

This supports model usefulness for bounded downstream guarding. It is not a
formal readiness pass because the batch was incomplete, known integrity
failures were present, and the cohort was inspected during policy design.

## Consumer-policy decision

Policy V1 hard-filters raw current/next candidates before
`RouteMemoryAgent`. In the representative replay it would defer 3,768 of
7,375 reversible relocalization updates, with an extreme episode-level
untrusted streak of 900 attempts.

Policy V2 therefore preserves all baseline candidates and reversible
relocalization. It counterfactually guards only:

- anchor promotion;
- route-hint injection;
- hint-action override;
- forced stop;
- VLM-stop veto.

The authoritative anchor's frozen V1.1 `jointly_trusted` result is the only
model field used by the guard. There is no `next`-for-`current` substitution,
pose edit, identity override, or oracle input.

## Policy V2 replay evidence

The deterministic 24ep replay spans seven scenes, 15 return successes and nine
return failures, low/medium/high risk and trust, and 41–1001 decisions per
episode.

| Operation | Requests | V2 vetoes | Pose-bad veto recall | Pose-good allow rate |
|---|---:|---:|---:|---:|
| relocalization update | 7,375 | 0 | n/a | 100.0% |
| anchor promotion | 126 | 31 | 96.67% | 97.92% |
| route hint | 624 | 356 | 99.69% | 89.90% |
| hint-action override | 99 | 5 | 100.0% | 100.0% |
| forced stop | 12 | 3 | 100.0% | 100.0% |
| VLM-stop veto | 26 | 13 | 100.0% | 100.0% |

There were zero Policy V2 relocalization defers, zero fail-open episode
disables, and zero shadow controller effects. This is sufficient to justify a
prospective online shadow integration test. It does not authorize active
enforcement.

## Implementation status

Policy V2 was implemented only in an isolated copy of the exact live sources:

- `round_trip_eval.py`: Policy V2 CLI/session/event wiring and final
  pre-execution hooks;
- `route_memory_agent.py`: a promotion callback immediately before identity
  commit;
- `v11_consumer_policy_v2.py`: stateful bounded guard with fail-open episode
  disable;
- `v11_consumer_policy_v2.json`: frozen shadow/no-enforcement artifact.

Verification completed with Python compilation plus 152 passed and 14 skipped
tests. The active mode cannot load the current artifact because it declares
`mode=shadow` and `enforcement_approved=false`.

No active Live file was changed while the original 100ep service was running.

## Online 24ep shadow handoff

The frozen episode order is:

```text
3 87 93 95 196 205 264 333 351 387 420 448
579 654 671 682 687 715 764 815 888 890 962 987
```

The online shadow batch is attached to a detached user-systemd handoff:

- waiting unit:
  `navila-v11-policy-v2-shadow-24ep-chain.service`;
- upstream unit:
  `navila-v11-decision-shadow-rgbd-100ep.service`;
- new run tag:
  `reliability_v11_policy_v2_online_shadow_24ep_20260724`;
- armed at:
  `2026-07-24T20:37:22+01:00`;
- status after registration:
  both units `active/running`, with the new unit waiting.

The handoff does not condition on upstream success. It starts after success,
nonzero exit, or bug-triggered terminal failure. It repeats all hash and mode
preflights before launch and restarts itself on failure after 120 seconds.
Closing the conversation or terminal does not stop it.

At registration time the original batch had 76 completed summary rows and was
running physical episode 355. The Policy V2 batch had not started early.

## Updated experiment sequence

### Stage A — finish and audit the current Policy V1 decision-shadow run

Keep the original frozen denominator and post-run order. The final audit must
report every corrupt/missing artifact and cannot manufacture a formal pass
from a selected subset. This final model/readiness analysis can proceed while
the detached Policy V2 shadow batch runs.

### Stage B — 24ep Policy V2 online shadow

Require:

- 24/24 valid completion/provenance records;
- exact online/offline model and Policy V2 decision parity;
- zero candidate, pose, probability, or identity mutation;
- zero V1.1 relocalization-update defers;
- zero controller effects;
- zero model/runtime fail-open disables;
- zero 30-promotion-veto fallbacks;
- no adapter-attributable crash, deadlock, or stuck condition.

The selected cohort is prospective for integration behavior, but it was
selected using revealed Policy V1 data. Navigation outcomes are therefore
descriptive and not a causal or unbiased performance estimate.

### Stage C — reviewed 10ep active canary

Only after Stage B passes:

1. review the isolated diff;
2. freeze a distinct active artifact with explicit enforcement approval;
3. retain the kill switch, fail-open behavior, and high-severity fault logs;
4. run 10 episodes with Policy V2 genuinely affecting the five guarded
   consumers.

Acceptance requires exact executed/logged agreement, 10/10 valid completions,
zero model or policy faults, zero identity mutation, zero fallback activation,
and no new integration-attributable crash/stuck condition.

### Stage D — 100ep active A/B

Only after a clean active canary, run a paired or randomized baseline/Policy
V2 experiment. Round-trip success is the primary endpoint. Guard-specific
risk, false vetoes, promotion behavior, stop errors, fault/fallback counts,
physical episode, and scene remain safety/cluster endpoints.

No replay, partial-data audit, or shadow cohort may be described as evidence
that V1.1 already improves navigation. Visual verification remains necessary
for confidently-wrong symmetric ICP basins that look geometrically clean.
