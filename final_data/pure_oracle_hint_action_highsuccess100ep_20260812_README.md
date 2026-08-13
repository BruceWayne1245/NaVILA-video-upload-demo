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

## Arbiter intervention-rate re-check (2026-08-13) — the "4.3%" figure does not transfer to this config

The project's oft-cited "`hint_action_arbiter` only overrides the VLM on 4.3% of return-phase
decisions (15/348), yet return success jumps from ~50% to 97%" figure comes from two 2026-06-30/
07-01 batches (`stop_gate_r3_hint_arbiter_hard11_20260630` + `oracle_shadow_loftr_v4_30_return_anchor_fix_20260701`,
see `investigations/数据补全/README.md` §2) that always ran `hint_action_arbiter` bundled with
`--oracle_align_return_yaw_to_anchor_segment` and `--stop_gate` — never in isolation. This batch
(`pure_oracle_hint_action_highsuccess100ep_20260812`) is the first isolation of
`hint_action_arbiter` (+`--topdown_route_map`) on its own, with those two other mechanisms
explicitly off, so the same override-rate computation was re-run against its own `[hint_arbiter]`
per-step log lines (`ep*_eval.log`, `grep "\[hint_arbiter\] step="`, same methodology as the
historical 4.3% figure) to see whether the rate transfers.

**It does not — the isolated arbiter overrides roughly 4x more often:**

| batch | total return-phase decisions | override=True (VLM output replaced) | override rate |
|---|---|---|---|
| historical 4.3% source (06-30/07-01, arbiter+yaw-oracle+stop_gate bundled) | 348 | 15 | 4.3% |
| `pure_oracle_hint_action_highsuccess100ep_20260812` (arbiter alone, this batch) | 3094 | 503 | **16.26%** |
| `pure_oracle_hint_action_100ep_20260812` (canonical-100, discarded 98/100 run — cross-check only) | 2480 | 433 | 17.46% |

The canonical-100 discarded run (different, harder episode manifest, not otherwise used as final
data) lands within 1.2 points of this batch's rate, so 16-17% looks like a property of running
the arbiter without yaw-oracle/stop_gate support, not an artifact of the high-success episode
sample.

Full per-episode decision counts and reason breakdown for this batch:
[`pure_oracle_hint_action_highsuccess100ep_20260812_arbiter_decisions.tsv`](pure_oracle_hint_action_highsuccess100ep_20260812_arbiter_decisions.tsv)
(87 of the 100 episodes reached the return phase and logged at least one arbiter decision; the
other 13 never entered return, consistent with `outbound_success=86/100` minus a couple of
episodes that stopped immediately on entering return). Reason-code breakdown, pooled:

| reason | count | share | meaning |
|---|---|---|---|
| `vlm_action_consistent` | 1699 | 54.9% | VLM action already matched the hint direction, no override needed |
| `occupied_in_local_map_path` | 727 | 23.5% | VLM conflicted with the hint, but the hinted path was occupied per the local/topdown map, so the arbiter declined to override |
| `vlm_conflicts_with_clear_hint` | 503 | 16.3% | VLM conflicted with the hint, hinted path was clear → **overridden** |
| `target_too_close` | 165 | 5.3% | next-anchor target distance below `min_anchor_distance_m`, decision skipped — a reason code not present in the historical 06-30/07-01 batches' arbiter version |

Per-episode intervention rate is broadly distributed, not driven by a few outlier episodes:
median 13.3% across the 87 episodes with at least one decision, 70/87 episodes have at least one
override, only a handful of low-decision-count episodes (≤14 decisions) hit 100%.

**Interpretation:** the 4.3% figure was never a property of `hint_action_arbiter` alone — it
described how often the arbiter still needed to intervene *after* `--oracle_align_return_yaw_to_anchor_segment`
had already removed most of the robot's heading noise. Without that oracle yaw correction, the
VLM's own action more often genuinely conflicts with the route hint, so the arbiter's real
correction workload in isolation is roughly 4x higher than the historical headline number. This
does not contradict the return-rate finding above (arbiter alone still adds +23.3 points over
hint-alone on this sample) — it only means the 4.3%/97% headline should not be quoted as
`hint_action_arbiter`'s own intervention rate going forward.

Source logs: `batch_logs/pure_oracle_hint_action_highsuccess100ep_20260812/ep*_eval.log` and
`batch_logs/pure_oracle_hint_action_100ep_20260812/ep*_eval.log` on `hrl-4090-server`
(`/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/`), `[hint_arbiter]` log lines emitted
by `scripts/hint_action_arbiter.py`.
