# Route 2 Core V1 episode protocol

Two cohorts are prepared and sealed. Nothing has been launched, queued, or
attached to the currently running 50 episodes.

## Development: 24 episodes

Purpose: collect on-policy training evidence, especially for Terminal. The
selection favours routes with at least one historical outbound success and low
return yield, while excluding every physical episode and exact geometry in the
current 50. It covers all nine dataset scenes. These captures may be cleaned
and added to a future training split.

Each completed episode records:

- full ICP replay and per-candidate Reliability V1.1 bearing/distance/pose
  outputs;
- Anchor Core V1 online shadow predictions with no controller effect;
- every return query, including background, near-threshold,
  threshold-preconfirmation, first candidate, and candidate tail;
- physically separate Terminal observation and direct-distance label files;
- post-episode Terminal and Hint Core V1 shadow scores;
- A0 visual-probe evidence and action-integrated motion since the prior query.

## Locked validation: 20 episodes

Purpose: one prospective check of the frozen artifacts and policies. At seal
time, physical episode IDs and exact path geometries had zero overlap with the
old training corpus, current 50, canonical historical attempts, and development
cohort. Route pairs also have zero overlap with the current 50 or development
cohort.

The remaining never-attempted reverse-route pool exists only in four scenes,
so this cohort covers `2azQ1b91cZZ`, `QUCTc6BB5sX`, `TbHJrupSAjP`, and
`zsNo4HB9uLZ`. It is a prospective physical-episode validation set, not a claim
of nine-scene coverage. Its outcomes cannot enter training or tune thresholds.

## Execution boundary

`launch/run_route2_core_cohort.sh` runs static preflight by default and has no
queue/wait mode. It accepts only explicit `--launch-development` or
`--launch-locked-validation`. Before a launch it refuses to run if any existing
`round_trip_eval.py` process is present; it never stops that process. Thus the
later choice to stop the current 50 or place these cohorts behind it remains a
separate user decision.

The runtime contract is:

- Reliability V1.1 core consumer: active.
- Anchor Core V1: online shadow, no controller effect.
- Terminal Core V1: post-episode shadow proposal/export.
- Hint Core V1: post-episode bounded shadow scoring.
- raw ICP reliability authority: forbidden.

The cohort lock records `execution_authorized=false` and
`queue_authorized=false`; explicit launch authorization is still required.
