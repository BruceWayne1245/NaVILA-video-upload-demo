# 2026-07-28 — First iteration of a learned promotion/quarantine/wait controller: dataset, model, and validation against the mechanism A/B/C episodes from `2026-07-28-downgrade-batch-mechanism-failure-classification`

## 0. Motivation and scope

`2026-07-28-downgrade-batch-mechanism-failure-classification/MODIFICATION_PLAN.md` scoped two parallel tracks to close the mechanism gaps found in that audit: "line 2" (patch the existing hand-written promotion/quarantine gates — `MODIFICATION_PLAN.md`) and "line 1" (replace the decision function itself with a model trained on the same per-attempt diagnostics `candidate_promote`/`_record_next_anchor_trend`/Injection A already consume). This document is the first iteration of line 1.

**Important distinction from `2026-07-21-icp-reliability-signal`**: that investigation trained a model to answer "is this one reading accurate" (a single-attempt classifier, AUC-capped at ~0.84 by the ~16% of readings that are scalar-feature-indistinguishable "confidently wrong"). This model answers a different, richer question — "given everything seen so far in this candidate's dwell (not just the current attempt), should the system promote / quarantine / keep waiting right now" — and, because it has access to the whole dwell history rather than one reading, it is not bound by the same single-reading ceiling.

## 1. Dataset

- 288 usable episodes (of 392 with saved `icp_replay_dataset/anchors.json`; 81 missing measurements, 23 unparseable/truncated trajectory JSONL from known infra crashes), spanning **16 distinct batches** from 2026-07-06 to 2026-07-28.
- 2,344 `current`/`next` dwell-sequences reconstructed by grouping `covisibility_records` by `attempt` and tracking the two live anchor roles (same method as the sibling mechanism-classification document). Dwell length: median 11 attempts, mean 46.7, 17.3% run 51+ attempts.
- 96,206 (dwell, attempt) rows. Every row is 100%-labelable: `icp_replay_dataset/anchors.json` gives ground-truth world pose for every anchor, so the candidate's true distance to the robot's true position (from the trajectory JSONL) is always computable — no missing-label problem.
- **Label** (hindsight, using the full dwell window — this uses future-within-dwell information, which is fine for a *label*, but never leaks into a feature): `promote` if ground-truth distance ≤ 0.75 m (matches `promotion_close_radius_m`) at this attempt, whether or not the historical heuristic actually promoted there; `quarantine` only for the final attempt of a dwell that (a) resolved via a real transition (not just the episode ending mid-dwell) and (b) never got within 0.75 m at any point in the whole dwell; `wait` otherwise. Label distribution: wait 81.8%, promote 16.9%, quarantine 1.4%.
- **Features are strictly causal** (only attempts up to and including the current one): raw per-attempt diagnostics for both `current` and `next` roles (`confidence`, `inlier_count`, `icp_best_to_second_score_ratio`, `icp_near_tie_basin_count`, `match_class` one-hot, residuals, `overlap_ratio`, `corridor_degeneracy_ratio`), a `U` reliability score for both roles (same formula as `2026-07-21`'s Injection A), rolling mean/std of `next`'s distance/confidence/ratio over the dwell so far, `current`'s own rolling bad-fraction history, and dwell position (`attempt_in_dwell`).

Extraction script: `code/extract_dwell_dataset.py`. Runtime: ~35s for all 288 episodes (no Isaac/VLM needed, reads already-saved `eval_results/`).

## 2. Model and headline results

`sklearn.ensemble.HistGradientBoostingClassifier` (sklearn 1.2.2, `navila-vlm` conda env — matching `2026-07-21`'s choice), inverse-frequency class weighting, 5-fold **episode-grouped** CV (`GroupKFold`, no episode's rows split across train/val — same discipline as `2026-07-21`).

| class | AUC (one-vs-rest) |
|---|---|
| wait | 0.930 |
| promote | 0.952 |
| quarantine | 0.950 |

Pooled balanced accuracy 0.855 ± 0.043 across folds. **Both promote and quarantine AUC exceed the 0.84 ceiling `2026-07-21` found for single-reading accuracy** — consistent with the hypothesis that a model with dwell-history access is not bound by that ceiling (the ceiling is specifically about readings that are indistinguishable *on their own*; aggregated over several readings, most of them stop being indistinguishable).

Baseline comparison (naive "promote iff `next_estimated_distance_to_anchor_m` ≤ 0.75 m, else wait" — i.e. what `close_enough` alone already does today): 0.839 accuracy but **zero recall/precision on quarantine** (a single-reading distance threshold cannot express "give up on this candidate," by construction). The trained model reaches 0.79 recall on quarantine.

Top permutation-importance features: `next_estimated_distance_to_anchor_m` (dominant, as expected), then `attempt_in_dwell` and `next_dist_rollstd` — i.e. the two next-most-important signals are dwell position and within-dwell volatility, neither of which any existing heuristic (`quality_ok`, `close_enough`, `trend_ok`, Injection A's `bad_fraction`) uses. `cur_confidence` and `cur_bad_fraction_hist` also rank in the top 10, meaning the model is using `current`'s own reliability history when deciding about `next` — precisely the cross-check `2026-07-28-downgrade-batch-mechanism-failure-classification/FINDINGS.md` mechanism B found missing from `_record_next_anchor_trend`.

## 3. Validation against the mechanism A/B/C episodes

Using **out-of-fold** predictions only (i.e., for each episode, the prediction comes from a fold that never trained on that episode's rows — no leakage):

| mechanism | episodes | result |
|---|---|---|
| A (promotion ignores confidence/ambiguity) | 19, 88, 95, 427 | model recall on true "should-promote" attempts: 1.00, 0.98, 1.00, 1.00 |
| C (oscillating, heuristic frozen the whole episode) | 276, 646 | **1.00 / 1.00** — the model catches both the 0.05 m (ep276) and 0.025 m (ep646) windows that 231 real heuristic attempts each never caught |
| B (current poisoned, trend-quarantine cascades) | 344 | no true-promote attempts exist in this episode at all (robot never got genuinely close to anything); model correctly promotes 0 times too. Quarantine recall 0.73 (8/11) |
| B | 355 | **model recall 0.00 on 7 true-promote attempts** — see §4 |

Mechanism C is the strongest result in this pass: both fully-frozen episodes are fixed at the per-attempt decision level.

## 4. Two follow-ups (this session, `code/calibrate_and_investigate_oscillation.py`)

### 4.1 Quarantine threshold calibration

Raw argmax (≈ threshold 0.5 on `proba_quarantine`) gives precision 0.186 / recall 0.780 / F1 0.300 — usable but not the best operating point. Quarantine's PR-AUC (average precision) is **0.477** against a 1.35% base rate (a ~35x enrichment over random), so the *ranking* is good even though precision at any single threshold looks numerically low (expected at this base rate).

| threshold | precision | recall | F1 |
|---|---|---|---|
| 0.20 | 0.089 | 0.878 | 0.162 |
| 0.50 (≈ argmax) | 0.186 | 0.780 | 0.300 |
| 0.60 | 0.229 | 0.744 | **0.350** |
| 0.70 | 0.292 | 0.697 | 0.411 |
| 0.80 | 0.376 | 0.615 | 0.467 |
| 0.90 | 0.539 | 0.460 | 0.496 |

**Recommended operating point: threshold 0.6–0.7** (best F1 region; recall stays above 0.70 while precision roughly doubles vs. argmax). Given the existing `reliability_quarantine_max_chain` cascade cap already bounds the damage from an over-eager quarantine call, erring slightly toward recall over precision at this stage is reasonable — but this should not be hardcoded into the model artifact; see `INTEGRATION_PLAN.md` for why it needs to stay a separately-tunable decision-policy parameter.

### 4.2 Is ep355's fully-missed dwell evidence of a general weakness on extreme oscillation? No — checked and rejected.

Hypothesis going in: ep355's dwell (`next_estimated_distance_to_anchor_m` swinging 0.79 → 8.89 → 8.88 → 8.96 → 1.78 → 1.80 → 8.67 m across 7 consecutive attempts, while ground truth stayed a flat ~0.43 m) represents a class of "extreme bimodal oscillation" the model handles poorly.

Checked against the full 96,206-row dataset:
- Readings this extreme ("reported > 5 m while ground truth < 2 m") are rare: 0.36% of all readings, present in 47/2,344 dwells (2.06%), spread across 9 different batches (not concentrated in one batch/scene/config) and 36 distinct episodes.
- Swing magnitude is mostly modest project-wide: median within-dwell (max − min) of reported distance is 0.81 m; only 2.12% of dwells exceed a 5 m swing.
- **Model recall on true-promote attempts is *higher*, not lower, inside dwells that contain such an outlier reading: 0.907 (n=730) vs. 0.849 (n=15,512) in dwells without one.** This directly contradicts the hypothesis.

**Conclusion**: ep355's 0/7 is not evidence of a systematic blind spot — it's an unlucky small-sample instance (n=7) inside a population the model otherwise handles somewhat *better* than average. No targeted feature engineering or additional data collection for this pattern is recommended at this time.

## 5. Artifacts

- `code/extract_dwell_dataset.py`, `code/train_model.py`, `code/oof_check.py`, `code/calibrate_and_investigate_oscillation.py` — full pipeline, reproducible from already-saved `eval_results/` (no Isaac/VLM).
- The 96 MB labeled dataset CSV and the prototype `.pkl` are **not** checked into this repo (too large, and a bare pickle is not a durable/versioned artifact — see `INTEGRATION_PLAN.md` §1 for why a production version needs a proper bundle format, not this prototype file).

See `INTEGRATION_PLAN.md` for how this plugs into `route_memory_agent.py`/`round_trip_eval.py`.
