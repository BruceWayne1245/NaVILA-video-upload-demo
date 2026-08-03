# 2026-07-31 — reliable30v3 re-validation, quarantine threshold recalibration, and Phase 3 (promote/wait live enforcement)

Author: Claude (Route 1). Continues directly from
`2026-07-30-promotion-shadow-logging-fix-and-unseen-validation` (the
`existing_heuristic_decision` logging fix and its Next Steps) and
`2026-07-28-promotion-quarantine-controller-model` (the original model +
`INTEGRATION_PLAN.md`, whose Phase 3 was "not started" until this session).
Unrelated to `2026-07-31-route2-runtime-failure-forensics` (same day, Route 2,
runner/lifecycle repairs only) -- that investigation and this one touch
disjoint files and disjoint failure classes; this one is entirely Route 1
(promotion controller model, `NaVILA-Bench/scripts/{round_trip_eval.py,
route_memory_agent.py,promotion_controller_runtime.py}`).

## 0. Context: what `promotion_shadow_reliable30v3_20260731` was actually for

Not just "more volume" -- the 07-30 FINDINGS.md Next Steps asked for two
specific things once the `existing_heuristic_decision` logging bug was fixed:

1. Use the now-fixed logging to do a clean model-vs-heuristic comparison
   without the `relocalization_events`-reconstruction workaround the 0728
   batch needed.
2. Get a materially higher valid-return-phase yield than `unseen30v2`'s
   catastrophic 17% (see that investigation), by dropping the "unseen"
   requirement -- 30 episodes picked purely by historical reliability (top-30
   by count of prior runs with a populated `return_success` field across all
   159 historical `batch_logs/*/summary.tsv`), not novelty. 9/30 overlap with
   the already-scored `promotion_shadow_30ep_20260728` cohort, 21/30 are new
   volume on the same reliable pool. This is a repeated-scenario check, not a
   held-out/OOD test -- same caveat the 0728 FINDINGS.md already flagged.

`reliable100` (100ep version of the same idea) was queued after
`unified_shadow50_retry4` per the 07-30 investigation, but was killed by
explicit user direction before completion ("如果你没有办法保证这30ep可以收获足够多有效的
return数据，那么还是优先用已经验证可以return的ep来跑" -- no time budget for a 100ep batch
right now, getting the model to Phase 3 matters more than strict validation
breadth). `reliable30v3` (this batch) is the 30ep replacement that actually
ran to completion. It was also blocked mid-run by an unrelated GPU/Vulkan
driver lockup (`2026-07-31-route2-runtime-failure-forensics` covers the
Route 2 side of that incident; the Route 1 side -- this batch stopping and
resuming cleanly across the reboot -- has no separate writeup since it
resumed with zero code changes needed, just a relaunch).

## 1. Yield: 18-19/28 episodes produced shadow-scoring data (~64-68%)

Confirmed via the existing-fix logging (`existing_heuristic_decision` now
shows real `promote`/`quarantine` actions, not 100% `wait` -- 112 real
promotes + 43 real quarantines across 6272 scored attempts in 19 episodes,
directly confirming the 07-30 fix is live in the deployed `round_trip_eval.py`
-- `promotion_shadow_pending`'s deferred-snapshot pattern was found at the
expected call sites). This is far above `unseen30v2`'s 17%.

Non-obvious finding: 3 episodes (`ep708`, `ep994`, `ep4`) show as
"no data"/infra-failure in `summary.tsv` (final measurement write or timeout
failed), but their `promotion_controller_shadow.jsonl` logs actually contain
96-257 scored attempts each -- the return phase did happen, only the final
wrap-up step failed. `summary.tsv`'s blank fields alone are not proof no
shadow data exists for an episode; check the JSONL directly.

## 2. Dwell-based re-scoring (training-matched ground truth, the rigorous check)

Regenerated ground truth with `extract_dwell_dataset.py`
(`2026-07-28-promotion-quarantine-controller-model/code/`, `BASE`/`OUT_CSV`
monkeypatched, scoped via glob to just this batch's episode dirs -- see
`code/extract_dwell_reliable30v3.py` in this folder). 15/28 episodes usable
(`ep708` lost to the already-documented intermittent measurement-JSON
corruption bug; 12 are real outbound failures with no return phase, hence no
dwells). 5413 rows, label split wait 79.9% / promote 18.8% / quarantine 1.3%
-- close to the 0728 batch's 78.9/19.2/1.9 and the original training set's
81.8/16.9/1.4.

Scored with the actual deployed bundle
(`promotion_controller_v2_2026-07-28_isaacenv.pkl` -- must load in the
`vlnce-isaac` conda env for sklearn 1.7.2 compatibility) +
`PromotionDecisionPolicy(quarantine_threshold=0.65)` (see
`code/score_reliable30v3.py`):

| class | reliable30v3 precision/recall/AUC | 0728 batch (prior) | offline OOF (training) |
|---|---|---|---|
| wait | 0.986 / 0.929 / 0.986 | 0.988 / 0.938 / 0.989 | 0.930 |
| promote | 0.857 / 0.963 / 0.993 | 0.902 / 0.975 / 0.997 | 0.952 |
| quarantine | 0.246 / 0.700 / 0.947 | 0.327 / 0.755 / 0.961 | 0.950 |

**wait/promote replicate almost exactly across two independent live batches**
run on different episode cohorts, different days -- this is the evidence
that justified going active on those two classes (Section 4). Quarantine's
low precision is now confirmed twice, not a fluke of one batch.

Caveat unchanged from 0728: both batches select episodes for historical
reliability across the same scenes the training set was built from -- a
repeated-scenario check, not a strict held-out/OOD test. `unseen30v2`'s yield
bug (see the 07-30 investigation) is what's blocking a real OOD check and
remains unresolved, deprioritized per the same user direction noted in
Section 0.

## 3. Combined-batch quarantine threshold sweep (13086 rows, 213 real quarantine examples)

Regenerated the 0728 batch's dwell dataset too (26/29 episodes, 7673 rows,
same 2 episodes lost to the same JSON-corruption bug as before -- reproduces
the previously-reported numbers exactly, confirming the extraction method is
stable/repeatable across sessions). Combined with reliable30v3's 5413 rows
(13086 total, 213 real quarantine examples vs. 143 in 0728 alone) and swept
`quarantine_threshold` 0.50-0.98 (`code/sweep_quarantine_threshold.py`):

| threshold | precision | recall | F1 |
|---|---|---|---|
| 0.65 (prior default) | 0.297 | 0.737 | 0.423 |
| 0.75 | 0.403 | 0.671 | 0.504 |
| **0.85 (F1-optimal)** | **0.560** | **0.549** | **0.555** |
| 0.90 | 0.633 | 0.469 | 0.539 |
| 0.95 | 0.732 | 0.333 | 0.458 |

This is a real, smooth precision-recall curve (not a wall) -- confirms the
model carries genuine quarantine signal, the 0.65 default was simply
miscalibrated. `promote` precision/recall stay flat (0.883/0.970) across
every threshold tested -- raising the quarantine gate only reroutes
borderline cases into the promote-vs-wait argmax, it does not visibly hurt
promote quality. Threshold and promote/wait quality are cleanly decoupled.

**Recommendation, adopted in Section 4's launcher**: raise
`sequential_pair_promotion_model_quarantine_threshold` from 0.65 to 0.85
(F1-optimal). If false-positive quarantine is judged costlier than
false-negative in practice (not measured here -- a real cost tradeoff, not
asserted with data), 0.90-0.95 trades further recall for precision.

If a future batch shows this recalibration isn't enough on its own, the next
lever is not more volume from the same "historically reliable" pool (which
structurally under-produces quarantine examples at its 1.3-1.9% base rate) --
it's a batch that deliberately oversamples dwells from anchors already
flagged unreliable in the `confidently-wrong`/ICP-reliability-ceiling
investigations, then a retrain.

## 4. Phase 3: promote/wait live enforcement (quarantine stays shadow-only)

See `PHASE3_IMPLEMENTATION.md` in this folder for the full design rationale,
code changes, and verification. Summary: given Section 2's replicated
precision/recall for promote/wait vs. quarantine's still-weak numbers, and an
explicit user decision on how the model should interact with the existing
`_select_sequential_pair_relocalization` heuristic gates, promote/wait went
active (`--sequential_pair_promotion_model_active_promote`) while quarantine
remains 100% heuristic-controlled
(`_record_next_anchor_trend`/`--sequential_pair_quarantine_mode`) --
unchanged by this work.

A 30-episode batch (`promotion_active_promote_30ep_20260731`, same 30
episode_idx values as `reliable30v3` for a direct before/after comparison on
identical episodes) is queued to run automatically overnight behind the
currently-running `unified_shadow50_retry4` (Route 2) -- see
`PHASE3_IMPLEMENTATION.md` Section "Overnight smoke test" for the queue
mechanism. Outcome not yet known as of this writing.
