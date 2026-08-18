# Bidirectional-Trained-Path Standalone-vs-Return Comparison (2026-08-18)

Scales up the 2026-06-06/06-16 one-off "reverse-direction episode" test (see
`NaVILA-video-upload-demo/README.md`, "Training Coverage Diagnosis: Reverse-Direction
Episode Test" and "Return-Failure Ablations") from a single hand-picked pair
(scene `zsNo4HB9uLZ`, episode 0 / episode 705) to a batch across all scenes that have any
valid match.

## What this measures

For a `(primary episode P, reverse-path-trained neighbor episode N)` pair on the same
physical path, found via `_find_reverse_path_neighbor` + `_ordered_path_match` in
`NaVILA-Bench/scripts/instruction_rewriter.py:289-376` (real geometric matching against
`vln_ce_isaac_v1.json.gz`, tolerance_m=2.0 — the same mechanism every `cache_only`
round-trip batch already uses to auto-retrieve Return-phase oracle instructions):

1. **standalone_outbound**: episode N run through plain `navila_eval.py` — N's path is
   the exact geometric reverse of P's return leg, using N's own real dataset instruction.
   Measures raw path-execution capability, no round-trip machinery involved.
2. **round_trip**: episode P run through `round_trip_eval.py`
   (`--round_trip_mode=phase_prompt --instruction_rewriter_provider=cache_only`, the
   project's pure-baseline flags). The Return phase auto-retrieves N's real instruction.
   Measures whether NaVILA can execute the *same* path when framed as the Return leg of
   a round-trip task (phase transition, accumulated visual history, stop judgment).

Comparing standalone `success` against the round-trip run's `return_success` isolates
round-trip *context* effects from raw path-execution capability, since both runs use an
identical, genuinely-trained physical path and instruction wording.

## Batches

- **Original 9-scene batch** (`group_idx` 0-8, one pair per scene — the maximum possible,
  since only 9 of 11 scenes have any valid match at tolerance_m=2.0; `8194nk5LbLH` and
  `pLe4wQe7qrG` have zero): launched 2026-08-18T16:07 BST, **completed** 2026-08-18T17:08 BST.
- **Extra-pairs batch** (`group_idx` 9-55, extending scenes from 1 pair to up to 10 —
  scanned every remaining episode per scene as a candidate primary/source excluding
  indices already used, so each additional pair is an independent physical path, not a
  reuse/swap of an existing one): launched automatically the moment the first batch's
  systemd unit exited (via a waiter unit polling `systemctl --user is-active`), started
  2026-08-18T17:08 BST. **Still running as of this snapshot** (2026-08-18T17:28 BST) —
  `bidirectional_trained_paths_20260818_summary.tsv` in this folder is a point-in-time
  copy of the live file at
  `NaVILA-Bench/batch_logs/bidirectional_trained_9scenes_20260818/summary.tsv` on the
  compute box; re-pull it once the batch finishes for the complete 47-group data.
- Not every scene had 9 more independent pairs available. Per-scene total (1 original +
  N extra): `zsNo4HB9uLZ` 10, `QUCTc6BB5sX` 10, `2azQ1b91cZZ` 10, `TbHJrupSAjP` 9,
  `x8F5xyUWy9e` 5, `X7HyMhZNoso` 5, `EU6Fwq7SyZv` 4, `Z6MFQCViBuw` 2, `oLBMNvg9in8` 1
  (no further valid matches at all, unchanged from the original batch).

## Columns

`group_idx`, `scene`, `run_type` (`standalone_outbound` / `round_trip`), `primary_idx`,
`primary_episode_id`, `neighbor_idx`, `neighbor_episode_id`, `matched_waypoints`,
`mean_distance` (of the geometric path match), `run_episode_idx`, `port`, `start_time`,
`end_time`, `exit_code`, `result_suffix`, `vlm_log`, `eval_log`, `measurement_file`,
then per-`run_type` result columns: `success`/`spl`/`distance_to_goal` populate only on
`standalone_outbound` rows; `outbound_success`/`return_success`/`round_trip_success`/
`distance_to_start`/`outbound_stop_distance_to_goal` populate only on `round_trip` rows.

## Known issue

Group 1 (`x8F5xyUWy9e`, primary episode 5)'s `standalone_outbound` run has `exit_code=98`
— the VLM server failed to start due to a transient `huggingface_hub`/`urllib3` import
race (`ValueError: too many values to unpack`), not a real path-execution failure. Its
`success` column is blank; do not read this row as "standalone failed." The paired
`round_trip` run for the same group completed normally.

## Preliminary result — original 9-scene batch (complete)

| scene | standalone success | round-trip return_success |
|---|---|---|
| zsNo4HB9uLZ | fail | **True** |
| x8F5xyUWy9e | ⚠️ infra crash, no valid result | False |
| QUCTc6BB5sX | **True** | False |
| 2azQ1b91cZZ | fail | False |
| EU6Fwq7SyZv | fail | False |
| TbHJrupSAjP | fail | False |
| Z6MFQCViBuw | **True** | False |
| X7HyMhZNoso | **True** | False |
| oLBMNvg9in8 | **True** | False |

4 of 8 valid groups replicate the original 06-06 pattern (standalone succeeds, round-trip
Return on the identical path fails); 1 shows the opposite (`zsNo4HB9uLZ`); 3 have
standalone failing too (uninformative for isolating round-trip-context effect). Sample is
still small — the 47-group extra-pairs batch should sharpen this once complete.

## Caveats

- Return-rate/consistency conventions follow this project's standing rules — see the
  main `final_data2/README.md`.
- This snapshot is **not final** for the extra-pairs batch; treat any group_idx ≥ 9 rows
  as partial until re-synced.
