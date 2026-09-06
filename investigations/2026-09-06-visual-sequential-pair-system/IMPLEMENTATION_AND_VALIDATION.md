# Implementation and validation record

## Changes

### `code/relocalization.py`

Adds `visual_sequential_pair_relocalization()`:

- accepts only current and next;
- converts each saved rear RGB-D observation into the matching view;
- calls the existing LoFTR/depth/RANSAC geometric estimator separately for
  each member of the pair;
- returns only measurements for those supplied anchors;
- never invokes full-route retrieval or local-map ICP.

### `code/round_trip_eval_visual.py`

- adds the `visual_sequential_pair` backend;
- binds it to `RouteMemoryAgent.sequential_target_anchor_pair()`;
- disables local LiDAR descriptor construction for that backend;
- adds the `--visual_gt_monitor` option;
- records truth after each simulator step and finalizes the monitor alongside
  normal episode artifacts.

### `code/visual_ground_truth_monitor.py`

Adds an independent analysis-only recorder for true outbound/return motion,
anchor truth, pair transitions, sensor assets, and online error measurements.

### `run_visual_sequential_pair_m50.sh`

- uses the isolated script path via an explicit `PYTHONPATH`;
- defaults to `visual_sequential_pair`;
- uses `0.2 m` anchors and interval-1 visual updates;
- retains the exact 50 episode entries from the matched-M50 runner;
- enables closure, bounded promotion, Hint/Arbiter, stop gate, stuck recovery,
  and the truth monitor;
- does not enable ICP-yaw alignment or the ICP-trained V1.1 consumer.

## Validation completed

- Python bytecode compilation passed for all four system modules.
- Shell syntax validation passed for the M50 runner.
- The runner contains exactly 50 `run_episode` entries.
- Two visual-backend unit tests passed:
  - only supplied current/next anchors are queried;
  - missing rear RGB-D does not invoke the matcher.
- The truth-monitor unit test verifies step/anchor/error artifacts without a
  control-return channel.
- Kornia LoFTR imports successfully in the installed Isaac environment.
- All three source-snapshot SHA-256 values revalidated successfully.
- The source files in live `NaVILA-Bench/scripts` were not edited by this work.

## Not yet validated

No live Isaac episode has been launched from this package.  Therefore this
record does not yet claim:

- adequate front/rear covisibility;
- sufficient LoFTR throughput at interval 1;
- calibrated confidence or RANSAC thresholds;
- correct promotion timing for `0.2 m` anchors;
- improved round-trip success over the LiDAR system.

These must be established by a one-episode smoke run followed by offline truth
comparison before the full M50 is authorized.

