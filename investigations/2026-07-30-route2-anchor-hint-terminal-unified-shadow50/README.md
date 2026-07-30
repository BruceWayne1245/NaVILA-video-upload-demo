# Route 2 — 2026-07-30 Anchor / Hint / Terminal handoff

## Scope and authority

This directory records the Route 2 work completed on 2026-07-30: analysis of
the scored Shadow30 subset, bounded Hint and Terminal follow-up, the
Anchor0/Terminal evidence-binding decision, preparation of a unified
50-episode read-only batch, and the two infrastructure failures encountered
before that batch could produce a trajectory.

The work was based on the authoritative GitHub state at commit
`a1d50470ccc9c522d95ed76646ce10f6d3c04684`.  Local historical README copies
were not used as authority.  Before any future runtime change or resumed
batch, re-read the latest GitHub README and its newer investigations and
verify that the runtime candidate still matches them.

## Executive status

- **Anchor Transition V1:** keep frozen and shadow-only.  Shadow30 gives eight
  harmful-promotion catches and zero observed safe delays, but only 12
  episodes are scoreable.  Ep670 remains replication-only; no 2026-07-30
  Anchor result was obtained.
- **Hint:** retain the bounded v3 evidence-recheck policy as a read-only
  candidate.  It has no movement or STOP authority.  The observed beneficial
  fractions are 87.50% on the untouched test scene and 86.67% on the
  scoreable Shadow30 rows, below the preregistered 90% activation gate.
- **Terminal direct-far veto:** reject the v3 estimator.  It removes many
  direct-far confirmations but destroys arrived recall.
- **Terminal and Anchor0:** do not globally require Anchor0 for arrival.
  Anchor0 is useful corroborating evidence in route-blind verification, but
  is neither a necessary nor sufficient arrival condition.
- **Unified 50-episode batch:** frozen and ready in design, but **not yet
  executed**.  Both canary attempts stopped before any valid trajectory.  The
  fresh49 cohort never started.
- **GPU/runtime status at handoff:** no valid batch process is running; the
  last service exited failed at 2026-07-30 11:33:28 BST.

## Retry2 repair and queue update

The namespace and false-clean-exit defects were repaired later on
2026-07-30.  The frozen experiment is queued behind Route 1's corrected
unseen30 v2 batch.  See `repair_retry2/README.md` and
`runtime_status/RETRY2_QUEUE.md`; the original handoff snapshot above remains
the audit record of the two failed attempts.

## Most important numbers

| Area | Result | Decision |
|---|---:|---|
| Shadow30 scoreable episodes | 12 | too small for activation |
| Anchor promotion-like decrements | 86 | audit population |
| Anchor high-confidence lagged vetoes | 9 | candidate catches |
| Anchor harmful catches / safe delays | 8 / 0 | validate on fresh data |
| Hint untouched-test beneficial fraction | 12.25 / 14.00 = 87.50% | shadow-only |
| Hint Shadow30 beneficial fraction | 6.50 / 7.50 = 86.67% | shadow-only |
| Terminal far-veto untouched-test arrived recall | 0.2692 → 0.0511 | reject |
| Terminal far-veto direct-far confirmations | 24 → 4 | recall cost unacceptable |
| Legacy A0 fallback Shadow30 accepts | 5 arrived / 1 boundary / 2 far | unsafe |
| A0 ≥ 0.60, streak 2 diagnostic | 4 arrived / 1 boundary / 0 far | loses ep189; not validated |
| Unified cohort | ep670 replication + 49 fresh | zero episodes executed |

## Directory map

- `reports/hint_terminal_v3_decision.md` — frozen Hint v3, rejected Terminal
  far-veto, and A0 threshold diagnostic.
- `reports/anchor0_terminal_binding_analysis.md` — reasoning and recommended
  conditional evidence hierarchy.
- `reports/shadow30_missed_opportunities.md` — compact Shadow30 audit.
- `FINDINGS.md` — integrated analysis and episode-level interpretation.
- `CHANGES_AND_WORKLOG.md` — actual code/data changes and failure chronology.
- `UNIFIED50_PROTOCOL.md` — cohort design, isolation rules, and preregistered
  gates.
- `runtime_status/SNAPSHOT.md` — exact handoff state and blocker.
- `NEXT_STEPS.md` — ordered continuation plan.
- `data/` — frozen 50-episode manifest and JSON policy definitions.
- `code/` — exact small runtime/scoring/launch snapshots used today.
- `tests/` — focused regression tests from the isolated candidate.
- `repair_retry2/` — collision-free runtime, strict capture validation,
  retry2 tests, and exact launch/queue scripts.
- `ARTIFACT_MANIFEST.sha256` — integrity hashes for every archived artifact.

## Safety statement

No learned component was activated today.  No Anchor decision changed route
state, no Hint decision changed movement, and no Terminal counterfactual
published STOP.  Ground-truth distance was reserved for post-episode scoring.
No credential, model binary, simulator log bundle, video, or private token is
stored in this investigation.
