# NaVILA learned anchor/terminal/hint-action controllers

## Status

The first models were trained on 2026-07-29. They are offline/shadow
candidates, not active control policies. Training did not modify or attach to
the live evaluator.

All models use only fields available to the return controller at inference
time. Rows whose route-memory source or backend contained oracle/Isaac
information were excluded before fitting.

The artifacts were trained and smoke-tested with scikit-learn 1.7.2 in:

```text
/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac
```

## Anchor-transition model

Artifact: `models/v1/anchor_transition_v1.joblib`

SHA-256:
`4d37f9bcb341f093d4cdc87e92c041db7d582a912acdb629963039cf7b27dc55`

Classes: `advance_one`, `hold`, `rebase`, `rollback`, `skip_or_rebase`.

| Split | Scene | Balanced accuracy | Macro F1 | ROC AUC |
|---|---|---:|---:|---:|
| validation | EU6Fwq7SyZv | 0.7346 | 0.7155 | 0.9028 |
| test | zsNo4HB9uLZ | 0.7710 | 0.7708 | 0.9531 |

The training balanced accuracy is 0.9830, so the cross-scene gap is material.
Use the model first to log recommendations beside the deterministic
controller. It should not directly advance, skip, roll back, or rebase anchors
until episode-level shadow evaluation shows that mistakes do not create
guidance-loss chains.

## Terminal-decision model

Artifact: `models/v1/terminal_decision_v1.joblib`

SHA-256:
`1b7bbc2fab5211c9b6422c70103735b89a8f3d75fa7c23beacfb8ea3b64cab84`

Classes: `arrived`, `boundary`, `far`.

| Split | Scene | Balanced accuracy | Macro F1 | ROC AUC |
|---|---|---:|---:|---:|
| validation | EU6Fwq7SyZv | 0.6943 | 0.7165 | 0.9145 |
| test | zsNo4HB9uLZ | 0.7368 | 0.7534 | 0.9807 |

The held-out test per-class F1 scores are 0.8503 for `arrived`, 0.4267 for
`boundary`, and 0.9833 for `far`. The weak boundary class is expected from its
small support, but it is precisely the safety-critical ambiguity region.

The arrived threshold selected to have zero false positives on the validation
scene did not generalize: it produced 16 false-arrived decisions on the test
scene, 13 of them on true `far` rows. Therefore the bundle's threshold is a
diagnostic calibration result, not an approved stop policy. The terminal model
must remain shadow-only; deterministic geometric gates keep final authority.

## Hint-action decision v1

Artifact: `models/v1/hint_action_decision_v1.joblib`

SHA-256:
`1851c727534f943396c7f74ec6b47f8da0695753cb0edc17fd957cdc532f03ca`

This model answers a separate question from anchor trust: when VLM movement
and the route hint conflict, should movement follow the hint, keep the VLM
action, or abstain? It does not control STOP and cannot bypass collision
clearance.

The dataset has 3,991 rows from 280 episodes and 9 scenes. On the held-out
test scene, three-class balanced accuracy is 0.4870 and macro F1 is 0.4808.
This is not sufficient for active control. At the validation-selected
operating point, however, held-out `override_hint` precision/recall are
0.7464/0.4711 versus 0.6466/0.3905 for the historical bearing-trust gate.

On four scoreable unseen prospective episodes, weighted intervention recall
improves from 0.3000 to 0.6429 while precision changes from 0.9130 to 0.9000.
Episode 1008 contains two weighted false interventions, so the artifact
remains shadow-only.

Hint v2 experiments separate route recommendation from the mandatory
clear-path gate and use leave-one-scene-out calibration. The three-class v2
became effectively inert. The binary v2 is the useful successor:

- development OOF advisory precision/recall: 0.8514/0.3425;
- untouched test advisory precision/recall: 0.8410/0.3723;
- prospective 5ep advisory precision/recall: 0.9655/0.4000;
- prospective ep1008: four correct recommendations and zero false override.

Its strict zero-OOF-false-positive execution policy makes no prospective
interventions, so v2 is also shadow/advisory-only.

## Terminal-decision v2 robust

Artifact: `models/v2/terminal_decision_v2_robust.joblib`

SHA-256:
`f033696bf632134c48edf3ce1734850833c98a93bfdadc7173780ef5ebef6bbb`

V2 removes absolute anchor/source/target indices, uses leave-one-development-
scene-out predictions to freeze a 0.7133 threshold with a four-query
confirmation streak, and increases boundary/arrived-without-stop weighting.
Its held-out test balanced accuracy/macro F1 are 0.7416/0.7095.

The sequence gate has zero true-far false-arrived decisions in every
development scene, but five on the untouched test scene. It therefore fails
the activation gate and is only a probability sensor. On the five-episode
prospective cohort it makes no false-far confirmation, but it misses every
arrived row in ep319.

## Reproducibility and reports

Dataset hashes:

- anchor: `6184b46465c59d816d2eaf2364a97ee02b24c5316af79b5cf2164fd1f17ce0f6`
- terminal: `c95f7243ad7e1971e01a906400420b1800420067ca6738aef086b30df925c1c7`

The full weighted confusion matrices, class reports, calibration results,
artifact validation, scene splits, and provenance are in:

- `reports/v1/training_report.md`
- `reports/v1/training_report.json`
- `reports/v1/hint_action_training_report.md`
- `reports/v1/hint_action_training_report.json`
- `reports/v2/terminal_v2_robust_report.md`
- `reports/v2/hint_action_v2_binary_report.md`
- `reports/v2/hint_action_v2_followup.md`
- `reports/v2/prospective5_hint_terminal_v2.md`
- `reports/v2/wider_candidate_pilot.md`
- `data/v1/DATA_CARD.md`
- `data/v1/audit.json`
