# Matched 50-Episode Subset — Final Data (2026-08-18)

This folder holds 5 batches — all run on the high-outbound-success
100-episode manifest (`investigations/数据补全/code/high_outbound_success_100ep_selection.tsv`,
100% `episode_id` overlap confirmed across all of them) — **filtered down to one common set of 50
episode_ids**, so all 5 conditions are directly, row-for-row comparable on an identical episode
set instead of the full 100.

## Why this 50-episode set specifically

The 50 `episode_id`s are the **first 50 rows, by execution order (`start_time`), of
[`policy_v2_active50_replay_on_highsuccess100ep_20260816`](../final_data/policy_v2_active50_replay_on_highsuccess100ep_20260816_README.md)**
— chosen because that specific 50-episode subset scored 55.1%, closely reproducing Route2's
historical-best 55.6%. A fresh **pure NaVILA baseline batch was launched on this exact same
50-episode set**
(`pure_baseline_highsuccess100ep_chronological_first50_20260818`, launched 2026-08-18T10:44 BST,
finished 2026-08-18T14:30 BST, all 50/50 episodes exit_code=0, see
[[project_policyv2_repro_and_v4_replay_results_20260818]]) specifically so it would also be
directly comparable to everything in this folder — see its row in the results table below.

This is **not** a rank-ordered or otherwise "natural" first-50 of the manifest — it's an
arbitrary-but-fixed 50-episode slice defined by one batch's own run order. Do not re-derive a
"first 50" for a 5th batch by any other convention (e.g. manifest rank order) — pull the id list
from one of the files in this folder instead, to guarantee the match.

## Files

Each file is the corresponding `final_data/*_full_results.tsv` filtered to the same 50
`episode_id`s (original per-file row order preserved, not reordered to match each other):

- [`policy_v2_active50_replay_on_highsuccess100ep_20260816_matched50_full_results.tsv`](policy_v2_active50_replay_on_highsuccess100ep_20260816_matched50_full_results.tsv)
- [`pure_oracle_hint_highsuccess100ep_20260811_matched50_full_results.tsv`](pure_oracle_hint_highsuccess100ep_20260811_matched50_full_results.tsv)
- [`pure_oracle_hint_action_highsuccess100ep_20260812_matched50_full_results.tsv`](pure_oracle_hint_action_highsuccess100ep_20260812_matched50_full_results.tsv)
- [`pure_oracle_hint_action_stopgate_highsuccess100ep_20260813_matched50_full_results.tsv`](pure_oracle_hint_action_stopgate_highsuccess100ep_20260813_matched50_full_results.tsv)
- [`pure_baseline_highsuccess100ep_chronological_first50_20260818_matched50_full_results.tsv`](pure_baseline_highsuccess100ep_chronological_first50_20260818_matched50_full_results.tsv)
  — this one was launched directly on this exact 50-episode set (not filtered down from a
  100-episode run), so it has no full-100 counterpart in `final_data/`.

`pure_navila_baseline_100ep_20260810` is **not** included here — it was run on the canonical-100
manifest, a different episode sample (only 30/100 `episode_id` overlap with the other 4), so it
cannot be filtered to this same 50-episode set.

## Code

[`policy_v2_active50_replay_on_highsuccess100ep_20260816_code/`](policy_v2_active50_replay_on_highsuccess100ep_20260816_code/)
holds the complete code that produced the `policy_v2_active50_replay` row above — both the
episode-execution harness (as it actually stood at launch time, including then-uncommitted
edits) and the Policy V2 / V1.1 reliability layer it loaded — plus the exact CLI launch
configuration. See that folder's own README for the full breakdown.

## Result — same 50 episodes, 5 conditions

| condition | outbound_success | round_trip_success | return-rate (on this 50-ep subset) | return-rate (full 100ep, for reference) |
|---|---|---|---|---|
| `pure_baseline` (no route_memory/stop_gate/oracle/hint) | 50/50 | 11/50 | 11/50 ≈ 22.0% | n/a — no full-100 run on this exact set |
| `oracle_hint` | 43/50 | 16/50 | 16/43 ≈ 37.2% | 32/86 ≈ 37.2% |
| `oracle_hint_action` (+arbiter, +topdown_route_map) | 44/50 | 31/50 | 31/44 ≈ 70.5% | 52/86 ≈ 60.5% |
| `oracle_hint_action_stop_gate` (+stop_gate) | 43/50 | 37/50 | 37/43 ≈ 86.0% | 71/87 ≈ 81.6% |
| `policy_v2_active50_replay` (66%-code reproduction) | 49/50 | 27/50 | 27/49 ≈ 55.1% | 42/91 ≈ 46.2% |

`oracle_hint`'s subset rate is coincidentally identical to its full-100 rate; `oracle_hint_action`
and `oracle_hint_action_stop_gate` both score noticeably *higher* on this 50-episode subset than
on the full 100 (+10pt and +4.4pt respectively) — consistent with this being the "easier half" of
the manifest for policy_v2 (55.1% vs 46.2% overall), not just a policy_v2-specific effect.
`policy_v2_active50_replay`'s ordering relative to the ablation chain is unchanged either way
(below `oracle_hint_action_stop_gate`, above `oracle_hint` and, on the full-100 numbers, above
`oracle_hint_action` too — though on this subset it now falls *below* `oracle_hint_action`, since
the latter gained +10pt on this easier half and policy_v2 didn't move as much).

`pure_baseline` sits well below every other condition (22.0% vs the next-lowest `oracle_hint` at
37.2%), on the exact same 50 episode_ids and in the same execution order as
`policy_v2_active50_replay` — the cleanest baseline-vs-policy_v2 comparison run so far, since it
removes episode-selection as a confound (both conditions ran the identical 50-episode,
identical-order subset). The 55.1pt gap between `pure_baseline` (22.0%) and
`policy_v2_active50_replay` (55.1%) is far larger than the ±10pt swing seen in the "easier half"
effect above, so it's very unlikely to be explained by that alone — the route_memory/stop_gate/
reliability_v11 stack appears to carry most of the improvement over a bare NaVILA policy on this
task, though the two runs were not launched back-to-back (`policy_v2` ran 08-16, `pure_baseline`
ran 08-18) so some of the gap could still reflect run-to-run environment drift rather than the
mechanism alone — not something this single pair of runs can rule out.

## Outbound vs return trajectory divergence (VLM noise floor vs hint effect)

See [`TRAJECTORY_DIVERGENCE_baseline_vs_oracle_hint_20260818.md`](TRAJECTORY_DIVERGENCE_baseline_vs_oracle_hint_20260818.md)
for a per-episode comparison of real logged trajectories (not just success/fail flags)
between `pure_baseline` and `oracle_hint` on this same 50-episode set, split by phase.
Outbound (VLM-only, no hint) diverges by ~0.14 m mean / 0.10 m median between the two
runs of the same episode — the policy's own run-to-run noise floor. Return (where
`oracle_hint` intervenes) diverges by ~1.91 m mean / 1.08 m median — roughly 10-14x the
noise floor, concentrated in the episodes where the hint flips the return outcome.

## Caveats

- Return-rate denominator is each batch's own `outbound_success` count on this 50-episode
  subset (not 50, not the full-100 `outbound_success`) — per this project's standing
  return-rate-denominator convention.
- `episode_id` (not `episode_idx`) is the join key used to build these files, per this project's
  standing convention.
- Row order within each file is that file's own original order (not resorted to align rows
  across files) — join on `episode_id` if a row-aligned comparison is needed.
- This 50-episode set is *not* a principled/random sample — it's whatever happened to run first
  in one specific batch. Treat comparisons here as a matched-sample check, not as a replacement
  for the full-100 numbers in `final_data/`.
