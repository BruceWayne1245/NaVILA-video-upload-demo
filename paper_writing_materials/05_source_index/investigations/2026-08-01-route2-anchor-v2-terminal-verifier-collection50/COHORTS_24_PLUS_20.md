# Route 2 Core development24 + locked-validation20

## Purpose and separation

The old collection50 was stopped after the architecture defect was confirmed.
It was not allowed to continue as though it were V1.1-core evidence. Two new
cohorts were frozen before execution:

1. **development24** collects on-policy diagnostic/training evidence and may
   enter a future training split after cleaning;
2. **locked-validation20** is opened once for a frozen prospective evaluation
   and may never enter training, feature choice, threshold tuning, early
   stopping or policy selection.

The cohorts run separately and preserve independent tags, manifests,
provenance and scoring. After both Route 2 cohorts, the pre-existing Route 1
quarantine-veto30 remains last in the chain; it is not pooled with Route 2.

## Development24

- 24 episodes across all nine dataset scenes;
- 12 medium and 12 long routes;
- historical totals include 50 outbound successes and four return successes;
- six physical episodes intentionally overlap old development training and may
  provide future training evidence;
- zero physical-ID or exact-geometry overlap with the canceled current50;
- manifest SHA:
  `35e06e51ebb0747e4d5a9fcadb843298766ee5a81cc384892ce51337afb29fd1`.

Each valid completion records V1.1 bearing/distance/pose envelopes, Anchor Core
online shadow outputs, every return query, separate Terminal observations and
direct-distance labels, post-episode Terminal/Hint scores, A0 probes and
action-integrated query-to-query motion.

## Locked-validation20

- 20 never-attempted physical episodes;
- 12 long and eight medium routes;
- zero overlap with old training IDs, current50 IDs, canonical historical
  attempt IDs, development24 IDs and excluded exact geometry;
- zero route-pair overlap with current50 or development24;
- the strictly fresh remaining pool covers four scenes only; this is disclosed
  and is not represented as nine-scene validation;
- manifest SHA:
  `4faafb4bec7e36505fd46a0f2060bb0ec9a6046556de36a2013809820f807ef0`.

## Cohort seal and authorization history

The lock artifact was created before execution with
`execution_authorized=false`, `queue_authorized=false` and state
`sealed_before_execution`. This records the state at seal time, not the later
decision. The user subsequently gave explicit authorization to cancel the old
50 and launch development24 followed by locked-validation20.

Evidence manifest SHA:
`62aa9cc37dede5ac8527758b3a9e9e096ac6f2aca0f51022d9f01ed1706f44a4`.

The exact manifests, selection evidence, lock and selection tool are archived
under `core_correction/`.

## Runtime contract

- Reliability V1.1 core inference and consumer enforcement: active;
- Anchor Core V1: online shadow, zero controller effect;
- Terminal Core V1: post-episode shadow/export;
- Hint Core V1: post-episode bounded shadow scoring;
- raw ICP reliability authority: forbidden;
- development24 completes before locked-validation20 begins;
- no locked20 outcome is inspected for tuning.

The separately recorded pending architecture proposal must not be hot-patched
into this frozen run. Development24 can generate hypotheses; the candidate and
all thresholds must be frozen before locked20 is opened.
