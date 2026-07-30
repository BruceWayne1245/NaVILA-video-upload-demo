# Findings and analysis

## 1. Anchor Transition V1

Anchor Transition V1 remains a narrow promotion guard, not a selector.  It
may only counterfactually defer an already-authorized adjacent promotion on
the following attempt when its `rollback` or `skip_or_rebase` probability is
at least 0.90.  It permits at most two deferrals and then fails open.  The
current batch configuration is shadow-only.

The 12 scoreable Shadow30 episodes contain:

- 86 promotion-like next-index decrements;
- 9 lagged high-confidence candidate vetoes;
- 8 harmful-promotion catches;
- 0 safe delays.

This is encouraging but insufficient to activate.  Ep670 must first be
treated as a replication-only check.  If it is a genuine isolated outlier
and fresh evidence continues to satisfy the registered safety gates, there
is no reason to redesign V1 solely around that episode.  If ep670 repeats or
the same failure appears in other scenes/geometries, it becomes a pattern
that must be addressed before active use.

Activation remains contingent on:

- harmful-promotion catch precision at least 0.90;
- safe-promotion delay rate at most 0.05;
- no scene with repeated high-confidence safe delays.

## 2. Hint v3 bounded evidence recheck

Hint v3 keeps the frozen Hint v2 binary estimator and only requests more
evidence:

- missing clearance plus score at/above the advisory threshold requests a
  clearance refresh;
- clear clearance plus score at/above the execution threshold, with an
  incomplete execution streak, requests a stability rescore;
- occupied clearance always hard-blocks;
- no more than two requests per episode/target;
- at least ten simulator steps between requests;
- no movement and no STOP authority.

Observed performance:

| Evaluation | Requests | Beneficial weight | Non-beneficial weight | Beneficial fraction |
|---|---:|---:|---:|---:|
| Untouched test scene | 23 | 12.25 | 1.75 | 0.8750 |
| Shadow30 scoreable rows | 8 | 6.50 | 1.00 | 0.8667 |

The policy is alive and targets genuine missed opportunities, but the
beneficial fraction has not reached the 0.90 activation requirement.  It
should remain read-only while the unified batch collects fresh evidence.

## 3. Terminal direct-far veto v3

The v3 supervision promoted 1,715 previously zero-weight direct-far query
rows for fitting.  A calibration class-order bug was corrected before the
reported experiment.

The dedicated far-veto model has development OOF AP 0.9333 and ROC AUC
0.8530.  Those ranking metrics do not translate into a safe operating point:

- the zero-direct-far development threshold has arrived recall 0.0000;
- on the untouched test, direct-far confirmations fall from 24 to 4, while
  arrived recall falls from 0.2692 to 0.0511.

The model is rejected.  The current scalar/runtime features do not separate
correct terminal tails from visually similar far tails well enough to use a
hard veto.

## 4. Why Terminal should not be globally bound to Anchor0

The current gate has two positive paths:

1. repeated fresh Route2-trusted `next/raw` distance intervals entirely
   inside the arrival radius;
2. when route evidence is blind, repeated VLM STOP plus repeated Anchor0
   visual confirmation.

Anchor0 is place recognition, not ground-truth metric localization.  It is
not sufficient: the legacy fallback accepted ep640 at 4.319 m and ep783 at
3.618 m.  Repeating the same view does not make a correlated perceptual alias
independent.

Anchor0 is also not necessary.  Success is a radius rather than the exact
initial camera pose, and valid arrival can differ in yaw, occlusion, lighting,
or descriptor availability.  The diagnostic A0 threshold of 0.60 with a
two-query streak removed the two observed direct-far accepts but also removed
the valid ep189 accept.  Ep189 was not a missing STOP publication in the
historical gate: it accepted at step 3391, distance 2.645 m.

The recommended hierarchy is therefore:

1. hard rules for freshness, provenance, current/next role, raw versus
   reconstructed evidence, and OOD/missingness;
2. a fresh trusted definitely-far interval may veto a proposal, but the veto
   must expire;
3. repeated fresh trusted raw-near evidence may accept without Anchor0;
4. route-blind cases enter bounded stationary verification using Anchor0,
   VLM, motion and Terminal evidence together;
5. Anchor0 corroborates but cannot alone publish STOP; unresolved evidence
   ends in explicit safe-fail.

## 5. Meaning of `anchors_missing`

The Shadow29 scorer's `SkipEpisode:anchors_missing` means the completed result
does not contain `icp_replay_dataset/anchors.json`.  It does **not** mean that
route-memory produced no anchor observations.

- Retry1 ep953 started inside the outbound success radius, ended after one
  command, and had no replay anchors.
- Retry2 ep49 produced 1,807 trajectory records and its measurement contained
  15 route-memory anchors, but it did not complete outbound/return and thus
  never wrote the replay dataset expected by the strict scorer.

The scorer should remain strict for model metrics.  The orchestration gate
should not confuse “unscoreable for this replay analysis” with
“infrastructure failed.”  Non-return and short-run cases are valid system
outcomes and must be retained.  Future canaries must not be selected for
likely return completion, because that would create selection bias.

## 6. Unified batch interpretation

The unified batch deliberately obtains one physical trajectory per episode
and evaluates Anchor, Hint, and five Terminal/A0 policies without control
authority.  It contains one non-pooled ep670 replication and 49 fresh,
geometry-deduplicated routes across eight scenes.

No experimental result exists yet.  The first launch failed during VLM
checkpoint startup; retry1 failed on a Python package namespace collision
before trajectory creation.  The frozen cohort and policy thresholds must
not be changed while repairing that infrastructure issue.
