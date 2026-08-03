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

Worker script and launcher (`replay_worker_step4_ab_20260712.py`, `run_replay_step4_ab_20260712.sh`) are included in this folder's `code/` subdirectory for reproducibility.

---

## 9. Step 4 result: negative, and in the wrong direction to be usable

The §8 A/B completed (2709 readings each track; Track A/B bearing errors are byte-identical, confirming step 4 is truly behavior-neutral). On Track A's full diagnostic set:

| signal | clean (≤5°) median | unexplained-by-old (>10°) median | direction |
|---|---|---|---|
| `icp_scan_context_yaw_agreement_deg` | 43.7° | 12.8° | **backwards** — bad readings show *more* agreement |
| `scan_context_similarity` | 0.216 | 0.300 | **backwards** — bad readings score *higher* SC confidence |

Persists after excluding near-zero-distance readings (bearing math degenerate when `true_dist_m` is tiny). **Likely explanation**: when the real cause of a bearing error is genuine physical symmetry in the scene (not an ICP-specific quirk), ICP and Scan Context are not actually independent — both are 2D geometric registration methods reading the *same* single point cloud, so a real symmetric structure can draw both toward the *same* wrong solution just as easily as it draws ICP there alone. Two methods "agreeing" is not reliable evidence of correctness when they can be fooled the same way by the same data.

**Decision**: stopped the already-running `step4_scan_context_hard11_20260712_accumulated` live batch mid-episode-2 (cleanly killed the whole process tree — VLM server, Isaac Sim, batch driver — confirmed GPU memory returned to idle) rather than let it finish, since the offline result already answers the question this batch existed to check, and step 4's own negative result doesn't need a live re-confirmation before moving on. `_scan_context_yaw_check` itself is left in the code (harmless, diagnostic-only, real unit tests still pass) but should not be used as a trust signal.

---

## 10. Implemented: short-baseline yaw disambiguation (step 5)

**Not the same mechanism as `multiframe_anchor_window`** (2026-07-08, confirmed regressed results — merges several *outbound* frames captured at the *same* physical location into one denser anchor descriptor; more points from one viewpoint, doesn't break a genuinely symmetric structure). This instead compares two independent *return-phase* observations of the same candidate anchor from two genuinely different robot positions (`sequential_pair_short_baseline_min_travel_m`, default 0.3m apart), exploiting real parallax — the one thing §9 established that a same-scan algorithm swap cannot provide.

**Where**: `route_memory_agent.py`, new `_check_short_baseline_yaw_disambiguation()` and `_yaw_disambiguation_pending` state (bounded — one entry per candidate anchor index, consumed the moment it resolves either way, pruned on promotion exactly like `_promotion_distance_history`/etc., never accumulates across an episode). Wired into `_select_sequential_pair_relocalization`: downgrades `anchor_heading_reliable` to `False` on the reported estimate when two readings confirm real disagreement.

**Geometry**: composes each raw reading's (dx, dy, dθ) onto the robot's own absolute pose at capture time (`current_absolute_pose_from_start()`) to get the anchor's *implied absolute pose*; two readings of the same real anchor should imply the same absolute pose regardless of where the robot stood for each one. Reuses `compose_pose`/`relative_delta` (this file's existing SE(2) utilities), not a new transform convention.

**Two design/implementation mistakes found and fixed before this was trustworthy — recorded in full since they're as informative as the final design:**

1. **First version gated the check behind `match_class in (ambiguous_high_confidence, partial_pose_degenerate)`** — reasoning that a clean-looking reading doesn't need a second opinion. An offline smoke test against real `ep1040` capture data (this project's own flagship confidently-wrong-rotation example) found this was backwards: **86.5% of its worst (>45°) bearing errors carry `match_class=clean_full_pose`**, which is the *entire reason* they were in the "69% unexplained" bucket in the first place — gating the one mechanism designed to catch exactly this behind the diagnostic that already fails to catch it defeats the purpose. Fixed by removing the match_class gate entirely — the check now runs on every next-candidate reading unconditionally (cheap: O(1) bookkeeping per attempt).

2. **The offline replay harness used to validate this (§6-8's methodology) never called `update_return_motion()`** — it called `update_relocalization()` directly every subsampled step, which is sufficient for every other diagnostic in this investigation (steps 1/2/4 only need the current attempt's point clouds) but **not** for this one, which depends on `current_absolute_pose_from_start()` actually advancing between attempts. Since the harness never advanced `_return_pose_from_return_start`, the agent's internal pose was frozen at its `finalize_outbound()` value for the entire episode, so every "how far have I traveled since the pending reading" computation returned ~0m regardless of how far the real robot had moved — the mechanism could never accumulate enough baseline to resolve, in either direction. This was caught by pulling the raw per-call log (pending state, computed travel, disagreement, not just the final True/False) after being asked directly whether the checks were actually agreeing or simply never running — the log showed `result=None` on every single call across a 130-step window where the real robot had moved >1m, which is not consistent with "genuinely still ambiguous" and pointed straight at the pose-tracking gap. **Confirmed this bug is confined to the offline test harness and does not affect the real live path**: `round_trip_eval.py` already calls `route_agent.update_return_motion(action_delta, local_descriptor=..., relocalization=...)` every return-phase step (pre-existing code, unchanged), so `current_absolute_pose_from_start()` correctly tracks real motion live. Given the harness bug meant the offline validation couldn't actually be trusted either way, this session moved to live validation directly instead of further offline debugging (see §11).

**Wired into `round_trip_eval.py`**: `--sequential_pair_short_baseline_disambiguation` (opt-in, default off), `--sequential_pair_short_baseline_min_travel_m` (default 0.3), `--sequential_pair_short_baseline_max_rotation_disagreement_deg` (default 20.0), all logged into the measurement JSON config block.

**Test results**: 7 new unit tests in `tests/test_route_memory_agent.py::SequentialPairShortBaselineDisambiguationTest`, including a hand-computable two-viewpoint consistency case, a two-viewpoint disagreement case, a case confirming the mechanism fires even when both raw readings self-report `match_class=clean_full_pose` (§10.1's fix, directly tested), a not-enough-travel-yet case, and a promotion-pruning case. Full suite: 223 tests, only the pre-existing unrelated `cv2` failure, 14 skips unchanged. `py_compile` clean on all three modified production files (`relocalization.py`, `route_memory_agent.py`, `round_trip_eval.py`).

---

## 11. Running now: full live Isaac Sim hard-11 batch for step 5

Given §10's harness bug made offline validation untrustworthy either way, and after confirming the actual production code path is unaffected by that bug (§10, point 2) and the full test suite is clean, this session went directly to a live validation rather than continuing to debug the offline harness.

`short_baseline_hard11_20260712_accumulated` — identical config to `promotion_use_raw_estimates_hard11_20260710_accumulated` / `step4_scan_context_hard11_20260712_accumulated` (the current best-validated batches), plus only `--sequential_pair_short_baseline_disambiguation` (+ its two threshold flags at their defaults). Directly comparable against those existing batches: this mechanism only ever downgrades `anchor_heading_reliable` on the reported hint, never changes `dx`/`dy`/promotion timing, so bearing/anchor-selection numbers should be unaffected except where a downgrade actually fires.

Launched fully detached (`setsid nohup ... < /dev/null &`, confirmed `PPID=1`/no controlling TTY/own session ID). Launcher `/home/teambruce/run_short_baseline_hard11_20260712.sh` (copy in this folder's `code/`), master log `/home/teambruce/short_baseline_hard11_20260712_master.log`. **Results pending as of this writing** — episode 4 was starting at the time of this entry.

## Next steps

1. Once §11's live batch finishes: check how often `anchor_heading_reliable` actually gets set to `False`, and for those cases, whether the underlying bearing error was genuinely large (i.e. the downgrade was correct) versus a false positive on an otherwise-fine reading.
2. If the downgrade rate and precision look reasonable, this is usable as an opt-in mitigation (translation-only bearing fallback when heading is flagged unreliable) — but note it only *suppresses* a bad reading, it does not correct it, unlike a true disambiguation that recovers the right answer; whether that's sufficient value on its own is a judgment call for a follow-up session.
3. If the offline replay harness is revisited for future diagnostics, fix it once properly (compute real per-step pose deltas from the captured ground truth and feed them through `update_return_motion`) rather than continuing to call `update_relocalization` directly — most future mechanisms in this investigation line are likely to depend on pose tracking the same way step 5 does.
