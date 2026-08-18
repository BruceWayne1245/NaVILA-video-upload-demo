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

## Batches — both complete

- **Original 9-scene batch** (`group_idx` 0-8, one pair per scene — the maximum possible,
  since only 9 of 11 scenes have any valid match at tolerance_m=2.0; `8194nk5LbLH` and
  `pLe4wQe7qrG` have zero): launched 2026-08-18T16:07 BST, completed 2026-08-18T17:08 BST.
- **Extra-pairs batch** (`group_idx` 9-55, extending scenes from 1 pair to up to 10 —
  scanned every remaining episode per scene as a candidate primary/source excluding
  indices already used, so each additional pair is an independent physical path, not a
  reuse/swap of an existing one): launched automatically the moment the first batch's
  systemd unit exited (via a waiter unit polling `systemctl --user is-active`), started
  2026-08-18T17:08 BST, **completed 2026-08-18T21:06 BST** (56 groups total, 112 runs).
  `bidirectional_trained_paths_20260818_summary.tsv` in this folder is now the complete,
  final file (re-synced from `NaVILA-Bench/batch_logs/bidirectional_trained_9scenes_20260818/summary.tsv`
  after the batch finished).
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

5 of the 112 runs (group 1 standalone, group 15 standalone, group 19 standalone, group 20
round_trip, group 42 round_trip) have `exit_code=98` — the VLM server failed to start due
to a transient `huggingface_hub`/`urllib3` import race (`ValueError: too many values to
unpack`), not a real path-execution failure. Their result columns are blank; do not read
these rows as "failed." Both legs of a group are independently launched, so an infra loss
on one leg does not invalidate the other leg of the same group.

## Final result (56 groups, 112 runs, complete)

### Per-scene

| scene | pairs | standalone: success/infra-loss | round-trip: return_success/infra-loss |
|---|---|---|---|
| zsNo4HB9uLZ | 10 | 3 succ / 1 infra | 2 succ / 0 infra |
| QUCTc6BB5sX | 10 | 4 succ / 0 infra | 0 succ / 0 infra |
| 2azQ1b91cZZ | 10 | 4 succ / 0 infra | 0 succ / 0 infra |
| TbHJrupSAjP | 9 | 1 succ / 0 infra | 0 succ / 0 infra |
| x8F5xyUWy9e | 5 | 1 succ / 2 infra | 0 succ / 1 infra |
| X7HyMhZNoso | 5 | 2 succ / 0 infra | 1 succ / 0 infra |
| EU6Fwq7SyZv | 4 | 1 succ / 0 infra | 0 succ / 1 infra |
| Z6MFQCViBuw | 2 | 1 succ / 0 infra | 0 succ / 0 infra |
| oLBMNvg9in8 | 1 | 1 succ / 0 infra | 0 succ / 0 infra |
| **total** | **56** | **18 succ / 3 infra (18/53 = 34.0%)** | **3 succ / 2 infra (3/54 valid pairs w/ round-trip data)** |

The round-trip side's own denominator (excluding its 2 infra losses) is 3/54 ≈ 5.6%; the
figure quoted below (3/51 ≈ 5.9%) additionally requires *both* legs of the same group to
be infra-clean, which is the correct denominator for the paired comparison since it's
asking about the same physical path on both sides.

### Paired same-path comparison (51 of 56 groups where both legs ran clean, `exit_code=0` both sides)

| outcome | groups |
|---|---|
| standalone succeeds AND round-trip return succeeds | 2 |
| standalone succeeds BUT round-trip return fails | 14 |
| standalone fails BUT round-trip return succeeds | 1 |
| both fail | 34 |

**Reading**: on the identical physical path, standalone/path-execution success (16/51 ≈
31.4%) is far higher than round-trip-return success (3/51 ≈ 5.9%). The 14-vs-1 asymmetry
(standalone-only-success groups vs round-trip-only-success groups) is the key signal —
it means the round-trip return leg fails on paths NaVILA can clearly execute standalone,
strongly reproducing the original 2026-06-06 single-pair finding (round-trip-context is
where these failures come from, not raw training coverage of the path itself) at n=51
instead of n=1. Not yet broken down by *why* the 14 flip-to-fail cases fail (stop_gate,
drift, wrong turn, etc.) — that's the natural next step on this data.

This is also consistent with
[`TRAJECTORY_DIVERGENCE_baseline_vs_oracle_hint_20260818.md`](TRAJECTORY_DIVERGENCE_baseline_vs_oracle_hint_20260818.md)'s
finding (different batch, same folder) that return-phase trajectories diverge ~10-14x more
from run to run than outbound trajectories do — the return leg is where round-trip context
introduces most of the behavioral instability.

## Caveats

- Return-rate/consistency conventions follow this project's standing rules — see the
  main `final_data2/README.md`.
- No failure-mode breakdown yet for the 14 standalone-succeeds/return-fails groups.
- The extra-pairs batch was launched automatically by a waiter unit rather than being a
  separately reviewed decision — its group count (56) was not planned in advance, it's
  simply "every valid match the scanner found."
