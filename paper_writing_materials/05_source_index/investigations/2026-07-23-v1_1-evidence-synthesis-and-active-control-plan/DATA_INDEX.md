# Data index and provenance

## Prospective 100ep evidence

`data/prospective_100ep/` contains:

- `prospective_v1.csv`: the complete 37,189-row diagnostic/label dataset;
- `prospective_v1_1.npz`: the complete frozen 249-feature model matrix;
- `row_predictions.csv`: frozen per-row probabilities and trust decisions;
- `prospective_score.json`: pooled, role, episode, scene, and bootstrap
  statistics;
- `navigation_episode_audit.csv`: 100-episode operational/navigation audit;
- `raw_label_audit.csv`: deterministic raw-pose label spot check;
- capture, batch, artifact, parity, model, and dataset manifests;
- `FINAL_REPORT.md`: frozen interpretation and decision.

The raw Isaac episode directories and 97,655 individual capture-frame files
are not copied into Git. Their linkage/parsing results are retained in
`all_capture_frame_validation.json`, `batch_audit.json`, and the dataset
manifests. The complete model-ready datasets and row-level predictions needed
to reproduce all reported model metrics are included.

## Online 5ep canary evidence

`data/online_canary/` contains:

- `summary.tsv`: process, scene, navigation, measurement, and trajectory
  summary for all five scheduled episodes;
- `validations/ep*.json`: independent frozen-runtime rescore/contract results;
- `decision_policy_replay_summary.json`: counterfactual action counts from the
  three evaluable logs;
- `master.log`: launch/completion chronology.

The source JSONLs remain in their recorded `/mnt/SSD4T/.../eval_results/...`
episode directories. They are not duplicated because the three logs contain
full high-volume per-row diagnostic payloads. Their derived counts are
preserved here, while the companion handoff includes the exact validator and
replay implementations.

## Analysis code

`tools/` preserves the scripts used for capture validation, batch audit, and
prospective scoring. The executable decision-level shadow and readiness tools
live in the companion handoff directory so that a single snapshot defines the
next run.

## Integrity

`DATA_MANIFEST.sha256` hashes every included evidence file except itself using
paths relative to this directory. The companion framework has its own
`SOURCE_MANIFEST.sha256`.

