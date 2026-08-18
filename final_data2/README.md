# Matched 50-Episode Subset — Final Data (2026-08-18)

This folder holds the same 4 batches from `final_data/` — all run on the high-outbound-success
100-episode manifest (`investigations/数据补全/code/high_outbound_success_100ep_selection.tsv`,
100% `episode_id` overlap confirmed across all 4) — **filtered down to one common set of 50
episode_ids**, so all 4 conditions are directly, row-for-row comparable on an identical episode
set instead of the full 100.

## Why this 50-episode set specifically

The 50 `episode_id`s are the **first 50 rows, by execution order (`start_time`), of
[`policy_v2_active50_replay_on_highsuccess100ep_20260816`](../final_data/policy_v2_active50_replay_on_highsuccess100ep_20260816_README.md)**
— chosen because that specific 50-episode subset scored 55.1%, closely reproducing Route2's
historical-best 55.6%, and a fresh **pure NaVILA baseline batch is currently running on this
exact same 50-episode set**
(`pure_baseline_highsuccess100ep_chronological_first50_20260818`, launched 2026-08-18T10:44 BST,
see [[project_policyv2_repro_and_v4_replay_results_20260818]]) specifically so it will also be
directly comparable to everything in this folder once it finishes.

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

`pure_navila_baseline_100ep_20260810` is **not** included here — it was run on the canonical-100
manifest, a different episode sample (only 30/100 `episode_id` overlap with the other 4), so it
cannot be filtered to this same 50-episode set.

## Code

[`policy_v2_active50_replay_on_highsuccess100ep_20260816_code/`](policy_v2_active50_replay_on_highsuccess100ep_20260816_code/)
holds the complete code that produced the `policy_v2_active50_replay` row above — both the
episode-execution harness (as it actually stood at launch time, including then-uncommitted
edits) and the Policy V2 / V1.1 reliability layer it loaded — plus the exact CLI launch
configuration. See that folder's own README for the full breakdown.

## Result — same 50 episodes, 4 conditions

| condition | outbound_success | round_trip_success | return-rate (on this 50-ep subset) | return-rate (full 100ep, for reference) |
|---|---|---|---|---|
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
