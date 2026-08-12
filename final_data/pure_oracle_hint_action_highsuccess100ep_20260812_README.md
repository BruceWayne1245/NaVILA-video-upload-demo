# Oracle-Hint-Action on High-Outbound-Success 100ep Sample — Final Data (2026-08-12)

This file documents `pure_oracle_hint_action_highsuccess100ep_20260812` — ablation step 2
(`oracle_hint` + `--hint_action_arbiter` + `--topdown_route_map`; **no** `--stop_gate`,
**no** `--oracle_align_return_yaw_to_anchor_segment`), run on the same high-outbound-success
100-episode sample as
[`pure_oracle_hint_highsuccess100ep_20260811`](pure_oracle_hint_highsuccess100ep_20260811_README.md)
(episode list unchanged — only the flags differ). This is **not** the standard canonical-100
manifest.

## Why this sample exists

Same rationale as the step-1 `oracle_hint` run: the canonical-100 manifest has a long-standing
26-43% outbound-success ceiling regardless of config, so a second sample was selected by
ranking all historical episode_ids by outbound success rate (top 100 of 264, weighted
historical outbound success 884/932 ≈ 94.85%). Full methodology:
`investigations/数据补全/code/high_outbound_success_100ep_selection.tsv` and
`investigations/数据补全/README.md` §6.

**This run replaces an earlier same-day attempt that used the wrong manifest.** A batch under
the same ablation step (`pure_oracle_hint_action_100ep_20260812`) was first launched on the
canonical-100 manifest by mistake — the intent was always to use this high-outbound-success
sample, matching step 1. It was manually stopped at 98/100 episodes once the mistake was
caught; that partial canonical-100 data remains in
`batch_logs/pure_oracle_hint_action_100ep_20260812/` but is **not** used here and is not part
of this final-data table. This run is the corrected one, on the intended manifest.

## Result

Source: `batch_logs/pure_oracle_hint_action_highsuccess100ep_20260812/summary.tsv` on
`hrl-4090-server` (`/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/`), launched
2026-08-12 14:33:53 BST via `systemd-run --user`, finished 2026-08-12 20:16:54 BST. All 100
episodes attempted; 7 had a non-zero `exit_code` (transient infra failures: episode_idx 647,
962, 783, 271, 656, 885, 960).

Full per-episode results: [`pure_oracle_hint_action_highsuccess100ep_20260812_full_results.tsv`](pure_oracle_hint_action_highsuccess100ep_20260812_full_results.tsv).

| metric | value |
|---|---|
| outbound_success | 86/100 |
| return_success | 52/100 |
| round_trip_success | 52/100 |
| **return-success rate** (`round_trip_success / outbound_success`, per project's standing denominator convention) | **52/86 ≈ 60.5%** |

No historical merge was applied here (unlike `pure_navila_baseline_100ep_20260810`'s
`final_data/README.md`) — this episode sample is brand new as of this week, so there is no
prior-round data on the same episode_ids to merge in.

## Comparison to step 1 (oracle_hint, same episode sample)

| condition | outbound_success | round_trip_success | return-rate |
|---|---|---|---|
| `oracle_hint` (step 1, [pure_oracle_hint_highsuccess100ep_20260811](pure_oracle_hint_highsuccess100ep_20260811_README.md)) | 86/100 | 32/100 | 32/86 ≈ 37.2% |
| `oracle_hint_action` (step 2, this file) | 86/100 | 52/100 | 52/86 ≈ 60.5% |

Same outbound-success count (both runs share the identical episode manifest, and neither flag
set touches outbound navigation), so the return-phase gain from adding `hint_action_arbiter` +
`topdown_route_map` on top of hint-alone is directly comparable on this sample: +20 round-trip
successes, return-rate +23.3 points.

## Caveats

- **Not comparable to the canonical-100 series** (`pure_navila_baseline_100ep_20260810`,
  `pure_oracle_hint_100ep_20260811`, and the partial/discarded
  `pure_oracle_hint_action_100ep_20260812`) — different episode sample entirely (only 30/100
  overlap with canonical-100). Use this as a standalone data point on the high-success sample,
  not as the canonical-100 ablation chain's step 2 in the paper's main comparison table.
- `episode_id` (not `episode_idx`) is the stable cross-batch join key, per this project's
  standing convention.
- Return-rate denominator is `outbound_success`, not total episode count or `return_success`
  alone — see the project's standing return-rate-denominator convention.
- 28/100 episodes in this sample have only a single historical attempt backing their selection
  (100% on n=1) — statistically weak for a subset of the manifest, flagged in the original
  selection methodology, not hidden.
