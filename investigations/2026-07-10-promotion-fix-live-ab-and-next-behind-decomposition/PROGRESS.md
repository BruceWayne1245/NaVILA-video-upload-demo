# 2026-07-10 (continued) — Daily progress: yaw-reliability diagnostics implemented (steps 1-2 of the problem-2 execution plan)

**Context**: following `investigations/2026-07-09-anchor-promotion-lag-and-icp-rotational-error/route_memory_literature_survey.md`'s recommendations for **Problem 2** (ICP bearing error >10° is 69% unexplained by any currently-logged diagnostic — see that investigation's `FINDINGS.md` §3). Problem 1 (promotion timing) is intentionally **not** revisited here — this session's live A/B (this folder's `FINDINGS.md`) already validated the `promotion_use_pre_closure_estimates` fix and found the residual gate-timing bug down to ≈0.5% of behind attempts, with 0% real anchor-staleness (§4-5 of that document); the survey's SPRT/BOCPD/HMM promotion-gate proposals are deprioritized accordingly, per the agreed 5-step plan for problem 2 only.

**The agreed 5-step plan** (problem 2 only): (1) yaw-curve + Hessian yaw-observability diagnostics, diagnostic-only; (2) serialize `alias_score` (a prerequisite the plan's own offline-ablation stage needs, found missing this session); (3) measure how much of the 69% unexplained bucket the new diagnostics actually explain, and if it clears 40-50%, add an opt-in downgrade gate; (4) Scan Context / correlative-occupancy verifier, only if (3) falls short; (5) TEASER++ offline verification / learned registration, long-term/shelved. **This entry covers steps 1 and 2, implemented and unit-tested. Steps 3-5 are not started.**

---

## 1. Implemented: yaw-curve diagnostics (full 24-seed sweep, not just top-2 basins)

**Where**: `relocalization.py`, new `_yaw_curve_diagnostics()` function, called from `sequential_pair_anchor_relocalization()` immediately after `icp_seed_sweep_2d()` (no extra ICP calls — reuses the seed sweep already being computed) and stored as `record["yaw_curve"]` in every covisibility record.

**Why**: `_summarize_icp_basins`'s existing `near_tie_basin_count` / `best_to_second_score_ratio` only compare the top-2 *basins* — clusters formed by a discrete translation/rotation distance threshold (`_cluster_icp_basins`, 0.35m / 20°). A broad-but-single-basin plateau in the raw per-seed score landscape, narrower than that clustering threshold but still indicating a poorly-constrained yaw, is invisible to it — exactly the survey's critique in §2.1 ("现有 near-tie 定义太窄").

**New fields per covisibility record** (`record["yaw_curve"]`):
- `yaw_score_entropy` / `yaw_score_normalized_entropy`: Shannon entropy of the (normalized) score distribution across all 24 yaw seeds.
- `yaw_peak_width_deg`: angular span, among seeds scoring within 15% of the top score, between the two most different such seeds — a wide value means many meaningfully-different orientations all look nearly as good as the winner, even if a discrete basin-clustering pass would still call it "one basin."
- `yaw_top1_next_distinct_gap_deg` / `yaw_top1_next_distinct_score_ratio`: gap (in degrees) and score ratio to the best-scoring seed that's at least 20° away from the winner (independent of translation, unlike the existing basin-based near-tie check).

**Validated on hand-built synthetic geometry** (`tests/test_geometry_pipeline.py::TestSequentialPairYawDiagnostics`), through the public `sequential_pair_anchor_relocalization()` entry point (not the private function directly, matching this file's existing convention):
- A 4-fold rotationally-symmetric "plus/cross" shape (genuinely ambiguous every 90°) → `yaw_peak_width_deg` ≥ 90°, a distinct 90°-away seed scoring within 5% of the winner (`yaw_top1_next_distinct_score_ratio` ≥ 0.95) — correctly flagged as a wide plateau.
- An asymmetric L-shape (long wall + a clearly shorter, unequal perpendicular arm — no rotational symmetry) → `yaw_peak_width_deg` < 5° — correctly flagged as a single sharp, isolated peak.

---

## 2. Implemented: yaw-specific observability from the correspondence Hessian

**Where**: `relocalization.py`, extended the existing `_localizability_from_correspondences()` (already computed for every accepted match; previously only reported the full 3×3 eigen-decomposition of the point-to-plane Hessian, which mixes translation and rotation directions and doesn't answer "is yaw specifically well-constrained").

**Why**: per the survey's §2.2 (X-ICP/LP-ICP framing) — the existing `weakest_direction`/`quality` fields answer "is *some* direction in (tx, ty, θ)-space weak", but a corridor-style ambiguity (translation trading off against a compensating rotation — the exact "rotational self-alias" signature `investigations/2026-07-09-.../FINDINGS.md` §3.5 documented at `ep1040`/anchor4, `clean_full_pose` + healthy overlap/inliers yet θ confidently wrong by 46-65°) can leave the existing `quality="full"` while θ itself is only weakly constrained once its correlation with translation is accounted for.

**Method**: the Schur complement of the rotation block against the translation block of the same 3×3 Hessian already being computed — `yaw_marginal_information = H[θθ] − H[θ,t] @ inv(H[t,t]) @ H[t,θ]` — the Fisher information remaining on θ *after* optimally letting translation absorb whatever correlated ambiguity it can. Normalized by the same `max_eig` already used for the existing `normalized_eigenvalues`, so it's comparable across anchors/point densities.

**New fields in `record["localizability"]`**: `yaw_marginal_information`, `yaw_normalized_marginal_information`, `yaw_observability` (`"full"` / `"weak"` / `"unknown"` — `"unknown"` specifically when the translation block itself isn't invertible, e.g. a pure corridor with one totally unconstrained translation axis; deliberately does **not** default to `"full"` in that case, since the question "is yaw well-constrained relative to translation" doesn't have a clean answer when translation itself is degenerate).

**Validated** (`tests/test_geometry_pipeline.py::TestSequentialPairYawDiagnostics`):
- Well-conditioned rectangle outline → `quality="full"` (unchanged, pre-existing field) **and** `yaw_observability="full"` (new field, positive control).
- Pure corridor (two parallel walls, translation-along-corridor totally unconstrained) → `yaw_marginal_information is None`, `yaw_observability="unknown"` — confirms the new code path degrades gracefully and does not silently claim "full" when the underlying math can't support the claim.
- **Not yet found**: a synthetic geometry demonstrating the specific "old `quality="full"`, new `yaw_observability="weak"`" combination that is the whole point of this diagnostic (the real-world `ep1040`/anchor4 signature). Several hand-built candidates (single wall + small end-marker, short-arm L-shapes) were tried and empirically checked — none reproduced it; the real failure mode documented in `investigations/2026-07-09-.../FINDINGS.md` §3.5 is evidently a genuine local-minimum/near-degeneracy artifact of real, denser, noisier point clouds, not something a few hand-drawn synthetic corners easily reproduce. This is flagged as an open item for step 3 below (real offline replay data, not synthetic geometry, is the right place to check whether this new field actually fires on the known-bad real anchors).

---

## 3. Implemented: `alias_score` serialization (blocking-prerequisite fix, not on the original numbered list)

**Where**: `route_memory_agent.py::RouteMemoryAgent._anchor_summary()` — previously silently dropped `RouteAnchor.alias_score` when building the per-anchor dict written into `route_memory.anchors` in the measurement JSON, even when `--sequential_pair_promotion_alias_aware` was on and `compute_anchor_alias_scores()` had populated it in memory.

**Why this blocks step 3**: `investigations/2026-07-09-.../DATA.md` §G and this folder's `FINDINGS.md` methodology notes both independently hit this same gap — any offline ablation that wants to check `alias_score` against the new yaw diagnostics (or against anything else, post-hoc) couldn't, because the value never made it into the serialized data in the first place. Fixed as a one-line addition; `None` until `compute_anchor_alias_scores()` has actually run (i.e. `alias_aware` off → always `null`, unchanged from before other than the key now existing).

**Validated**: `tests/test_route_memory_agent.py::ComputeAnchorAliasScoresIntegrationTest::test_alias_score_is_serialized_in_summary` — confirms `agent.summary()["anchors"][i]["alias_score"]` is `None` before `compute_anchor_alias_scores()` runs and matches `agent.anchors[i].alias_score` exactly afterward, plus a `json.dumps` round-trip check.

---

## 4. Test results

All changes are purely additive (new dict keys; no existing field removed, renamed, or changed in meaning) and **no new CLI flag was added** — both diagnostics are computed unconditionally, matching how `_localizability_from_correspondences`/basin-clustering were already always-on diagnostics before this change, not gated behind `quality_policy`. No live decision logic (promotion gates, closure fusion, match_class assignment) reads any of these new fields yet — they are purely informational until step 3 decides whether they're worth acting on.

- `tests/test_geometry_pipeline.py`: 71/71 pass (4 new: `TestSequentialPairYawDiagnostics`'s two yaw-curve tests and two localizability tests).
- `tests/test_route_memory_agent.py`: 100/100 pass, 14 pre-existing skips unchanged (1 new: `test_alias_score_is_serialized_in_summary`).
- Full `tests/` discovery: 214 tests, only the pre-existing unrelated `test_loftr_matching` import error (`cv2` not installed in this shell — documented in every prior session in this project) remains.
- `py_compile` clean on `relocalization.py`, `route_memory_agent.py`, and both modified test files.

A snapshot of the modified files (`relocalization.py`, `route_memory_agent.py`, `test_geometry_pipeline.py`, `test_route_memory_agent.py`) is included in this folder's `code/` subdirectory, matching the convention established in `investigations/2026-07-09-.../code/`.

---

## 5. Not yet implemented (steps 3-5 of the agreed plan)

**Step 3 — measure explanatory power, then opt-in downgrade gate.** Not started. Needs an offline replay pass (reusing `--capture_icp_replay_dataset`, same harness as prior sessions) against the already-identified worst unexplained groups from `investigations/2026-07-09-.../FINDINGS.md` §3.4 (`ep1040`/anchor4, `ep187`/anchor8, `ep187`/anchor14, `ep680`/anchor5, etc.) to check whether `yaw_peak_width_deg` / `yaw_observability="weak"` actually fires on those specific real readings — this is the concrete test of whether today's diagnostics work on the real failure mode, not just synthetic geometry (see §2's open item above). Target from the agreed plan: explain 40-50% of the 69% unexplained bucket before adding any gating. If it clears that bar, the gate itself should follow the project's established pattern: opt-in flag, default off, downgrade only (`anchor_heading_reliable=False`, bearing hint falls back to translation/anchor-edge-geometry-only), never an outright reject of dx/dy.

**Step 4 — Scan Context / correlative-occupancy yaw verifier.** Not started, contingent on step 3 falling short of the 40-50% target.

**Step 5 — TEASER++ offline verification / learned registration.** Not started; per the agreed plan this is long-term/shelved regardless of step 3's outcome.

## Next steps

1. Run step 3's offline replay against real captured data (not synthetic shapes) for the known worst-unexplained (episode, anchor) groups; report the explained fraction.
2. Depending on that result, either design the opt-in downgrade gate (if ≥40-50% explained) or move to step 4 (Scan Context verifier) for the remainder.
3. If a genuine "confidently wrong, quality=full, yaw_observability=weak" synthetic example is ever found (useful for a clean, fast-running regression test independent of real capture data), add it to `TestSequentialPairYawDiagnostics` — not blocking, since real-data validation in step 3 is the actual bar that matters.
