# 2026-07-13 (continued) — Step 3: offline calibration of `hint_action_arbiter`'s confidence threshold

**Data source**: today's `no_fusion_ep368_20260713_accumulated` run — Variant 1 (no fusion) config, `--route_hint_source=oracle` (real navigation still oracle-driven) with `sequential_pair` computed in parallel as the shadow, exactly as every prior diagnostic batch in this project already does. No new live run was needed for this calibration — the shadow's reported/fused `relocalization_events` (what `hint_action_arbiter` would actually consume once wired to a non-oracle hint source) were already logged, complete with the `confidence` value.

**Method**: ground-truth bearing error (same methodology used throughout `investigations/2026-07-13-icp-bearing-error-cross-batch-deep-dive/`) computed for every reported/fused event, cross-referenced against that event's own `confidence`.

## Result: confidence separates cleanly, at a high threshold

n=356. Confidence is heavily concentrated at exactly 1.0 (93.8% of readings), with mean bearing error 4.1°/median 1.6° in that bucket — the remaining 6.2%, spread across confidence 0.5-0.99, has mean error 70-118° depending on the sub-bucket (essentially all catastrophically wrong):

| confidence bucket | n | % | mean err | median err |
|---|---|---|---|---|
| [0.5, 0.7) | 4 | 1.1% | 33.6° | 17.3° |
| [0.7, 0.8) | 4 | 1.1% | 117.7° | 108.1° |
| [0.8, 0.9) | 9 | 2.5% | 77.0° | 83.9° |
| [0.9, 0.95) | 1 | 0.3% | 50.3° | 50.3° |
| [0.95, 0.99) | 4 | 1.1% | 50.0° | 48.3° |
| [0.99, 1.01] | 334 | 93.8% | 4.1° | 1.6° |

Threshold sweep (readings with `confidence >= threshold` are "kept" / allowed to drive an arbiter override; below is "dropped" / arbiter defers to the VLM):

| threshold | kept % | kept mean | kept median | dropped n | dropped mean |
|---|---|---|---|---|---|
| 0.85 | 97.5% | 6.35° | 1.76° | 9 | 81.3° |
| **0.90** | **95.2%** | **4.82°** | **1.64°** | **17** | **76.4°** |
| 0.95 | 94.4% | 4.38° | 1.60° | 20 | 73.2° |
| 0.99 | 93.8% | 4.15° | 1.55° | 22 | 70.4° |

**Recommendation: `--hint_arbiter_min_relocalization_confidence=0.90`.** Drops only 4.8% of readings, all with catastrophic ground-truth error (mean 76.4°) — a clearly worthwhile trade for keeping the remaining 95.2% (mean 4.82°, median 1.64°) fully eligible for arbiter override.

**Note on the historical "confidence saturates" concern**: this doesn't contradict it. That finding (repeated throughout this project, e.g. `ep680`/anchor7) was about confidence failing to separate a *specific known-bad anchor* from the rest of the pool *in aggregate across many different anchors' own overlap baselines*. This calibration asks a narrower, different question — *within one episode's own accepted/fused events, does a higher confidence value predict lower error* — and the answer here is a clean yes. It's possible the specific saturation failure mode still exists on some other anchor not present in `ep368`; this is a single-episode calibration and should be revisited if a wider batch's data tells a different story.

## Reproducibility

Script: `code/calibrate_confidence_threshold_20260713.py` in this folder.
