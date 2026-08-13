# Oracle-Hint-Action+Stop-Gate on High-Outbound-Success 100ep Sample — Final Data (2026-08-13)

This file documents `pure_oracle_hint_action_stopgate_highsuccess100ep_20260813` — ablation
step 3, the final step of the chain (`oracle_hint` + `--hint_action_arbiter` +
`--topdown_route_map` + `--stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0
--stop_gate_confirm_steps=3 --stop_gate_min_confidence=0.5`), run on the same
high-outbound-success 100-episode sample as
[`pure_oracle_hint_highsuccess100ep_20260811`](pure_oracle_hint_highsuccess100ep_20260811_README.md)
and
[`pure_oracle_hint_action_highsuccess100ep_20260812`](pure_oracle_hint_action_highsuccess100ep_20260812_README.md)
(episode list unchanged — only the flags differ). This is **not** the standard canonical-100
manifest. `--oracle_align_return_yaw_to_anchor_segment` remains deliberately excluded, matching
the historical stop-gate-batch flag set.

## Why this sample exists

Same rationale as steps 1 and 2: the canonical-100 manifest has a long-standing 26-43%
outbound-success ceiling regardless of config, so a second sample was selected by ranking all
historical episode_ids by outbound success rate (top 100 of 264, weighted historical outbound
success 884/932 ≈ 94.85%). Full methodology:
`investigations/数据补全/code/high_outbound_success_100ep_selection.tsv` and
`investigations/数据补全/README.md` §6-8.

## Result

Source: `batch_logs/pure_oracle_hint_action_stopgate_highsuccess100ep_20260813/summary.tsv` on
`hrl-4090-server` (`/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/`), launched
2026-08-13 09:10:37 BST via `systemd-run --user`, finished 2026-08-13 18:05:27 BST. All 100
episodes attempted; 1 had a non-zero `exit_code` (transient infra failure: episode_idx 539).

Full per-episode results: [`pure_oracle_hint_action_stopgate_highsuccess100ep_20260813_full_results.tsv`](pure_oracle_hint_action_stopgate_highsuccess100ep_20260813_full_results.tsv).

| metric | value |
|---|---|
| outbound_success | 87/100 |
| return_success | 73/100 |
| round_trip_success | 71/100 |
| **return-success rate** (`round_trip_success / outbound_success`, per project's standing denominator convention) | **71/87 ≈ 81.6%** |

No historical merge was applied here (unlike `pure_navila_baseline_100ep_20260810`'s
`final_data/README.md`) — this episode sample is brand new as of this week, so there is no
prior-round data on the same episode_ids to merge in.

## Full ablation chain (same high-success-100 sample throughout)

| step | condition | outbound_success | round_trip_success | return-rate |
|---|---|---|---|---|
| 1 | `oracle_hint` ([README](pure_oracle_hint_highsuccess100ep_20260811_README.md)) | 86/100 | 32/100 | 32/86 ≈ 37.2% |
| 2 | `oracle_hint_action` = step 1 + `hint_action_arbiter` + `topdown_route_map` ([README](pure_oracle_hint_action_highsuccess100ep_20260812_README.md)) | 86/100 | 52/100 | 52/86 ≈ 60.5% |
| 3 | `oracle_hint_action_stop_gate` = step 2 + `stop_gate` (this file) | 87/100 | 71/100 | 71/87 ≈ 81.6% |

Each step adds exactly one mechanism on top of the last, on an unchanged episode manifest, so
the deltas are directly attributable:
- step 1 → 2 (`hint_action_arbiter` + `topdown_route_map`): +20 round-trip successes, +23.3pt
- step 2 → 3 (`stop_gate`): +19 round-trip successes, +21.1pt (on 1 more outbound-success than
  step 2 — outbound counts are not required to match exactly across steps since `stop_gate` also
  affects when a run is declared successful outbound, though the flag set does not intentionally
  touch outbound navigation)
- step 1 → 3 (full stack): +39 round-trip successes, +44.4pt

This chain is now complete: `oracle_hint` → `oracle_hint_action` → `oracle_hint_action_stop_gate`
mirrors the historical 06-30/07-01 batches' flag composition (minus
`--oracle_align_return_yaw_to_anchor_segment`, deliberately excluded throughout this chain), run
end-to-end on one consistent, high-outbound-success episode sample.

## Caveats

- **Not comparable to the canonical-100 series** (`pure_navila_baseline_100ep_20260810`,
  `pure_oracle_hint_100ep_20260811`, and the partial/discarded
  `pure_oracle_hint_action_100ep_20260812`) — different episode sample entirely (only 30/100
  overlap with canonical-100). Use this chain as a standalone data point on the high-success
  sample, not as the canonical-100 ablation chain in the paper's main comparison table.
- `episode_id` (not `episode_idx`) is the stable cross-batch join key, per this project's
  standing convention.
- Return-rate denominator is `outbound_success`, not total episode count or `return_success`
  alone — see the project's standing return-rate-denominator convention.
- `--oracle_align_return_yaw_to_anchor_segment` is excluded from all three steps in this chain —
  this chain measures `hint_action_arbiter` and `stop_gate`'s contributions without ground-truth
  heading correction, so it is not a full reproduction of the historical 4.3%/97% headline batch
  (which stacked all four mechanisms). See
  [`pure_oracle_hint_action_highsuccess100ep_20260812_README.md`](pure_oracle_hint_action_highsuccess100ep_20260812_README.md#arbiter-intervention-rate-re-check-2026-08-13--the-43-figure-does-not-transfer-to-this-config)
  for the related arbiter-intervention-rate re-check.
- 28/100 episodes in this sample have only a single historical attempt backing their selection
  (100% on n=1) — statistically weak for a subset of the manifest, flagged in the original
  selection methodology, not hidden.
