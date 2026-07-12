# 2026-07-10/12 — Daily progress: yaw-reliability diagnostics (steps 1-2), offline validation (step 3), and Scan Context yaw verifier (step 4)

**Context**: following `investigations/2026-07-09-anchor-promotion-lag-and-icp-rotational-error/route_memory_literature_survey.md`'s recommendations for **Problem 2** (ICP bearing error >10° is 69% unexplained by any currently-logged diagnostic — see that investigation's `FINDINGS.md` §3). Problem 1 (promotion timing) is intentionally **not** revisited here — this session's live A/B (this folder's `FINDINGS.md`) already validated the `promotion_use_pre_closure_estimates` fix and found the residual gate-timing bug down to ≈0.5% of behind attempts, with 0% real anchor-staleness (§4-5 of that document); the survey's SPRT/BOCPD/HMM promotion-gate proposals are deprioritized accordingly, per the agreed 5-step plan for problem 2 only.

**The agreed 5-step plan** (problem 2 only): (1) yaw-curve + Hessian yaw-observability diagnostics, diagnostic-only; (2) serialize `alias_score` (a prerequisite the plan's own offline-ablation stage needs, found missing this session); (3) measure how much of the 69% unexplained bucket the new diagnostics actually explain, and if it clears 40-50%, add an opt-in downgrade gate; (4) Scan Context / correlative-occupancy verifier, only if (3) falls short; (5) TEASER++ offline verification / learned registration, long-term/shelved.

**Status as of 2026-07-12**: steps 1-2 implemented and unit-tested (2026-07-10, §1-4 below). Step 3's offline validation (§6) found the new diagnostics do **not** clear the 40-50% bar (best calibrated operating point: +9pp of the unexplained bucket at a 10% false-positive cost on clean readings; `yaw_normalized_marginal_information` shows no discrimination at all, same negative result as `corridor_degeneracy_ratio` before it) — getting a *methodologically sound* version of that result took three corrected attempts, documented in full in §6 because the mistakes are as informative as the result. Per the agreed decision rule this triggered step 4, now implemented (§7): a Scan Context-based independent yaw cross-check. Two full offline A/B replay campaigns (with vs. without step 4) are running in the background as of this writing (§8) — results pending.

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

## 5. Step 3 target restated

Needs an offline replay pass (reusing the existing `icp_replay_capture_hard11_20260706_accumulated` capture — raw anchor + per-return-step point clouds and ground-truth poses, no Isaac Sim needed) against real data, to check whether `yaw_peak_width_deg` / `yaw_observability="weak"` actually discriminate clean readings from the still-unexplained >10° bearing-error bucket. Target from the agreed plan: explain 40-50% of that bucket before adding any gating. §6 covers how this was actually done, including three attempts before the result could be trusted.

---

## 6. Step 3: offline replay validation — three attempts, two of them wrong for reasons worth recording

**Attempt 1 (per-anchor radius sweep, wrong scope, corrected by direct instruction):** first pass matched only the 9 worst-known (episode, anchor) groups from `investigations/2026-07-09-.../FINDINGS.md` §3.4, each against capture steps within a fixed 2m radius — not the full 9-episode dataset this project's prior offline analyses always used. Corrected after being told directly: this project's established practice is a full parallel run across every available episode (`icp_replay_capture_hard11_20260706_accumulated` covers 10 of the hard-11 set; `ep678`'s `anchors.json` is corrupted beyond what the generic repair tooling from this session's earlier JSON-repair work could fix — same corruption class documented in `investigations/2026-07-09-.../DATA.md`, excluded here too).

**Attempt 2 (raw-candidate replay, methodologically valid but answers a different question than intended):** matched every captured step against its ground-truth-projected current/next anchor pair directly via `sequential_pair_anchor_relocalization`, bypassing `RouteMemoryAgent` entirely. This is `investigations/2026-07-09-.../DATA.md`'s "Category C" methodology (raw per-role ICP candidates, not accepted/fused events) — confirmed consistent with that document's own prior numbers (~63-66% of the >10° bucket explained by existing diagnostics either way). Two negative/weak results here: `yaw_normalized_marginal_information` showed **no separation at all** between clean (≤5°) and still-unexplained (>10°, existing-diagnostics-clean) populations (median 0.894 vs 0.894) — the same negative-result shape as `corridor_degeneracy_ratio` in `investigations/2026-07-09-.../FINDINGS.md` §3.2. `yaw_score_normalized_entropy` showed weak separation, mostly saturated near 1.0 in both populations. `yaw_top1_next_distinct_score_ratio` showed real separation (clean median 0.391 vs unexplained median 0.686) — calibrated against the clean population's own percentiles: clean-p75 threshold → +25pp explained at a 25% false-positive rate (too noisy to act on); clean-p90 → +9pp at 10% FP; clean-p95 → +1.4% at 5% FP. **None of these operating points clear the 40-50% target.** But this whole attempt graded raw candidates, not the accepted/fused hint FINDINGS.md's original 69% figure was actually about — a scope mismatch identified after the fact, not before.

**Attempt 3 (full `RouteMemoryAgent` replay, matching the real "accepted event" population) — two further bugs found and fixed before the result could be trusted:**
1. Instantiating `RouteMemoryAgent` with `sequential_pair_geometry_source="accumulated"` (this capture's own original recorded config) while every `RouteAnchor.edge_from_previous` was left at its `[0,0,0]` default (no outbound walk was ever simulated to populate it) silently corrupted every belief-fusion reprojection — median bearing error 14.95° instead of this project's established ~5-7° for comparable configs. Fixed by using `sequential_pair_geometry_source="oracle"` instead (ground-truth anchor-to-anchor `world_pose` diff, fed via `RouteAnchor.metadata["world_pose"]`) — the exact substitution `investigations/2026-07-09-.../DATA.md`'s own header already documents as required for this capture ("the outbound odometry accumulator state isn't part of the capture"), which had already been read earlier in this same session and should have been applied the first time, not copied blindly from the captured run's own settings.
2. Parallelizing by splitting each episode's (stride-subsampled) steps round-robin across worker chunks (`steps[chunk_index::num_chunks]`) scrambled the temporal order **within** each chunk. `sequential_pair` can only ever advance one anchor per accepted attempt and depends on a temporally continuous run of steps to track identity — interleaving broke this completely. Caught by a sanity check comparing each chunk's first 3 events (median 5.15° error) against the rest (median 11.43°) — the *opposite* of what a normal cold-start transient looks like, and exactly what "every chunk is scrambled throughout, not just briefly cold at the start" predicts. Fixed by removing intra-episode chunking; parallelism now comes only from running each of the (up to) 10 episodes as one contiguous serial process.
3. A third issue, caught by directly checking reported `anchor_index` against a ground-truth arc-length projection (not just eyeballing bearing-error magnitude): replaying with this capture's own original `sequential_pair_promotion_mode=immediate` (this capture predates 2026-07-06's `bounded_evidence` entirely) reproduced 93-98% wrong anchor **identity** in several episodes (`ep408`, `ep187`, `ep994`) — the pre-existing "lead-lock cascade on repeating structure" bug documented in `investigations/2026-07-06-anchor-selection-and-icp-aliasing/`, not a rotational-ambiguity problem at all. Switched to the latest validated production config (`bounded_evidence` + `alias_aware` + `trust_aware_guard` + `promotion_use_pre_closure_estimates`, matching this session's own 2026-07-10 live A/B) so the replayed population's anchor identity is reliable and any remaining bearing error is much more likely to be genuine rotational ambiguity. (`ep408` specifically is expected to still show a high mismatch/error rate regardless of promotion config — its true robot position is stationary for most of the episode, an already-documented, unrelated bug; not treated as a methodology failure.)

**Lesson, stated directly because it was pointed out directly**: all three of the real bugs above (accumulated-geometry, chunk-interleaving, immediate-promotion-mode) trace to the same root cause — reconstructing a replay pipeline from first principles and inventing configuration/parallelization choices, instead of first finding and reusing this project's own already-validated recipes and settings (the DATA.md header's oracle-geometry note and the README's bounded_evidence/alias_aware history were both already available in context before the first attempt). This is why this section documents the wrong attempts in full, not just the final numbers.

---

## 7. Implemented: Scan Context yaw verifier (step 4)

**Trigger**: step 3 (§6) did not clear the 40-50% explanatory-power bar, so per the agreed plan this step proceeds.

**Where**: `relocalization.py`, new `_scan_context_yaw_check()`, called from `sequential_pair_anchor_relocalization()` right after ICP produces its own `theta`, stored as `record["scan_context_yaw_check"]`. Reuses this project's existing Scan Context infrastructure (`build_scan_context`, `column_shift_search_with_region`, `shift_to_yaw_rad` — the same functions `scan_context_anchor_relocalization` already uses in production) with no new dependency.

**Why this is a different kind of check than steps 1-2**: yaw-curve and yaw-observability only ever re-examine the *same* ICP computation more closely (the score landscape it already produced, the correspondence Hessian it already built) — neither can, even in principle, catch a case where ICP is a genuine, self-consistent local optimum that just happens to be wrong (the `ep1040`/anchor4 "clean_full_pose, confidently wrong by 46-65°" signature). Scan Context is a structurally different algorithm (global egocentric occupancy similarity via column-shift search, not iterative nearest-point minimization) with different failure modes — a disagreement between the two is evidence neither one alone can produce.

**New fields** (`record["scan_context_yaw_check"]`): `scan_context_yaw_deg`, `scan_context_similarity`, `scan_context_region_size`/`scan_context_region_ratio`, `icp_scan_context_yaw_agreement_deg` (angular difference between ICP's and Scan Context's independent yaw estimates).

**Sign convention verified against a known rotation, not just reasoned about** (given this session's track record on exactly this kind of mistake): `tests/test_geometry_pipeline.py::TestSequentialPairYawDiagnostics::test_scan_context_yaw_check_agrees_with_icp_on_a_known_rotation` constructs an asymmetric shape, rotates it by a known 40°, and confirms both `scan_context_yaw_deg` lands near 40° (within Scan Context's ~6°/sector resolution) and `icp_scan_context_yaw_agreement_deg` is small — confirming `scan_context_yaw_rad` and ICP's `theta` are directly comparable with no sign flip needed. A second test confirms the check runs (without asserting a specific relationship) on a rotationally-symmetric shape, where genuine multi-valued disagreement is expected, not a bug.

Diagnostic-only, same convention as steps 1-2: no new CLI flag, always computed, does not gate or reject anything yet.

**Test results**: `tests/test_geometry_pipeline.py`: 73/73 pass (2 new). Full `tests/` discovery: 216 tests, same single pre-existing unrelated `cv2` failure, 14 skips unchanged. `py_compile` clean.

---

## 8. Running now: full offline A/B (with vs. without step 4), all available episodes

Two fully-detached background campaigns (`setsid nohup ... < /dev/null &`, confirmed `PPID=1`/no controlling TTY/own session ID — survives closing this session), launched 2026-07-12, comparing the *same* corrected `RouteMemoryAgent` replay methodology from §6 attempt 3, on the same 9 available episodes (`4, 5, 187, 367, 368, 408, 680, 994, 1040`; `ep678` excluded, corrupted capture), with everything held constant except step 4:

- **Track A (with step 4)**: current code. Output `/home/teambruce/replay_results_with_step4_20260712/`, log `/home/teambruce/replay_with_step4_20260712_master.log`.
- **Track B (without step 4, steps 1-2 only)**: a snapshot of `relocalization.py`/`route_memory_agent.py` taken immediately before step 4's edits (this folder's `code/` subdirectory, prior version), imported via a separate `--scripts-dir`. Output `/home/teambruce/replay_results_without_step4_20260712/`, log `/home/teambruce/replay_without_step4_20260712_master.log`.

Worker script and launcher (`replay_worker_step4_ab_20260712.py`, `run_replay_step4_ab_20260712.sh`) are included in this folder's `code/` subdirectory for reproducibility. **Results pending as of this writing.**

**What to check once it finishes**: (1) Track B should reproduce §6 attempt 3's numbers (sanity check that nothing else changed); (2) whether `icp_scan_context_yaw_agreement_deg` (Track A only) discriminates the still-unexplained bucket better than `yaw_top1_next_distinct_score_ratio` did in §6 — the actual bar for whether step 4 is worth keeping; (3) whether combining the two step-1/2 signal with the new Scan Context agreement signal (an ensemble) does better than either alone, per this session's own discussion of that possibility.

## Next steps

1. Once the A/B campaign in §8 finishes: compute the same clean-vs-unexplained percentile analysis as §6 attempt 2, this time for `icp_scan_context_yaw_agreement_deg`, and decide whether it clears the 40-50% bar alone or needs to be combined with the step-1/2 signals.
2. If Scan Context's agreement signal (alone or combined) clears a reasonable bar, design the opt-in downgrade gate (`anchor_heading_reliable=False`, translation-only bearing fallback) and move to a live A/B, following this project's standard opt-in/unit-tested/offline-then-live discipline.
3. If it does not, step 5 (TEASER++ offline verification, short-baseline multi-frame disambiguation, learned registration) is the remaining, lower-priority option per the original plan.
