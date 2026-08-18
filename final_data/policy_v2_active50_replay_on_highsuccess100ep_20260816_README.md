# Policy V2 (66%-code) Reproduction on High-Outbound-Success 100ep — Final Data (2026-08-16/18)

This file documents `policy_v2_active50_replay_on_highsuccess100ep_20260816`: the byte-verified,
untouched `policy_v2_live_candidate` code (`route_memory_agent.py`/`relocalization.py`/
`hint_action_arbiter.py`/`stop_gate.py`/`stuck_recovery.py`, archived at
`/home/teambruce/navila_archive/staging_dirs/navila-reliability-v1_1-policy-v2-active50-20260725/`)
that originally produced Route2's best verified round-trip number (55.6% overall, 66% on a
29-episode subset), re-run end-to-end against the same high-outbound-success 100-episode manifest
used throughout the `数据补全` ablation chain
([`pure_oracle_hint_action_stopgate_highsuccess100ep_20260813`](pure_oracle_hint_action_stopgate_highsuccess100ep_20260813_README.md)
and its siblings — 100/100 `episode_id` overlap confirmed).

Launched via `systemd-run --user` unit `navila-policyv2-highsuccess100ep-20260816`, started
2026-08-16T17:34:47+01:00, finished 2026-08-18T01:34:21+01:00 (~1d 21h wall time). All 100
episodes completed with `exit_code=0`. Source:
`batch_logs/policy_v2_active50_replay_on_highsuccess100ep_20260816/summary.tsv` on
`hrl-4090-server` (`/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/`).

Full per-episode results (chronological execution order preserved via `start_time`/`end_time`
columns): [`policy_v2_active50_replay_on_highsuccess100ep_20260816_full_results.tsv`](policy_v2_active50_replay_on_highsuccess100ep_20260816_full_results.tsv).

## Result — full 100 episodes

| metric | value |
|---|---|
| outbound_success | 91/100 |
| return_success | 43/100 |
| round_trip_success | 42/100 |
| **return-success rate** (`round_trip_success / outbound_success`) | **42/91 ≈ 46.2%** |

This is well below the 66% seen on the original 29-episode overlap subset that motivated this
reproduction run, and below Route2's historical best verified 55.6% — see
[[project_100ep_failure_and_threetier_stuck_20260816]] for the investigation this followed from.
**Conclusion: 66% was a small-sample (n=29) overestimate**, not a result this exact code
reproduces at full-manifest scale.

## First-50 vs. last-50 (chronological execution order, not `episode_idx` order)

Splitting the 100 episodes by the order they actually ran (episode_idx values are interleaved
across both halves, not sorted, so this is not an artifact of manifest ordering):

| split | time range | outbound_success | round_trip_success | return-success rate |
|---|---|---|---|---|
| **first 50** | 2026-08-16T17:34:47+01:00 → 2026-08-17T08:03:24+01:00 | 49/50 | 27/50 | **27/49 ≈ 55.1%** |
| last 50 | 2026-08-17T08:03:24+01:00 → 2026-08-18T01:34:21+01:00 | 42/50 | 15/50 | 15/42 ≈ 35.7% |

**Headline number: the first-50-episode subset scores 55.1%, essentially reproducing Route2's
historical best verified result (55.6%)** — while the second half of the same continuous batch
run drops to 35.7%, pulling the pooled 100-episode number down to 46.2%. The drop is not
explained by episode difficulty (episode_idx values are scattered similarly across both halves);
most likely a time-dependent environment effect over the ~40h continuous run (GPU/VRAM state,
VLM server drift, scene cache, etc.) — root cause not yet investigated.

## Caveats

- Return-rate denominator is `outbound_success`, not total episode count, per this project's
  standing convention.
- The first/last-50 split is by **execution order** (wall-clock), not `episode_idx` — do not
  reorder the underlying TSV by `episode_idx` and re-split, the split will no longer match this
  table.
- This code's own ICP nearest-neighbor is the pre-KD-tree brute-force version (main repo
  switched to `scipy.spatial.cKDTree` 2026-08-15), deliberately kept unchanged from the original
  2026-07-25 code to avoid introducing an extra variable — see
  [[reference_policyv2_66pct_archived_code_20260816]].
- The first-50/last-50 gap is a real, observed pattern in this one run, not yet confirmed via a
  repeat run — treat 55.1% as "reproducible under first-half conditions of this batch," not yet
  as an independently-replicated number.
