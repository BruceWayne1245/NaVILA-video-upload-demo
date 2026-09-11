# Return-geometry M50 results

This result set evaluates the deterministic breadcrumb/path-following return
controller on the paper-matched 50-episode cohort. Outbound and confirmation
retain the online comparator behavior; return uses accumulated breadcrumbs,
sequential-pair ICP, and the deterministic geometry controller.

## Final accounting

| Population | Outbound success | Return success | Round-trip success |
|---|---:|---:|---:|
| 50 scheduled episodes | 46 | 11 | 11 (22.0%) |
| 48 evaluators that ran | 46 (95.8%) | 11 (22.9%) | 11 (22.9%) |
| 46 outbound-success episodes | 46 | 11 (23.9%) | 11 (23.9%) |

Episodes 658 and 271 had VLM startup failures (exit code 98), so they do not
have navigation outcomes. Among the 48 evaluators that ran, 11 completed the
round trip and 37 failed return. One of those 37 (episode 1004) also failed the
3 m outbound criterion.

The 11 successful episodes are:

`844, 555, 367, 484, 319, 815, 813, 783, 784, 785, 479`

## Recovery and provenance

The original batch summary directly contained 32 complete outcomes. Six more
outcomes were recovered verbatim from terminal fields in malformed measurement
JSON files: 806, 517, 961, 555, 671, and 539.

Ten evaluator runs had no measurement or trajectory file: 646, 579, 696, 534,
688, 264, 581, 366, 189, and 1004. Their outcome flags are recoverable from the
evaluator logs:

- the outbound stop distance is the logged XY error against the oracle return
  pose and is evaluated against the unchanged 3 m success radius;
- every run entered return;
- none recorded an accepted return stop-gate decision;
- `return_success` starts false and can only become true after that accepted
  stop event.

Consequently, these ten runs are exact outcome recoveries, not estimated
success labels. Their precise terminal position and full trajectory cannot be
reconstructed because those files were never written. The
`last_observed_distance_to_start` column is periodic ground-truth telemetry and
must not be treated as the exact terminal distance.

`summary.recovered.tsv` preserves all 50 scheduled rows and adds recovery
status, evidence source, last observed step/distance, and a recovery note. The
original local summary and raw evidence were not modified.

## Frozen code snapshot

The `code/` directory contains the files used to launch and implement this
batch:

- `run_path_following_geometry_m50_20260906.sh`: exact runner arguments and the
  ordered 50-episode cohort;
- `scripts/round_trip_eval.py`: evaluator entry point;
- `scripts/path_following_geometry.py`: deterministic return controller;
- `scripts/route_memory_agent.py`, `scripts/relocalization.py`,
  `scripts/local_map.py`, and `scripts/scan_context.py`: route memory and ICP;
- `scripts/stop_gate.py` and supporting runtime modules;
- `reliability/`, `configs/`, and the portable shadow artifact used by the
  evaluator configuration;
- `tests/test_path_following_geometry.py`: controller unit tests;
- `tools/recover_geometry_m50_summary.rb`: reproducible result-recovery tool.

This is a source/configuration snapshot for auditing the reported result. It
does not vendor Isaac Lab, NaVILA model weights, locomotion checkpoints, the
Matterport assets, or the Python/Conda environments required for a full rerun.
