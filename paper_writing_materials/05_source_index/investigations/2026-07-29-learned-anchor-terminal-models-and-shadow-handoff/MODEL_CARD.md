# NaVILA learned anchor/terminal controllers v1

## Status

The first models were trained on 2026-07-29. They are offline/shadow
candidates, not active control policies. Training did not modify or attach to
the live evaluator.

Both models use only fields available to the return controller at inference
time. Rows whose route-memory source or backend contained oracle/Isaac
information were excluded before fitting: 3,260 anchor rows and 291 terminal
rows.

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

## Reproducibility and reports

Dataset hashes:

- anchor: `6184b46465c59d816d2eaf2364a97ee02b24c5316af79b5cf2164fd1f17ce0f6`
- terminal: `c95f7243ad7e1971e01a906400420b1800420067ca6738aef086b30df925c1c7`

The full weighted confusion matrices, class reports, calibration results,
artifact validation, scene splits, and provenance are in:

- `reports/v1/training_report.md`
- `reports/v1/training_report.json`
- `DATA_CARD.md`
- `data/v1/audit.json`
