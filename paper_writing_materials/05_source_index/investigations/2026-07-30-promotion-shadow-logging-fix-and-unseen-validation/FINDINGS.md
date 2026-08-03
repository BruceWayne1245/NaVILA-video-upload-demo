# 2026-07-30 — Promotion-shadow logging bug found and fixed; corrected precision/recall shows no retrain needed; genuinely-unseen validation batch launched (two candidate-selection bugs found and fixed along the way)

Author: Claude (Route 1). Continues directly from `2026-07-28-promotion-quarantine-controller-model` and the finished `promotion_shadow_30ep_20260728` shadow run referenced in that folder's `INTEGRATION_PLAN.md` next steps (a live precision/recall report on the learned promotion/quarantine/wait controller).

## 0. Context

`promotion_shadow_30ep_20260728` (30 episodes, launched 2026-07-28, finished 2026-07-29T18:20 BST) was meant to produce exactly the precision/recall report `INTEGRATION_PLAN.md` asked for: compare `promotion_controller_v2_2026-07-28_isaacenv.pkl`'s counterfactual decisions (`sequential_pair_promotion_model_shadow`, zero control authority) against what the real heuristic controller actually did. Round-trip outcome was 15/30 (baseline heuristic behavior, unaffected by the shadow model as intended).

## 1. Bug found: `existing_heuristic_decision` always logs "wait"

Every one of 9,347 `promotion_shadow_score` events across all 29 completed episodes in `promotion_shadow_30ep_20260728` has `existing_heuristic_decision.action == "wait"` — zero `promote`, zero `quarantine`, ever. This is wrong: independently reconstructing real anchor promotions from each episode's `relocalization_events` (`target_anchor_index` transitions) confirms real promotions did happen (e.g. 4 in ep88, 7 in ep671, 3 in ep367, 2 in ep962) — the field was simply never seeing them.

**Root cause**: `round_trip_eval.py`'s `_sequential_pair_relocalizer_with_v11_shadow` closure snapshotted `route_agent._target_anchor_index` / `_quarantined_anchor_indices` both immediately before and immediately after its own internal `sequential_pair_anchor_relocalization()` call, inside the same closure. But this closure runs *from inside* `RouteMemoryAgent.update_relocalization()` (invoked at its `self.relocalizer(...)` call site); the code that actually applies this attempt's real promotion/quarantine decision, using the estimates this closure returns, runs in `update_relocalization()`'s *continuation*, strictly after this closure returns. So both snapshots were taken before the real decision landed — the comparison could never see a change, and always fell through to `"wait"`. (An earlier code comment on this block asserted the opposite ordering; that assertion was wrong.)

## 2. Fix

Deferred the "after" snapshot and the whole `existing_heuristic_decision` computation from inside the closure to right after `route_agent.update_return_motion()` (which calls `update_relocalization()`) actually returns in the main loop — mirroring the already-correct pattern the sibling `v11_shadow_session.record_controller_snapshot()` call uses a few lines below in the same file. The closure now just stashes `{step, attempt, records, idx_before, quarantined_before}` into a new `promotion_shadow_pending` nonlocal; the real comparison and the single `promotion_shadow_session.score_attempt(...)` call happen once, after the real state change has landed. Full diff: `code/promotion_shadow_existing_decision_fix.patch`.

**Validated live**: a 1-episode smoke test (`promotion_shadow_bugfix_smoke_1ep_20260730`, ep88) now logs 5 real promote transitions (6→5→4→3→2→1, monotonic as expected) instead of 100% "wait". The model's own decision matched 3/5 (attempts 44, 50, 60 — high confidence, 0.92-0.99) and missed 2/5 (attempts 129, 147 — high-confidence "wait", 0.71 and 0.998) — small-sample, consistent with the corrected recall figure below, not evidence of a new problem.

Not yet committed to git (the dev sandbox at `/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench` already carries a large pre-existing uncommitted diff from prior sessions) and not yet reported to Route2/Codex.

## 3. First reconstruction attempt was itself measured wrong (correction, then a second correction)

Before finding the fix above, `existing_heuristic_decision` couldn't be trusted, so real `target_anchor_index` transitions were reconstructed independently from `relocalization_events` as a substitute ground truth, restricted to the 20/28 episodes where `relocalization_events` count matched the shadow log's own attempt count closely (<3% mismatch — the other 8 have the known "an attempt can be silently skipped" trap). Against this (98 real transition events, ±1 attempt tolerance), the model's `promote` calls scored **precision 0.090 / recall 0.365** (loose variant, counting `quarantine` calls too: precision 0.103 / recall 0.509) — a discouraging result.

**This was the wrong ground truth to use.** The model was trained (`extract_dwell_dataset.py`) to answer *"is the ground-truth distance to this anchor ≤ 0.75 m right now"* — a state that can hold true across many consecutive attempts within a dwell — not *"is this the exact attempt `bounded_evidence`'s vote-counter finally commits"* (a single instant, later in the window, since promotion needs 3-of-5 confirming votes). Redone properly: re-extracted the 30ep batch with the *training-matched* label definition (scoped `extract_dwell_dataset.py` to just this batch's 26 successfully-parsed episodes — 2 hit the known intermittent measurement-JSON corruption bug, 1 was empty), then scored the real deployed bundle (loaded in the `vlnce-isaac` conda env — the bundle's sklearn version, 1.7.2, does not unpickle in `navila-vlm`'s 1.2.2) against these correct labels:

| class | precision | recall | F1 | AUC |
|---|---|---|---|---|
| wait | 0.988 | 0.938 | 0.963 | 0.989 |
| promote | 0.902 | 0.975 | 0.937 | 0.997 |
| quarantine | 0.327 | 0.755 | 0.457 | 0.961 |

These match or exceed the original offline OOF AUCs (0.930/0.952/0.950) — **no live/offline degradation, no retrain justified.** Quarantine's low precision is expected at its 1.4-1.9% base rate (matches `2026-07-28-promotion-quarantine-controller-model/FINDINGS.md`'s own calibration table). Caveat: the 30 episodes were selected for historically-perfect outbound success across the same 16 batches the training set came from, so while this specific run wasn't in training, the same physical scenes likely were — this is a repeated-scenario check, not a strict OOD test (motivating §4-5 below).

## 4. Phase 3 (live enforcement) does not exist yet

Checked before considering "going active": `PromotionModelBundle.load()` only accepts `mode="shadow"`, raises on anything else by design; `INTEGRATION_PLAN.md`'s own Phase 3 section is unimplemented. Recommendation (not yet acted on): validate on genuinely unseen episodes first (the explicit, not-yet-done next step in that same plan), then implement Phase 3 as a single-variable live A/B, keeping `reliability_quarantine_max_chain`/`stop_gate`/`hint_action_arbiter` untouched.

## 5. Building a genuinely-unseen validation cohort (two candidate-selection bugs found and fixed)

Of 209 physical episode ids ever attempted in this project's history (146 `batch_logs/*/summary.tsv` files), only 101 fed the promotion controller's training set, and only 2 (670, 696) were both untrained *and* had a prior 100%-outbound-success record — the previously-"safe" 50-episode pool (`policy-v2-active50` cohort) turned out to be fully absorbed into training already.

**Bug 1**: the first 30-episode candidate list (69, 138, 149, 152, 202, 207, 255, 303, 308, 332, 378, 379, 393, 405, 522, 524, 562, 563, 607, 699, 747, 750, 775, 781, 824, 850, 930, 964, 1056, 1073 — same 9 scenes as training, never run before, no other check) all failed within ~12-40s of Isaac Sim startup, `exit_code=0`, no traceback, no `eval_results/` directory ever created. Root cause: `--instruction_rewriter_provider=cache_only` needs either a cache hit or a dataset-derived "reverse path neighbor" (`instruction_rewriter._find_reverse_path_neighbor()`) to build the return instruction; when neither exists it raises `InstructionRewriteError` → `RuntimeError` right after `env.reset()` (`round_trip_eval.py`'s `build_episode_instructions()`, called ~line 2840) — and this exception is silently swallowed by Isaac Kit's own app-shutdown sequence before Python prints a traceback (a known project-wide "silent exception" pathology; see the 2026-07-19 comment on the `try: main() finally: simulation_app.close()` wrapper at the file's end). None of this project's prior batch scripts hit this because their episode pools were always pre-filtered (implicitly or explicitly, e.g. via the `neighbor_idx` column already present in Route2's own `episodes.tsv`) to have a valid neighbor.

**Fix**: ran `_find_reverse_path_neighbor()` directly against the untried-same-scene pool (850 episodes); 40/72 checked had a valid match (~55% hit rate). Took the first 30 with a match: 0, 1, 2, 9, 10, 11, 15, 16, 17, 21, 22, 23, 27, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 46, 47, 48, 50 (concentrated in 3 scenes — `zsNo4HB9uLZ`/`QUCTc6BB5sX`/`2azQ1b91cZZ` — less diverse than originally intended, but validity mattered more given time pressure). Verified with a single ep0 smoke check before committing to the full batch: confirmed real VLM-driven outbound steps now execute.

**Also discovered while launching**: `run_vision_disagreement_ab_50ep_driver_20260726.sh` (this project's standard batch driver) hardcodes its 50-episode manifest as literal `run_episode <args>` calls in the script body; `ONLY_EPISODES` only *filters down* from that fixed list, it cannot inject new episode ids. The first launch attempt with this driver silently ran zero episodes (all 30 new ids got skipped) before this was noticed. Worked around by copying the driver with the hardcoded list replaced (`run_promotion_shadow_unseen30v2_driver_20260730.sh`) rather than patching the shared driver.

## 6. Currently running (outcome not yet known as of this writing)

`promotion_shadow_unseen30v2_20260730` — launched via `systemd-run --user --unit=navila-promotion-shadow-unseen30v2-20260730 --collect`, cgroup verified at `/user.slice/user-1006.slice/user@1006.service/app.slice/...` (survives session/SSH disconnect, confirmed `loginctl` `Linger=yes`). Same canonical downgrade-arm config as `promotion_shadow_30ep_20260728`, only the episode cohort differs, so any behavior difference is attributable to the cohort, not a config change.

**Also fixed while investigating this session**: the "current 50ep job" this was originally meant to queue behind (`navila-unified-shadow50-20260730`, self-labeled "Route-2 unified shadow50" in its own README, combining frozen Anchor Transition V1 + Hint v3 + Terminal/A0 policies) had already failed twice (`FileNotFoundError` on `capture_completion.json` for ep670, both the original launch and its retry1) and was not running by the time this was checked — queuing was abandoned in favor of launching immediately, per user decision.

## 7. Next steps

1. Once `promotion_shadow_unseen30v2_20260730` finishes: re-run the corrected §3 methodology on it directly, and this time also read `existing_heuristic_decision` straight from the fixed logging (no reconstruction needed) to get the original NEXT_STEPS.md comparison cleanly.
2. If that holds up, proceed to the genuinely-novel-episode validation Phase 3 (`INTEGRATION_PLAN.md`) was already waiting on before considering live enforcement.
3. Report the `existing_heuristic_decision` logging bug and its fix upstream (not yet done as of this writing) so any parallel/Route2 use of the same shadow logging isn't quietly relying on it.
4. Consider building a proper reverse-path-neighbor-aware episode sampler (rather than ad hoc `_find_reverse_path_neighbor` probing) if genuinely-unseen validation becomes a recurring need — 55% hit rate on a random untried sample means roughly half of any naive candidate list needs to be discarded first.

## 8. Artifacts

- `code/promotion_shadow_existing_decision_fix.patch` — the `round_trip_eval.py` diff described in §2 (documentation-quality; the file has no clean committed baseline to apply against mechanically).
