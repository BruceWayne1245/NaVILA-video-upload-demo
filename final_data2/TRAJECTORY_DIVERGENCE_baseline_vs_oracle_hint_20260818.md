# Outbound vs Return Trajectory Divergence — pure_baseline vs oracle_hint (2026-08-18)

Purpose: isolate how much of the return-path difference between `pure_baseline` and
`oracle_hint` (see [`README.md`](README.md)) is just VLM run-to-run noise vs. an actual
effect of the hint. **Outbound** is driven by the plain VLM policy in both conditions
(hint never touches outbound), so baseline-vs-oracle_hint divergence on outbound is a
direct measurement of the VLM's own trajectory variance when the identical episode is
run twice. **Return** is where `oracle_hint` actually intervenes, so its divergence
combines that same noise floor plus the hint's effect.

## Method

For each of the same 50 `episode_id`s used throughout `final_data2/` (see
[`README.md`](README.md#why-this-50-episode-set-specifically)), the real per-step 2D
position log was pulled from each run's
`eval_results/.../trajectories/output_{episode_id-1}.jsonl` (written by
`make_trajectory_record` in `round_trip_eval.py`), split by the `phase` field into
`outbound` and `return` segments. Each pair of paths (baseline vs oracle_hint, same
episode, same phase) was arc-length-resampled to 100 points and compared point-by-point
with Euclidean distance — the same resampling approach used for the earlier 9-episode
return-trajectory grid (`investigations/数据补全/code/plot_baseline_vs_oracle_9ep_grid.py`).

Script: [`code/compute_trajectory_divergence_outbound_return_20260818.py`](code/compute_trajectory_divergence_outbound_return_20260818.py).

**n = 43/50** episodes have valid trajectory data in both runs. 7 excluded: 6 have
non-zero `exit_code` in the `oracle_hint` batch (infra failure, no full trajectory
written) and 1 (`episode_id` 1801) has a truncated summary row (31s runtime, no
`outbound_success`/measurement data) — see raw `batch_logs/pure_oracle_hint_highsuccess100ep_20260811/summary.tsv`.

## Result

| phase | mean divergence | median divergence | std | range (per-ep mean) | mean of per-ep MAX | mean endpoint divergence |
|---|---|---|---|---|---|---|
| **outbound** (VLM only, no hint) | **0.139 m** | 0.103 m | 0.166 m | 0.000 – 0.585 m | 0.304 m | 0.283 m |
| **return** (oracle_hint active) | **1.908 m** | 1.081 m | 2.076 m | 0.000 – 7.597 m | 4.068 m | 3.913 m |

**Return-phase divergence is ~10–14x larger than outbound** (median ratio ≈10.5x, mean
ratio ≈13.7x). Outbound gives a noise floor of roughly 0.1–0.3 m for the same episode run
twice by the plain VLM policy; return divergence far exceeds that floor, so the
hint is reshaping the return path, not just adding noise.

### Return divergence by return-success outcome (same 43 episodes)

| baseline_return | oracle_return | n | mean divergence | median divergence |
|---|---|---|---|---|
| False | False (both fail) | 23 | 1.617 m | 0.466 m |
| False | True (hint recovers) | 10 | 3.157 m | 2.838 m |
| True | False (hint derails) | 4 | 2.875 m | 2.895 m |
| True | True (both succeed) | 6 | 0.299 m | 0.246 m |

When both conditions succeed, return paths converge tightly (~0.3 m) — success itself
pulls paths together. Divergence concentrates in the 14 episodes where the hint flips
the outcome (either direction), at ~2.8–3.2 m median — this is where the hint is
actually doing something to the trajectory shape, not the full 43-episode pool
uniformly.

## Data files

- [`trajectory_divergence_outbound_baseline_vs_oracle_hint_20260818.csv`](trajectory_divergence_outbound_baseline_vs_oracle_hint_20260818.csv) — per-episode outbound divergence (43 rows)
- [`trajectory_divergence_return_baseline_vs_oracle_hint_20260818.csv`](trajectory_divergence_return_baseline_vs_oracle_hint_20260818.csv) — per-episode return divergence (43 rows)

Columns: `mean_div_m`, `max_div_m`, `median_div_m`, `endpoint_div_m` (all from the
100-point arc-length-resampled pointwise comparison), `path_len_baseline_m` /
`path_len_oracle_m` (raw path length in each run), `n_points_a` / `n_points_b` (raw
logged step counts), `episode_id`, plus the relevant per-condition success flags
(`baseline_outbound_success`/`oracle_outbound_success` for the outbound file,
`baseline_return_success`/`oracle_return_success` for the return file).

## Caveats

- This is a matched-sample comparison on one specific 50-episode subset, not the full
  100ep manifest for either condition — same caveat as the rest of `final_data2/`.
- Arc-length resampling aligns paths by fraction-of-length-traveled, not by wall-clock
  step — a fair shape comparison, but it does not capture speed/timing differences
  between the two runs.
- The two batches were launched a week apart (`oracle_hint` 2026-08-11,
  `pure_baseline` 2026-08-18); some of the outbound "noise floor" could in principle
  include environment drift across that gap rather than pure per-run stochasticity,
  though 0.1–0.3 m is small enough that this is unlikely to change the qualitative
  conclusion (return divergence is far above the outbound floor regardless).
