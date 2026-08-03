# 2026-07-21 — Layer-1 ICP-reliability signal: feasibility, data, and the 0.84 ceiling

## Why this investigation exists (background)

The project is at a fork. A ground-truth deep dive on the `canonical_report_next_stopgate_100ep_20260720` batch (this session; see the "batch2 failure" and "gating-mechanism" analysis that motivated this doc) established:

1. **The dominant return-failure mode is not navigation, it's the stop/gating decision.** 8/19 return "failures" in the outbound-success subset physically ended **within the 3 m success radius** (0.01–2.64 m from start) yet were logged as failures — the robot walked home but the system never registered a valid stop. If the stop decision worked, return would be ~15/26 (~58 %) instead of 7/26 (27 %).

2. **The immediate cause is a permanent tracker "pin".** In 13 stuck episodes, `current` advances normally until it lands on a degenerate anchor, then freezes for the rest of the episode. The robot keeps walking home while the tracker (and therefore the injected hint / `stop_gate` distance authority) is frozen and wrong.

3. **Root cause is structural, not a single bad threshold.** Almost every `next`-side gate — `closure_precheck`, `quarantine` (trend), promotion `quality_ok` — is a *differential* check measured **relative to `current`**. So a bad `current` (especially a "confidently wrong" one, whose `confidence`/quality saturate near 1.0) poisons all of them. The one supervisor designed to judge `next` **independently** of `current` (`_record_next_anchor_quality`, 2026-07-15, uses `best_to_second_score_ratio`) is **OFF** in the canonical config (it caused an unbounded cascade for lack of a stall-relief valve). The dedicated escape hatch — `quarantine` skipping a bad `next` — **fired 0 times across all 13 stuck episodes**, because it keys on *position* disagreement (blind to the bearing/rotational aliasing that is the actual defect) normalized by a distance-inflated sigma that pushes the trip point to ~2–4 m.

The conclusion pointing here: **the system is missing an absolute, `current`-independent, per-ICP-reading reliability signal.** Both candidate routes need it:

- **Route 1** (keep heuristic gating): wire such a signal into quarantine / promotion / stop-confidence.
- **Route 2** (learn the gating): the signal *is* a learned reliability model.

This investigation tests whether that signal is buildable, how good it can be, and how much data exists to train it.

---

## Data available

`eval_results/` holds **848 episode directories**. Of those, the `sequential_pair`-era batches (2026-07-04 onward, which emit `route_relocalization_diagnostics.covisibility_records` — the per-anchor per-attempt ICP diagnostics) total **~470 episodes**: `canonical_report_next_stopgate_100ep` (89), four ~50 ep canonical/shadow batches (185), plus ~20 ep and ~11 ep batches.

**Every reading is auto-labelable from ground truth.** For each covisibility record we reconstruct the anchor's true world position (accumulate `|command[:2]|·0.02 s` along the outbound trajectory, look up each anchor's `anchor_distance_from_start_m` against that curve — the same 0.000 m-verified method used in the 2026-07-19/20 investigations), then compare the record's `estimated_bearing_to_anchor_deg` / `estimated_distance_to_anchor_m` against the true bearing/distance from the robot's true pose at that attempt's step. **The label needs no human annotation** — it is exactly the ground-truth accuracy of the reading.

For this feasibility pass we extracted **90,076 labeled readings** from **88 episodes across 3 batches** (`100ep_stopgate`, `50ep_stopgate`, `shadow_hint_swap_50ep` — deliberately mixing configs). Label = "bad" iff bearing error > 30° (44.6 % positive — balanced). Scaling to all ~470 episodes yields ~250 k+ labeled readings.

Features are the record's own **`current`-independent** fields: `overlap_ratio`, `corridor_degeneracy_ratio`, `icp_near_tie_basin_count`, `icp_basin_count`, `icp_best_to_second_score_ratio`, `icp_best_to_second_rotation_delta_deg`, `icp_best_to_second_translation_delta_m`, `confidence`, `inlier_count`, `mean_residual_m`, `median_residual_m`, `anchor_points`, `current_points`, `anchor_z_span_m`, `current_z_span_m`, `estimated_distance_to_anchor_m`, `localizability` min-eigenvalue + condition number, and one-hot `match_class` / `icp_ambiguity`.

Validation is **episode-grouped 5-fold CV** (`GroupKFold` by `tag+episode`) — no reading from a test episode is ever in training, so the AUCs below are genuine held-out-episode numbers.

---

## Results

### 1. Single-signal discriminative power (AUC, symmetrized to ≥ 0.5)

| Signal | AUC | | Signal | AUC |
|---|---|---|---|---|
| `inlier_count` | **0.787** | | `overlap_ratio` | 0.742 |
| `icp_best_to_second_score_ratio` | **0.780** | | `icp_near_tie_basin_count` | 0.692 |
| `localizability` min-eigenvalue | **0.771** | | `current_points` | 0.615 |
| `confidence` | 0.759 | | `estimated_distance_to_anchor_m` | 0.589 |
| `mean_residual_m` | 0.753 | | `icp_basin_count` | 0.549 |
| `median_residual_m` | 0.748 | | **`corridor_degeneracy_ratio`** | **0.523** |

**Confirms the long-standing skepticism about specific signals** — `corridor_degeneracy_ratio` (0.523) and `icp_basin_count` (0.549) are near-useless. **But refutes it for the others**: `inlier_count`, `best_to_second_score_ratio`, `localizability`, `confidence`, and the residuals are individually usable (0.75–0.79). These had never been evaluated as a *combined absolute reliability gate* before this pass.

### 2. Direct signal use ≈ trained model

| Method | AUC | Training needed |
|---|---|---|
| Best single signal (`inlier_count`) | 0.787 | none |
| **Hand z-score sum of top-4** | **0.799** | **none** |
| Logistic regression (top-6 linear) | 0.801 | trivial |
| **HistGradientBoosting, all features** | **0.841** | full pipeline |

**A zero-training hand combination of 4 signals already reaches 0.799.** The trained GBDT buys only **+0.04**. Operating points of the GBDT: at 90 % recall of bad readings, precision 69 %; at 76 % precision, recall ~50 %. Feature importance (permutation): `mean_residual_m` dominates, then `current_z_span_m`, `localizability` condition number, `inlier_count`, `corridor_degeneracy_ratio` (only useful in nonlinear interactions), `overlap_ratio`.

### 3. The 0.84 ceiling — the strategic fact

The AUC ceiling with these scalar features is **~0.84**. ~16 % of readings are **"confidently wrong"**: identical to good readings on every scalar diagnostic (high `confidence`, `clean_full_pose` `match_class`, high `overlap`, few basins) yet the pose is wrong. **No classifier on these features can separate inputs that are identical in feature space** — this is a property of the features, not model capacity.

Three tiers of the confidently-wrong problem:

- **(a) ~0.80 — catchable now** by a simple combination of existing scalar signals. This is the immediately actionable part.
- **(b) Possibly higher — untested** with richer inputs: raw point clouds (`anchor_points_xyz` / `current_points_xyz`), the full basin landscape (`icp_top_basins`, not just the scalar near-tie count), or multi-view temporal consistency (a truly wrong anchor is inconsistent across viewpoints — invisible to a single-reading label). This is a bigger model and a real research bet.
- **(c) Physically irreducible from LiDAR geometry alone.** In a self-similar corridor, two different positions produce genuinely near-identical point clouds — no model can distinguish identical inputs. This is exactly why the project repeatedly finds LoFTR/**vision beats LiDAR 5–10×** in corridor-degenerate geometry (wall texture/pictures break the geometric symmetry LiDAR cannot). For tier (c) the fix is **sensing** (fuse vision back) or **mapping** (motion-integrated multi-frame submaps to add geometric constraint), **not** a better classifier.

---

## Conclusions & recommendation

1. **An absolute, `current`-independent reliability signal is buildable and is far better than what the gates use today** (the position-only quarantine that fired 0/13). A zero-training combination of `inlier_count + best_to_second_score_ratio + localizability + mean_residual` reaches ~0.80.

2. **For Route 1, no ML is required.** The trained model is a marginal (+0.04) upgrade over just combining the signals. Use the signals directly first; add the model only if that +0.04 turns out to matter after seeing real return-rate impact. The two top signals (`inlier_count`, `best_to_second_score_ratio`) are already on the `AnchorRelocalization` dataclass — zero plumbing for a first version.

3. **Route 2's ML ambition is capped at tier (b).** A scalar-feature model is a confidence signal, not a decision-owner: at AUC 0.84 it cannot cleanly decide "promote / skip / stop." To push past 0.84 needs point-cloud/multi-view features (a bigger model); and a residual is irreducible from LiDAR and needs vision fusion or mapping changes. So the realistic near-term value of Route 2 **is** the Layer-1 confidence signal — which is what Route 1 needs too. **The routes converge on the same first step.**

4. **Next step (low-regret):** wire the ~0.80 signal into the gates (see `MODIFICATION_PLAN.md`), then run an offline counterfactual replay on the 13 stuck + 8 stop-decision episodes to quantify how many return-successes it recovers **before** writing any production loop. Whether to then invest in point-cloud features / vision fusion is the decision that actually forks Route 1 vs Route 2 — and it should be made against that measured return-rate gain, not in advance.

## Reproduction (`code/`)

- `extract_features.py` — builds the labeled dataset (`icp_dataset.csv`) from `eval_results` via ground-truth anchor reconstruction.
- `train.py` — single-signal AUCs, GBDT grouped-CV AUC, operating points, permutation importance.
- `deep_analysis.py`, `deep_analysis2.py`, `deep_analysis3.py`, `se2.py` — ground-truth reconstruction + faithful closure-check replay (extended from the 2026-07-20 deep-dive).
- `paths.py`, `batch2.py`, `peranchor.py`, `lockin.py`, `whichlink.py` — the batch2 failure classification, per-anchor ICP breakdown, pin-anchor time-course (H1-vs-H2), and quarantine-firing / position-vs-bearing checks that established the background above.

All scripts are ad hoc (scratch), CPU-only, and read already-saved `eval_results` — no Isaac/VLM needed. Trained with the `navila-vlm` conda env (sklearn 1.2.2).

---

## 2026-07-21 model follow-up

The scalar feasibility result above was followed by two independently isolated
model versions. V1 confirmed useful ranking but failed all trusted-risk gates;
V1.1 added full ICP basins, current/next pair consistency, and causal temporal
features and became much stronger under physical-episode-grouped nested CV.
V1.1 is still development-only because all historical runs were used for model
development and no prospective batch has been evaluated.

The complete record is indexed in [`README.md`](README.md), with metrics and a
fair comparison in [`MODEL_WORK_SUMMARY.md`](MODEL_WORK_SUMMARY.md), provenance
in [`CODE_AND_PROVENANCE.md`](CODE_AND_PROVENANCE.md), and the frozen execution
order in [`NEXT_STEPS.md`](NEXT_STEPS.md). Neither model is authorized for
enforcement.
