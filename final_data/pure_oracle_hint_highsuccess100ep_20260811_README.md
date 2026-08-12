# Oracle-Hint on High-Outbound-Success 100ep Sample — Final Data (2026-08-12)

This file documents `pure_oracle_hint_highsuccess100ep_20260811` — the plain `oracle_hint`
condition (`--round_trip_mode=phase_prompt --instruction_rewriter_provider=cache_only
--route_memory --route_hint_mode=compact --route_hint_source=oracle
--route_relocalization_backend=none`, **no** `--hint_action_arbiter`, **no** `--stop_gate`,
**no** `--oracle_align_return_yaw_to_anchor_segment` — identical flags to
`pure_oracle_hint_100ep_20260811`), run on a **different, newly-selected 100-episode sample**,
not the standard canonical-100 manifest.

## Why this sample exists

`pure_oracle_hint_100ep_20260811` (the canonical-100 run, see
`investigations/2026-08-11-pure-oracle-hint-100ep-and-stopgate-audit/`) only reached
outbound_success on 30/100 episodes — confirmed to be a long-standing property of the
canonical-100 manifest itself (6 historical batches on the same set all land in the 26-43%
outbound-success range), not a config issue. To get a second oracle_hint data point on
episodes the VLM can reliably reach outbound in the first place, a new 100-episode sample was
selected by ranking all 264 episode_ids with historical outbound-success data (scanned across
196 historical `batch_logs/*/summary.tsv`, joined on the stable `episode_id` key) by historical
outbound success rate, taking the top 100. Full selection methodology and per-episode
historical-evidence data: `investigations/数据补全/code/high_outbound_success_100ep_selection.tsv`
and `investigations/数据补全/README.md` §6.

**This sample's weighted historical outbound success rate was 884/932 ≈ 94.85%** going in —
substantially higher than canonical-100's 26-43%, confirming the selection worked as intended,
though this week's own realized rate (below) came in somewhat lower than that historical
estimate.

## Result

Source: `batch_logs/pure_oracle_hint_highsuccess100ep_20260811/summary.tsv` on
`hrl-4090-server` (`/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/`), launched
2026-08-11 23:22 BST via `systemd-run --user` (unit
`navila-oracle-hint-highsuccess100ep-20260811`, survives disconnect via linger), finished
2026-08-12 05:10:38 BST. All 100 episodes attempted; 6 had a non-zero `exit_code` (transient
infra failures: episode_idx 688, 95, 484, 189, 1004, 555).

Full per-episode results: [`pure_oracle_hint_highsuccess100ep_20260811_full_results.tsv`](pure_oracle_hint_highsuccess100ep_20260811_full_results.tsv).

| metric | value |
|---|---|
| outbound_success | 86/100 |
| return_success | 32/100 |
| round_trip_success | 32/100 |
| **return-success rate** (`round_trip_success / outbound_success`, per project's standing denominator convention) | **32/86 ≈ 37.2%** |

No historical merge was applied here (unlike `pure_navila_baseline_100ep_20260810`'s
`final_data/README.md`) — this episode sample is brand new as of this week, so there is no
prior-round data on the same episode_ids to merge in.

## Caveats

- **Not comparable to the canonical-100 series** (`pure_navila_baseline_100ep_20260810`,
  `pure_oracle_hint_100ep_20260811`, and the planned `pure_oracle_hint_action_100ep_20260812` /
  `+stop_gate` steps) — different episode sample entirely (only 30/100 overlap with
  canonical-100). Use this as a standalone "how does oracle_hint do on easier episodes"
  data point, not as a substitute for the canonical-100 ablation chain in the paper's main
  comparison table.
- `episode_id` (not `episode_idx`) is the stable cross-batch join key, per this project's
  standing convention.
- Return-rate denominator is `outbound_success`, not total episode count or `return_success`
  alone — see the project's standing return-rate-denominator convention.
