# 2026-07-16 — Phase-1 signal audit against the network survey's own priority order; a stateless "current"-role confidence-ambiguity gate implemented and unit-tested; live 22-episode validation launched

**Context**: `investigations/2026-07-15-50ep-batch-current-next-simultaneous-failure/low_density_lidar_matching_network_investigation.md` surveyed the literature for a replacement ICP/matching primitive, recommending (Priority 1) reusing this project's already-logged `localizability` (Hessian eigenvalue/eigenvector) signal for X-ICP/DRPM-style directional-degeneracy handling, before anything heavier (correlative Top-K search, GenZ-ICP, etc.). Per the survey's own Phase-1 recommendation ("first validate whether existing diagnostic signals already predict the failure, at zero implementation cost, before building anything new"), this session ground-truth-checked that recommendation directly against this project's own real 50-episode batch data, rather than accepting it on the survey's authority.

## Part 1 — Phase-1 signal audit: the survey's own Priority-1 mechanism does not discriminate on this project's real data; a lower-priority mechanism does

Reconstructed ground-truth bearing error (same methodology as `FINDINGS.md`, but this session fixed a real bug found along the way — see Part 1a) for all `current`-role covisibility records across the 8 known-failure episodes of `shadow_hint_swap_50ep_20260714_accumulated` (`134,367,994,319,708,498,354,214`; n=4636, split into 2613 catastrophic `>45°` vs 1344 clean `≤10°`):

| signal | mechanism family | discrimination found |
|---|---|---|
| `localizability.quality` (degenerate/full) | X-ICP/DRPM (survey Priority 1) | **inverted**: 94.2% of catastrophic readings show `full` (not degenerate) vs 67.7% of clean readings |
| `min_normalized_eigenvalue` | X-ICP/DRPM | **inverted at every threshold tested**: TP−FP gap goes from +0.6pt down to **−50.6pt** as the threshold loosens |
| `yaw_observability` (Schur-complement, this project's own 2026-07-10 addition, more sophisticated than a naive eigenvalue check) | X-ICP-adjacent | **uninformative**: both groups report `full` 100% of the time, the "weak" branch never fires on this data |
| `yc_top1_next_distinct_score_ratio` (= `icp_best_to_second_score_ratio`, same signal already used for `quarantine_next_quality_enabled`) | multi-hypothesis/basin (survey Priority 2, Cartographer-adjacent) | **strong**: TP=97.6%/FP=41.1% (gap 56.4pt) at threshold 0.5; TP=80.1%/FP=34.4% (gap 45.7pt) at the already-validated 0.75 |
| `yc_peak_width_deg` | multi-hypothesis/basin | moderate: best gap ~46pt, degrades faster than the ratio signal as threshold rises |

**Net finding: the signal family the survey ranked lowest-effort-highest-priority (Hessian-eigenvalue directional degeneracy) does not predict this project's actual catastrophic current-role bearing errors — and is backwards at some thresholds — while the signal family it ranked second (yaw multi-hypothesis/basin competition) shows real, substantial separation.** This does not mean X-ICP/DRPM are bad methods in general; it means the *specific, already-computed* single-frame Hessian eigen-decomposition this project logs today does not carry the signal the survey assumed it would for this project's specific failure mode. Any future work adopting X-ICP/DRPM-style directional projection should re-validate against this same ground-truth methodology before assuming it will help, rather than treating "we already have localizability" as sufficient justification.

### Part 1a — a real ground-truth reconstruction bug found and fixed along the way

Initial reconstruction (naive `row_index = 0 if attempt==1 else (attempt-1)*relocalization_interval_updates - 1`, per the row-alignment formula documented from 2026-07-03) produced per-anchor bearing-error numbers that did **not** match `FINDINGS.md`'s own already-published Part 5/6 tables (e.g. computed ep134 anchor7 current-role share/median as 31.2%/149.8° vs `FINDINGS.md`'s published 57.5%/63.6°). Root cause: that formula computes an offset from the start of the **return phase**, not the start of the full trajectory file (which also contains the outbound phase) — the correct row index is `first_return_phase_row_index + formula_offset`. Confirmed by exact-matching each attempt's current-role `(anchor_index, anchor_dx_m, anchor_dy_m)` against the trajectory JSONL's own per-step `route_memory.target_anchor_index`/`anchor_dx_m`/`anchor_dy_m` echo (the shadow's own logged state, not a smoothed/derived field) — after the fix, reconstructed numbers match `FINDINGS.md`'s published per-anchor share/median almost exactly (e.g. ep134 anchor7: 57.4%/63.6° vs published 57.5%/63.6°; ep498 anchor5: 35.9%/68.3° vs published 36.1%/68.3°). All Part 1 numbers above use the corrected alignment. Per this project's established methodology (never trust a derived alignment without cross-checking against an independently-logged field), this is recorded here so the bug isn't reintroduced by a future session reusing the row-index formula verbatim without the return-phase offset.

## Part 2 — existing safety infrastructure is already blind to this signal

Checked whether the existing `confidence` field (which already feeds `relocalization_confidence` → `hint_action_arbiter`'s 2026-07-13 confidence gate, calibrated at 0.90) varies with the ambiguity signal found useful in Part 1. On `ep134`: mean confidence when `icp_best_to_second_score_ratio >= 0.75` (ambiguous) = 0.980; when `< 0.75` (clear) = 0.989 — **essentially identical, confirming the project's previously-documented "confidence saturates near 1.0" finding applies here too.** The arbiter/stop_gate infrastructure built 2026-07-13 for the oracle-to-shadow swap is real and already wired up, but is fed a confidence value that cannot see this failure mode at all.

## Part 3 — offline simulation: would a current-role ambiguity flag actually engage during the known dwells?

For each of the 8 known-failure episodes, identified the dominant "bad" current-role anchor(s) (share ≥10% of the episode's current-role attempts AND median ground-truth bearing error >45°) and checked, walking the actual attempt sequence in order, whether `icp_best_to_second_score_ratio >= 0.75` would have flagged the reading, and how quickly after the dwell began:

| episode | bad anchor(s) | dwell share | flag rate on bad dwell | flag rate on everything else | first flag |
|---|---|---:|---:|---:|---|
| 134 | 7 | 57.4% | 75.4% | 18.8% | immediate |
| 367 | 5,7,8 | 73.2% | 88.9% | 36.9% | immediate |
| 498 | 5 | 35.9% | 90.7% | 9.0% | immediate |
| 708 | 5,7,8 | 52.7% | 76.1% | 23.8% | **delayed — 42 attempts into the dwell** |
| 319 | 4,5 | 63.3% | 71.1% | 92.4% | immediate, but flags almost everything |
| 354 | 10 | 10.3% | 98.1% | 87.5% | immediate, but flags almost everything |
| 214 | 1,3,5 | 72.6% | 79.1% | 86.0% | immediate, but flags almost everything |
| 994 | (none identified) | 0% | — | 24.4% | never — this episode's known failure (FINDINGS.md Part 2: VLM disregards a correctly-hedged "keep going" hint) is not a confidently-wrong-current-reading problem at all |

**Honest read, not oversold**: this would give clean, targeted, near-immediate protection on 3 episodes (134/367/498) where ambiguity is genuinely localized to the bad anchor; partial (delayed) protection on 1 (708); would degrade toward "flag almost the whole episode" on 3 self-similar routes (319/354/214) where ambiguity is route-wide, not anchor-specific (functionally similar to always deferring to the VLM on those routes — not wrong, but not precise either); and would do nothing for 1 (994, a different failure mechanism entirely, out of scope for a confidence-based gate).

## Part 4 — design: abstain, not ban

Per explicit user direction: this must NOT repeat `quarantine_next_quality_enabled`'s failure mode (2026-07-15 finding: permanently banning a candidate after a handful of noisy samples, with no release valve, cascades through an entire self-similar route's candidate chain). The two mechanisms differ in exactly the property that mattered:

| | `quarantine_next_quality_enabled` (2026-07-15) | `current_confidence_ambiguity_gate_enabled` (this session) |
|---|---|---|
| role monitored | "next" only (mirrors existing quarantine modes' exemption) | **"current" only** — the role FINDINGS.md Part 6 established nothing else monitors |
| state carried between attempts | yes — accumulates a history, permanently adds to `_quarantined_anchor_indices` once crossed | **none** — every attempt re-derives the result purely from that single estimate |
| action on a positive flag | ban the anchor forever, skip past it | **cap the reported `relocalization_confidence` for this one attempt**, defer to the existing arbiter/stop_gate gates |
| cost of a false positive | permanent, compounding (proved to cascade to exhausting an entire route's candidate chain) | one attempt's hint is under-trusted; the very next attempt is judged fresh |
| does it fix a stuck/wrong anchor? | attempts to (by routing around it) — this is what failed | **no, explicitly** — it only stops the shadow from actively misleading the VLM while current looks bad; getting current unstuck remains open (see Part 5) |

This is a deliberately weaker intervention than either `quarantine_next_quality_enabled` (ban) or the 2026-07-07 `trust_aware_guard` (reconstruct one side from the other, which requires an independently-trustworthy other side — not available in exactly the current+next-both-bad cases this line of investigation is about).

## Part 5 — what was implemented

All changes additive, off by default, unittested to confirm zero regressions when off.

- **`RouteMemoryAgent.__init__`** (`route_memory_agent.py`): new params `current_confidence_ambiguity_gate_enabled: bool = False`, `current_confidence_ambiguity_gate_threshold: float = 0.75`, `current_confidence_ambiguity_gate_floor: float = 0.5`.
- **`RouteMemoryAgent._current_reported_confidence(estimate)`** (new method): stateless — returns `estimate.confidence` unchanged unless the gate is enabled and `estimate.best_to_second_score_ratio >= threshold`, in which case returns `min(estimate.confidence, floor)`. A missing/`None` ratio is never treated as ambiguous (same convention as `_record_next_anchor_quality`). Does **not** mutate `estimate.confidence` itself — that field is still used unmodified everywhere else (promotion voting, closure-check quality comparisons, quarantine).
- **`RouteMemoryAgent._anchor_progress_from_estimate`**: now calls `_current_reported_confidence` once and uses the result for both the reported `relocalization_confidence` field AND `filter_std_m`'s confidence-dependent inflation (previously both used `estimate.confidence` directly) — an ambiguous reading now reports both lower confidence and a wider uncertainty radius consistently, so both existing downstream consumers (`hint_action_arbiter`'s confidence gate, `stop_gate`'s/`_filter_lost`'s arrival-claim-suppression wording gate) react.
- **New CLI flags** (`round_trip_eval.py`): `--sequential_pair_current_confidence_ambiguity_gate` (off by default), `--sequential_pair_current_confidence_ambiguity_gate_threshold` (default 0.75), `--sequential_pair_current_confidence_ambiguity_gate_floor` (default 0.5, chosen below the arbiter's existing 0.90 threshold so the gate actually engages when it fires). Logged into the measurement JSON's config-echo block.

## Part 6 — validation

10 new unit tests, `tests/test_route_memory_agent.py::SequentialPairCurrentConfidenceAmbiguityGateTest`: default-off preserves the original confidence exactly; an ambiguous reading (ratio ≥ threshold) is capped at the floor; an unambiguous one is unaffected; ratio exactly at threshold is gated (boundary inclusive, matching `_record_next_anchor_quality`'s own `>` vs this gate's `>=` — deliberately chosen so a reading exactly at the already-validated 0.75 cutoff is treated the same way this signal was validated); a missing ratio is never treated as ambiguous; the floor is a `min()`, never raises an already-lower confidence; the gate does not mutate the underlying `estimate.confidence`; the effect is stateless across consecutive attempts (no cooldown, no memory); and an end-to-end `_anchor_progress_from_estimate` call reports both lower confidence and a wider `filter_std_m` when ambiguous, with the default-off path byte-for-byte unchanged. Full suite re-run: **197 tests (187 prior + 10 new), 14 pre-existing skips (unchanged), zero regressions.**

## How to revert

Simply omit `--sequential_pair_current_confidence_ambiguity_gate` from the launch command (default is off). No other code path is touched when it's off.

## Live validation launched

Re-runs the same 22 outbound-success episodes from `shadow_hint_swap_50ep_20260714_accumulated` (the 14 known successes + 8 known return-failures analyzed in `FINDINGS.md`), identical Variant-1 config, with only `--sequential_pair_current_confidence_ambiguity_gate` (threshold 0.75, floor 0.5) added on top — `sequential_pair_quarantine_next_quality` left off per the 2026-07-15 decision not to pursue it further. An isolated, single-variable A/B against the same already-known baseline used for the 2026-07-15 test.

- Run tag: `shadow_current_confidence_gate_22ep_20260716`
- Launcher: `/home/teambruce/run_22ep_current_confidence_gate_20260716.sh` (snapshot in this folder's `code/`)
- Master log: `/home/teambruce/run_22ep_current_confidence_gate_20260716_master.log`
- Results: `NaVILA-Bench/batch_logs/shadow_current_confidence_gate_22ep_20260716/summary.tsv` (once finished)

**Pending / next steps**: once finished, compare per-episode `round_trip_success` against the known 14/8 baseline, same methodology as the 2026-07-15 analysis (condition on this run's own outbound-success set, since VLM outbound-phase stochasticity makes some episodes non-comparable run to run). Per Part 3's own honest read, the realistic expectation is targeted improvement on `134/367/498`-like cases, partial help on `708`-like delayed-ambiguity cases, near-constant deferral (not necessarily harmful, but not precise) on `319/354/214`-like uniformly-self-similar routes, and no effect on `994`-like VLM-behavior failures — this is a mitigation for one specific sub-mechanism (current actively misleading the VLM), not a fix for current getting stuck in the first place. The real fix for that (per this session's Part 1 finding, which reopens rather than closes the matching-primitive question) remains an open research direction — the network survey's Priority-1 mechanism is now evidenced not to help as-is; its Priority-2 mechanism (multi-hypothesis/correlative search) is the better-supported next direction to actually pursue for improving the matching primitive itself, separate from this confidence-gate mitigation.
