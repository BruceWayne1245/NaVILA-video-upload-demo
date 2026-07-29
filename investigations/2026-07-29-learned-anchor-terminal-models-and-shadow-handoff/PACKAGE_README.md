# NaVILA anchor/terminal training data

This directory builds two supervised sequence datasets from saved NaVILA
return-phase captures without changing or reading from any live evaluator
process.

It complements, rather than replaces, the earlier 96,206-row
promotion/quarantine/wait dataset in the GitHub investigation
`2026-07-28-promotion-quarantine-controller-model`. That dataset remains useful
for the existing dwell controller; this package adds route-identity and
terminal supervision.

## Outputs

`data/v1/anchor_state.jsonl.gz`

- one row per relocalization attempt;
- exact attempt-to-return-step alignment when evidence-update or V1.1 step
  metadata exists; explicitly down-weighted interpolation for older captures;
- every candidate observed on that attempt;
- runtime-safe candidate, state, motion, and reliability features;
- temporally aligned oracle route identity and route-progress labels.

`data/v1/terminal_decision.jsonl.gz`

- one row per return-phase VLM query;
- runtime-safe route-memory, candidate, A0, VLM-STOP, freshness, and motion
  features;
- oracle return-route distance labels: `arrived`, `boundary`, or `far`;
- counterfactual action labels: `accept`, `verify`, `reject`, or `continue`.

`data/v1/episodes.jsonl`, `splits.json`, and `audit.json` record provenance,
scene-disjoint splits, exclusions, label quality, class balance, and candidate
coverage.

The datasets intentionally do not copy point clouds, RGB, depth, or trajectory
files. Source paths and hashes link each row back to the saved capture.

Legacy captures that predate exact attempt-step logging are retained with
`attempt_step_alignment="linear_attempt_interpolation_approximate"` and half
weight. They can be excluded during training without rebuilding the dataset.

## Label conventions

Route identity is aligned to the outbound anchor polyline with a temporal
dynamic-programming alignment. This avoids labeling a self-intersection or
loop solely by Euclidean nearest segment.

The oracle next anchor uses the same one-metre lookahead convention as the
current direct-oracle route-anchor implementation. Oracle route distance is:

```text
distance(robot, oracle target anchor) + target anchor distance from A0
```

Terminal classes use the current stop-gate uncertainty margin:

- `arrived`: route distance `<= 2.65 m`;
- `boundary`: `2.65 m < distance <= 3.35 m`;
- `far`: route distance `> 3.35 m`.

These are route-distance labels, not Euclidean distance-to-A0 labels.

## Build

```bash
python3 tools/build_training_datasets.py
python3 tools/audit_training_datasets.py
python3 -m unittest discover -s tests -v
```

The default source root is:

```text
/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results
```

Scene IDs are recovered from the frozen evaluator dataset when an older
capture predates `capture_completion.json`:

```text
/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/isaaclab_exts/
omni.isaac.vlnce/assets/vln_ce_isaac_v1.json.gz
```

Use `--source-root`, `--episode-dataset`, `--output-dir`, or `--limit` for an
alternate source or small validation build.

## Train

The v1 models are trained with the `vlnce-isaac` environment so their joblib
artifacts use the same scikit-learn version as the navigation runtime:

```bash
./training/run_training.sh
/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac/bin/python \
  training/finalize_training.py
```

The saved artifacts and held-out evaluation are in `models/v1/` and
`reports/v1/`. See `MODEL_CARD.md` for intended use and safety limitations.

## Leakage policy

- splits are disjoint by Matterport scene;
- repeated physical episodes and repeated policy variants remain in the same
  split because the scene is the split group;
- exact duplicate trajectories are removed by SHA-256;
- all fields under `labels` and `oracle_alignment` are supervision only;
- absolute simulator position and anchor world poses are never placed in
  runtime feature blocks;
- historical controller and stop-gate decisions are stored under
  `historical_policy`, not under model inputs.
