# Pure NaVILA Baseline — Final Merged Return-Success Data (2026-08-11)

This folder holds the reconciled outbound/return numbers for the "pure NaVILA" round-trip
baseline (`--round_trip_mode=phase_prompt --instruction_rewriter_provider=cache_only`,
**no** `--route_memory`, **no** `--stop_gate`, no oracle/hint/relocalization flags of any
kind — the language-only control condition this project compares every enhanced pipeline
against).

Two independent sources feed the merged numbers below:

1. **This week's 100-episode batch** (`RUN_TAG=pure_navila_baseline_100ep_20260810`,
   run 2026-08-10 → 2026-08-11 across an original launch + 2 resumes, see
   `investigations/2026-08-10-100ep-baseline-batch/`). Full per-episode results are in
   [`pure_navila_baseline_100ep_20260810_full_results.tsv`](pure_navila_baseline_100ep_20260810_full_results.tsv)
   (100 rows, one per `episode_id`, from `batch_logs/pure_navila_baseline_100ep_20260810/summary.tsv`
   on the eval box).
2. **Three earlier, smaller pure-baseline rounds** documented in the main `README.md`
   under "2026-06-16/17/18 — v4 Baseline" (3-episode random test, 5-episode random test,
   and the 30-episode Batch A+B addition — 38 distinct episodes total, same
   `phase_prompt`/`cache_only`/no-memory config, just an older/different episode sample
   than the canonical-100 manifest introduced later on 2026-07-20).

## 1. The 100-episode canonical set

The full 100 `episode_id` values tested this week (identical set used by
`canonical_report_next_stopgate_100ep_20260720` and the other enhanced-pipeline batches,
so results below are directly comparable episode-for-episode to those) are listed in
[`pure_navila_baseline_100ep_20260810_full_results.tsv`](pure_navila_baseline_100ep_20260810_full_results.tsv),
column `episode_id`. Exit codes: 96×`0`, 3×`98`, 1×`1` (all 100 episodes were attempted;
a handful produced no measurement file, see the `outbound_success` column being blank).

## 2. Outbound-success denominator: 39 episodes

- **34 episodes** had `outbound_success=True` in this week's own run.
- Of the 9 episodes that succeeded outbound in one of the three earlier (pre-canonical-100)
  pure-baseline rounds but did **not** succeed outbound this week, **5 are actually members
  of this week's 100-episode canonical set** (the other 4 — `episode_id` 151, 601, 1166,
  1699 — belong only to the older, pre-2026-07-20 episode sample and are not part of the
  canonical 100, so they are excluded here).
- Per explicit instruction, those 5 historically-outbound-successful-but-in-set episodes are
  merged into the denominator alongside this week's 34, giving **39** total.

**The 39 outbound-success episode IDs:**

This week's 34 (`outbound_success=True`, `episode_id`):
```
9, 33, 128, 129, 286, 335, 422, 428, 439, 443, 476, 512, 562, 602, 603, 855, 868, 870, 922,
1119, 1134, 1153, 1154, 1167, 1189, 1336, 1378, 1517, 1700, 1710, 1711, 1713, 1759, 1761
```

Plus 5 historical outbound successes (from the 2026-06-18 30-episode batch; this week's own
run on the same `episode_id` failed outbound) — `episode_id (this week's episode_idx)`:
```
8 (idx4), 195 (idx134), 281 (idx187), 682 (idx408), 1165 (idx678)
```

## 3. Return-success numerator: 7 episodes

All 7 return successes come from this week's own run — **none of the 5 merged historical
episodes returned successfully** (all 5 failed return back in the 2026-06-18 batch: ep4
final distance 10.151 m, ep134 6.223 m, ep187 11.813 m, ep408 6.884 m, ep678 3.782 m — none
inside the 3.0 m success radius). They contribute to the denominator only, not the numerator.

**The 7 return-success episode IDs (all from this week, `episode_id (episode_idx, scene)`):**
```
428  (idx271,  QUCTc6BB5sX)  — final distance to start 2.182 m
1119 (idx647,  x8F5xyUWy9e)  — final distance to start 0.640 m
1154 (idx670,  X7HyMhZNoso)  — final distance to start 0.534 m
1167 (idx680,  zsNo4HB9uLZ)  — final distance to start 1.924 m
1700 (idx994,  QUCTc6BB5sX)  — final distance to start 1.201 m
1759 (idx1038, X7HyMhZNoso)  — final distance to start 2.299 m
1761 (idx1040, X7HyMhZNoso)  — final distance to start 2.478 m
```

All 7 also have `round_trip_success=True` (return success only counts here when outbound
also succeeded in the same run, per the project's standing return-rate-denominator
convention — this week's raw data additionally has 5 rows with `return_success=True` but
`outbound_success=False`, which are excluded from this analysis for the same reason, matching
`round_trip_success=False` on those rows).

## 4. Final number

```
return success rate = 7 / 39 = 17.9%
```

(For reference, using only this week's own run without the historical merge: 7/34 = 20.6%.
Merging in the 5 historically-successful-but-this-week-failed episodes pulls the pooled rate
down to 17.9%, since none of the 5 added denominator entries contributed a return success.)

## Methodology notes / caveats

- `episode_id` (not `episode_idx`) is the only reliable cross-batch join key — `episode_idx`
  is a manifest-order position that is **not** stable across different batch scripts/runs
  (confirmed by direct comparison: two other same-named "100ep" batches from 2026-07-22/24
  turned out to use a completely different 100-episode sample, zero `episode_id` overlap,
  despite using the same nominal episode count).
- The 4 excluded historical episodes (151, 601, 1166, 1699) are real outbound successes from
  the 2026-06-17 5-episode random test and the 2026-06-18 30-episode batch, but since they
  fall outside this week's 100-episode canonical manifest they are not comparable
  episode-for-episode to the rest of this dataset and were left out of the merged pool.
  Their own historical return outcomes: id 151 (ep105) — return **succeeded** (1.997 m,
  round-trip success); id 601 (ep366) — return **failed** (7.441 m, outbound-only success);
  id 1166 (ep679) — return **succeeded** (1.995 m, round-trip success); id 1699 (ep993) —
  return **succeeded** (1.994 m, round-trip success) — i.e. 3 of these 4 excluded episodes
  were themselves historical round-trip successes. If a
  future analysis wants a "was ever outbound-capable" pool untied to the canonical-100
  manifest, these would need to be added back in (denominator 43, numerator 10, 23.3%) —
  not done here since the instruction was to merge only episodes that are part of this
  week's 100-episode test set.
- Source data: `batch_logs/pure_navila_baseline_100ep_20260810/summary.tsv` on
  `hrl-4090-server` (`/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/`), and the
  three "v4 baseline" tables in the main `README.md` (2026-06-16/17/18 sections).
