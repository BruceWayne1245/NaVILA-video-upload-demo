# Findings as of 2026-07-23

## 1. What is already established about V1.1

The frozen artifact was evaluated prospectively without refitting,
recalibration, threshold changes, or post-outcome episode replacement.
The usable model cohort contains 37,189 raw candidate rows from 59 physical
episodes and seven previously represented scenes.

All pooled metrics below use physical-episode-balanced weights. Risk upper
bounds are one-sided 95% bootstraps over physical episode IDs.

| Output | AUC | AP | Brier | ECE | trusted coverage | bad rate among trusted | 95% risk UCB |
|---|---:|---:|---:|---:|---:|---:|---:|
| bearing | 0.9196 | 0.8674 | 0.1087 | 0.0256 | 44.90% | 4.68% | 7.70% |
| distance | 0.9453 | 0.8899 | 0.0765 | 0.0165 | 45.79% | 0.95% | 1.32% |
| pose | 0.9743 | 0.9585 | 0.0442 | 0.0094 | 40.48% | 1.29% | 1.89% |

At the all-three-head joint operating point, coverage is 39.93%, empirical
pose-bad risk is 0.89%, and its cluster-bootstrap upper bound is 1.34%.

This is strong evidence for the narrow claim that V1.1 distinguishes many good
and bad raw ICP readings. It is not a navigation-effect estimate.

## 2. Important limitations in that evidence

The 100ep prospective batch did not pass its frozen capture-integrity gate:

- ep264 has two syntactically corrupt required frame JSON files;
- ep324 wrote 595 frames after entering return but did not persist a
  reconcilable measurement or trajectory;
- therefore the formally required zero-drop/exact-linkage condition failed.

Those defects do not make the other 37,189 rows useless. They mean the batch is
positive statistical evidence rather than a formal prospective acceptance
cohort. No corrupt file was repaired and no unfavorable episode was silently
removed to manufacture a pass.

Generalization is also bounded. The cohort provides fresh episodes but no
unseen scenes. Scene `EU6Fwq7SyZv` is a warning slice: bearing AUC is 0.758 and
the empirical bearing-bad rate inside its trusted subset is 34.55%. This is one
reason that global enforcement is not justified by the pooled result alone.

## 3. Online portable-runtime evidence

The official 5ep retry2 online shadow canary completed 5/5 processes with exit
code zero. Three episodes reached return scoring; two did not and therefore
contain no V1.1 score rows.

Across the three evaluable episodes:

- 698 model calls and 1,244 candidate rows;
- zero feature mismatches;
- maximum frozen probability difference from offline rescoring: 0;
- zero trusted-flag mismatches;
- zero runtime exceptions, non-finite probabilities, or controller-contract
  violations;
- average observed call latency about 3.26 ms;
- per-episode p99 latency 3.85–3.87 ms;
- maximum observed latency 3.91 ms.

Per-episode validation is stored under
`data/online_canary/validations/`. ep448 and ep691 are explicitly classified
as `not_evaluable_no_score_rows`, not failed model episodes.

Navigation was 3/5 round trips in this tiny canary. Since V1.1 was shadow-only,
that outcome belongs to the existing controller and cannot be attributed to
the model.

## 4. What the proposed consumer would have done

The old canary logs did not contain inline oracle truth and predated the new
decision-event schema, so replay is an interface/availability smoke test only.
Applying the frozen `role-safe-precontroller-joint-trust-v1` rule to its 698
score calls gives:

| Counterfactual action | Count | Share |
|---|---:|---:|
| defer the whole relocalization update because current is untrusted | 331 | 47.42% |
| forward trusted current only | 213 | 30.52% |
| forward trusted current and trusted next | 154 | 22.06% |

Thus a current candidate would be forwarded on 367/698 attempts, or 52.58%.
A next candidate would be forwarded on 154/698 attempts, or 22.06%.

The episode distribution is highly heterogeneous:

| Physical episode | full defer | current only | current + next | attempts |
|---:|---:|---:|---:|---:|
| 579 | 241 | 81 | 19 | 341 |
| 539 | 23 | 121 | 92 | 236 |
| 688 | 67 | 11 | 43 | 121 |

This is exactly why model AUC alone cannot authorize hard gating. The consumer
may remove nearly half of all updates overall and far more in a particular
episode. The next 100ep must measure false admits, false defers, first-use
availability, consecutive defer streaks, and scene heterogeneity for the exact
policy.

The replay also found 328 attempts where the existing controller selected an
untrusted candidate, 190 with a jointly trusted alternate available, and 129
with a lower predicted-pose-risk alternate. These are disagreement counts, not
proof that switching identity would be safe. The frozen policy deliberately
does not replace a bad/missing current with next.

## 5. Route-1 result is a separate question

In the earlier 100ep non-model Route-1 batch:

- reported outbound success was 43/100;
- official round-trip success was 17/100;
- trajectory truth found 19 physical final-position successes among the 43
  outbound-success episodes, with 42 evaluable return trajectories;
- ep366 and ep844 ended within 3 m but were not official return successes.

These navigation figures describe Route 1, not V1.1. The earlier 12/19 snapshot
and this 19/43 outcome used different, unpaired episode cohorts, so their
difference cannot establish causal benefit or harm from other controller
changes.

## 6. Root-cause boundary

The latest 2026-07-23 investigation shows that scalar reliability cannot
separate every confidently-wrong rotationally symmetric ICP solution: a wrong
basin can have clean-looking geometry. V1.1 can still suppress a large fraction
of risky observations and protect irreversible consumers, but visual rotation
verification is required for the unresolved failure family.

## 7. Current conclusion

The evidence supports all of the following:

1. V1.1 is technically portable and fast enough for the current online loop.
2. Its frozen outputs reproduce offline exactly on the evaluable canary rows.
3. It is a strong selective classifier of raw ICP reliability on represented
   scenes.
4. The exact active consumer and its availability cost remain unvalidated.
5. A decision-complete shadow run, followed by a guarded active canary, is the
   shortest defensible route to genuine control participation.

It does **not** support claiming that V1.1 already improves round-trip success,
that all scenes are covered, or that a finite shadow run can prove active
safety.

