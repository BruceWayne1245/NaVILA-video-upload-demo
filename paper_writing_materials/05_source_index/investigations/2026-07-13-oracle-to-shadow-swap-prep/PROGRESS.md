# 2026-07-13 — Preparing the first Oracle→Shadow hint-source swap: plan + steps 1-2 implemented

**Context**: `investigations/2026-07-13-icp-bearing-error-cross-batch-deep-dive/` closed out the bearing-error investigation line with Variant 1 ("no fusion at all" — `--sequential_pair_disable_temporal_smoothing`, `--sequential_pair_closure_check` omitted) adopted as the new main `sequential_pair` configuration: bearing error median 1.79°/mean 8.24° on `ep368`, a dramatic improvement over every prior configuration. This makes the shadow relocalizer accurate enough to seriously consider for the first time actually replacing `--route_hint_source=oracle` with the shadow's own hint — the original long-term goal this entire route-memory system was built for. This document is the plan for that swap, plus the first two (of five) steps, already implemented.

## Investigation before planning: is new plumbing needed, or does it already exist?

A code investigation (not guessed) found the swap needs far less new work than expected:

1. **`--route_hint_source=integrated` already exists and already drives the real non-oracle shadow pipeline** (`route_agent.progress()`, i.e. whatever `--route_relocalization_backend` is configured, including `sequential_pair`). Today this only ever runs in parallel for diagnostics (`route_shadow_progress`, logged as `shadow_progress`/`shadow_alignment`) while `--route_hint_source=oracle` drives real navigation — but the actual computation the swap needs is already exercised on every batch. **The swap is mostly a CLI flag change** (`--route_hint_source=integrated`), not new plumbing.
2. **`stop_gate.py` is already confidence-aware and non-oracle-ready.** `_extract_d_and_conf` only forces `conf=1.0` when `progress.source` is oracle-flavored; otherwise it already reads `relocalization_confidence`/`filter_std_m` and low confidence already defers to the VLM. This mechanism needed no changes.
3. **`hint_action_arbiter.py` had zero confidence gating** — it unconditionally overrode the VLM's action whenever the hint conflicted and the path looked clear, with no check on whether the hint itself was trustworthy. Safe only because the only real hint source was ground-truth oracle. **This was the one real gap**, and is what "补齐主动纠正机制" (filling in the missing active-correction mechanism) refers to — not a missing mechanism, but an existing one with an unsafe (implicit-trust) assumption that needs to change now that the hint source may be noisier.
4. A secondary gap: `_anchor_progress_from_estimate()` (the path used for anchor/`sequential_pair`-sourced hints) never populated `filter_std_m`, so the hint-text uncertainty-suppression logic (`_filter_lost()`) was silently dead code on this path (always saw `filter_std_m=None` → always returned `False`).

## The agreed 5-step plan

1. **Add confidence gating to `hint_action_arbiter`** (this document, done).
2. **Populate `filter_std_m` for anchor/`sequential_pair`-sourced progress** so the existing uncertainty-wording gate actually engages (this document, done).
3. Offline-replay-calibrate the new confidence threshold against already-existing oracle-driven batches (which already log `shadow_progress` in parallel) — no new live run needed for this step.
4. A single, small live test (`ep368` — user's choice, already validated well under Variant 1 and contains the hardest known anchor, anchor12) with `--route_hint_source=integrated` actually driving navigation.
5. If step 4 looks reasonable, decide on scope for a wider batch.

This document covers steps 1-2. Steps 3-5 are still pending.

---

## Step 1: confidence gate for `hint_action_arbiter`

**New field**: `HintActionArbiterConfig.min_relocalization_confidence: float = 0.0` — default preserves the arbiter's exact original behavior (every confidence value passes; needed since the only real-navigation hint source to date, oracle, always reports `relocalization_confidence=1.0` anyway, so this was never a live behavior change until now).

**New gate** in `HintActionArbiter.check()`: right after the existing `missing_hint_direction`/`target_too_close` checks, reads `progress.relocalization_confidence` (already a generic, already-populated field — confirmed set to `1.0` for oracle progress and `estimate.confidence` for anchor/`sequential_pair` progress) and refuses to override (`reason="low_relocalization_confidence"`) when it's present and below the configured threshold. A **missing** confidence value (e.g. some other/legacy progress source that never sets the field) is treated as "no reason to distrust it," mirroring `RouteMemoryAgent._candidate_is_trustworthy`'s existing convention for `match_class` — consistent with this project's established pattern for handling optional trust signals.

New CLI flag: `--hint_arbiter_min_relocalization_confidence` (default `0.0`, threshold to be calibrated in step 3, not guessed).

**Validated** (no existing unit-test file covers `hint_action_arbiter.py`, so a standalone smoke test was run, not just `py_compile`): confirmed (a) default config (`min_relocalization_confidence=0.0`) still overrides on conflict exactly as before; (b) with the gate set to `0.5`, a `confidence=0.2` reading is correctly blocked (`reason="low_relocalization_confidence"`); (c) a `confidence=0.9` reading still overrides normally; (d) a progress object with the field entirely absent (legacy path) is not blocked. Full existing suite (`tests/test_geometry_pipeline.py` + `tests/test_route_memory_agent.py`, 180 tests) re-run clean, zero regressions.

## Step 2: `filter_std_m` for anchor/`sequential_pair` progress

`_anchor_progress_from_estimate()` now sets `filter_std_m = _closure_disagreement_sigma_m(estimate) / max(0.05, estimate.confidence)` — reuses the existing distance-dependent ICP noise-scale primitive already used elsewhere in this file (`_closure_disagreement_sigma_m`, 0.45-2.0m range) and inflates it as confidence drops, so a high-confidence reading stays near the plain ICP noise floor (well under `_filter_lost`'s `>=2.5m` threshold — "not lost") while a low-confidence one crosses it ("lost", suppress arrival-claim wording). **This is not a rigorously calibrated filter** — there is no real particle filter on this code path to measure an actual standard deviation from — it is a defensible proxy just so the existing wording gate has something real to act on, rather than being permanently dead code on this path. Worth revisiting with real calibration data if the wording behavior it produces looks wrong in practice.

**Validated**: standalone smoke test constructing high-confidence (0.95) and low-confidence (0.10) `AnchorRelocalization` estimates confirmed `filter_std_m` of 1.05m (not lost) vs 10.0m (lost) respectively — the gate fires in the expected direction. Full existing suite re-run clean.

## Next steps

Step 3 (offline calibration): replay existing oracle-driven batches' logged `shadow_progress`/`shadow_alignment` fields through the new confidence gate at a range of thresholds, and check how often/how well a shadow-driven arbiter would have decided to override vs defer, compared to what oracle-driven navigation actually needed — before choosing a real threshold for step 4's live test.

## Reproducibility

Modified files (snapshots in this folder's `code/`): `hint_action_arbiter.py`, `route_memory_agent.py`, `round_trip_eval.py`.
