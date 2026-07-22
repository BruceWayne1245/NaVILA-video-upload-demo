# V1.1 prospective capture-shadow 100ep protocol (2026-07-22)

Status: **predeclared handoff; not chained or scheduled**. The short-lived
automatic chain was explicitly cancelled on 2026-07-22 so Claude can first
finish and freeze the next non-model controller changes.

## What this run is

This is a prospective, capture-based shadow test of the frozen Reliability
V1.1 development artifact. The model is not loaded in Isaac, emits no online
decision, and cannot alter navigation. After the run, the exact captured
current/next ICP records are transformed causally and scored offline with the
frozen artifact.

The sole controller will be Claude's finalized non-model integrated
sequential-pair configuration. The template begins from the A+B+C reliability
fix used by `reliability_fixon_100ep_20260721_accumulated`, but Claude must
record any subsequent changes before launch. The pre-2026-07-14 oracle is not
the controller.

## Frozen inputs

- V1.1 repository code commit before predeclaration: `bb457488653e386b284bef8e1bcb6f45094d8868`
- V1.1 development artifact SHA-256:
  `5f23aba46a45d564131dccd093b1e76160a513162910709503ac8c0a49cb35ce`
- V1.1 development dataset SHA-256:
  `f5dd5ed86e776f9c3ae8efc6e8a2e9f8f1bcce8b0f793dc16115dc7d80494133`
- The template's current live-code hashes describe the 2026-07-22 A+B+C
  baseline. Claude must replace them with his finalized hashes; those become
  frozen before launch.
- Frozen episode list: `episodes.tsv`.
- Episode-list SHA-256:
  `60d2adf33efeaeb985dc2b234a284a4698ff69160b2a284adfa0ed060b1c60c7`.
- Run tag:
  `reliability_v11_prospective_capture_shadow_100ep_20260722_accumulated`.

No model, feature, calibrator, threshold, label, exclusion rule, or episode may
be changed after aggregate outcomes from this batch are opened. Any later
change creates V1.2 and requires a new prospective batch.

## Episode selection

The full 1,077-episode source set was screened only for the existing
deterministic reverse-path-neighbor eligibility rule. All 100 physical CLI
episode IDs used by the current batch were excluded; these include all 56
physical IDs used to develop V1.1. From the remaining 596 eligible IDs, each
scene list was deterministically shuffled with seed `20260722`, then sampled
round-robin by scene.

The final allocation is 15/15/15/14/14/13/14 across the seven scenes with
remaining candidates. These are fresh episodes, not fresh scenes; this batch
does not establish unseen-scene generalization.

## Controller and capture

- `route_hint_source=integrated`
- `route_relocalization_backend=sequential_pair`
- the template starts from the canonical closure, report-next, stale
  suppression, stop-gate anchor corroboration, promotion, short-baseline, and
  A+B+C settings of the running fix-ON batch
- Claude's later non-model changes must be documented and frozen in the final
  runner; they may control navigation, while V1.1 may not
- `capture_icp_replay_dataset` enabled
- V1.1 online inference absent; every V1.1 enforcement field is therefore
  structurally false
- A pure VLM-server startup failure (`exit_code=98`) receives at most one
  predeclared retry after a 120-second cooldown. No navigation failure, model
  score, label, or outcome can trigger a retry or replacement episode. Both
  infrastructure-attempt rows remain logged and share one physical-episode
  cluster.

## Primary analysis

The independent statistical unit is the physical CLI episode ID. Candidate
rows and repeated attempts are clustered within episode. For bearing,
distance, and pose, report AUC, AP, calibration, trusted coverage, empirical
trusted bad rate, and one-sided 95% physical-episode-cluster bootstrap upper
bounds. Apply the already frozen gates in
`../2026-07-21-icp-reliability-signal/model_versions/v1_1/reports/V11_PROSPECTIVE_PROTOCOL.md`:

| Head | Minimum AUC | Maximum trusted bad-rate UCB | Minimum trusted coverage |
|---|---:|---:|---:|
| bearing | 0.80 | 10% | 35% |
| distance | 0.92 | 5% | 35% |
| pose | 0.96 | 5% | 30% |

Also report episode-macro, scene-macro, worst-scene, current-role, next-role,
and early/middle/late-return slices, plus a joint operating point. No row-level
confidence interval may be treated as independent evidence.

## Integrity and secondary outcomes

Required integrity gates are zero required-feature capture drops, exact
attempt/step linkage, no causal history crossing episode or anchor boundaries,
and at least 100 labels recomputed from raw robot/anchor poses with zero
mismatch. Missingness, unseen-category drift, and unusable episodes stay in the
operational denominator.

Navigation outbound/return/round-trip success and controller events are
secondary descriptive outcomes. They cannot demonstrate a model benefit in
this batch because the model has no control authority.

Passing the statistical gates still does not authorize model control. A later
online shadow canary must establish portable-runtime parity, causal-state
parity, logging completeness, exceptions/NaNs, and latency before a separately
reviewed consumer-policy experiment.
