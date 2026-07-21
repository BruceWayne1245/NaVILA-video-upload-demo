# 2026-07-21 — Modification plan: use the reliability signals directly (no ML required)

Goal: give the gating an **absolute, `current`-independent per-reading reliability score** and wire it into the three places the current deadlock lives, using only the existing diagnostic fields (per `FINDINGS.md`, a hand combination reaches AUC ~0.80 — the trained model adds only +0.04, so ML is deferred).

All line numbers refer to `NaVILA-Bench/scripts/route_memory_agent.py` as of 2026-07-19 (snapshot in `../2026-07-19-*/code/` and the live file).

---

## 0. The reliability score

New helper `_reading_reliability(estimate) -> float` in `route_memory_agent.py`. Returns a value where **high = trustworthy**. Directions are fixed by the single-signal analysis:

```
reliability =  + w_inlier   · z(inlier_count)                 # high  = good
               - w_ratio    · z(best_to_second_score_ratio)   # high  = ambiguous = bad
               - w_neartie  · near_tie_basin_count             # >0    = bad
               + w_conf     · z(confidence)                    # high  = good (weak)
               + w_loc      · z(loc_min_eig)          [Phase 2]# high  = good
               - w_resid    · z(mean_residual_m)      [Phase 2]# high  = bad
```

- **Phase 1 uses only fields already on the `AnchorRelocalization` dataclass**: `inlier_count`, `best_to_second_score_ratio`, `near_tie_basin_count`, `confidence` (and `degeneracy_ratio`, low weight). The two strongest signals (`inlier_count` 0.787, `best_to_second_score_ratio` 0.780) are here — **zero plumbing**.
- **Phase 2** threads `localizability` min-eigenvalue and `mean_residual_m` from the covisibility computation in `relocalization.py` onto the dataclass for the extra ~0.02–0.04.
- The z-scores use running mean/std per episode (or fixed constants fit offline from `icp_dataset.csv`). Start with equal weights = the validated 0.799 hand-combo; optionally load the logistic-regression coefficients (0.801) — identical wiring, just different constants. Swapping in the trained GBDT later changes only this one function.

Expose two derived predicates with tunable thresholds: `is_unreliable(estimate)` (strict, high-precision — for blacklisting/eviction) and a continuous `reliability` (for confidence capping).

---

## 1. Injection point A — fix the escape hatch (quarantine Door B)

**Problem** (confirmed): `quarantine` fired **0/13** on stuck episodes because it keys on position disagreement vs `current`, blind to bearing and sigma-throttled to a ~2–4 m trip point.

**Change**: add an **absolute** quarantine path — quarantine a `next` candidate when its *own* `reliability` is persistently low, independent of `current`. This is essentially re-enabling `_record_next_anchor_quality` (line 1295, currently OFF) but:
- use the combined `reliability` score, not `best_to_second_score_ratio` alone;
- **add the stall-relief valve it lacked** (its absence caused the 2026-07-15 cascade regression that got it excluded): if quarantining a `next` does not let `current` advance within `reliability_quarantine_stall_attempts` (e.g. 200, mirroring the alias stall-relief at line 1454), release the most-recently-quarantined anchor. This bounds the "quarantine the whole chain" failure.

New flag `--sequential_pair_reliability_quarantine` (off by default). Feeds the same `_quarantined_anchor_indices` set → `_next_candidate_index` (line 1848) already skips them, no change there.

Effect: a bearing-degenerate `next` finally gets skipped, so `current` can promote to `current−2` and escape the degenerate region.

---

## 2. Injection point B — evict a bad `current` (the missing capability)

**Problem**: nothing can evict a `current` that is itself degenerate; it only leaves via a promotion the degeneracy prevents. And `closure_precheck`'s reject (line 1677-1689) forces `candidate_promote=False` **even when the reject is a comparison against an untrustworthy `current`** — a meaningless veto.

**Change (two parts):**

- **(i) Gate the closure-reject veto on `current` being reliable.** At line 1677-1689, only apply `candidate_promote = False` from `closure_reject_reason` when `_reading_reliability(current_est)` is above threshold. If `current` is itself unreliable, its disagreement with `next` is not evidence against `next` — let promotion proceed on `next`'s own merits so we can get *off* the bad `current`.
- **(ii) Explicit current demotion.** If `_reading_reliability(current_est)` is below the strict threshold for `current_evict_stall_attempts` consecutive attempts, force-advance: promote `next` (or re-seed `_target_anchor_index` to the most-reliable candidate among `{current, next}`), bounded by the same stall-relief convention. Prune histories exactly as the existing promotion block does (line 1710-1735).

New flag `--sequential_pair_evict_unreliable_current` (off by default).

Effect: directly addresses the "confidently-wrong `current` poisons every relative check" root cause — the one thing no current mechanism can do.

---

## 3. Injection point C — downstream distrust (highest-ROI, recovers the d-class)

**Problem**: 8/19 return failures were robots that reached home (≤ 3 m) but never registered a stop — because `stop_gate` vetoed the VLM's correct stop ( up to 258 times in `ep680`) on the strength of a **poisoned `gate_authority_d`** coming from the pinned, degenerate `current` reading.

**Change**: make the reported confidence — and therefore `hint_action_arbiter` and `stop_gate` — distrust a low-reliability reading.

- Extend `_current_reported_confidence` (line 1323, which already caps confidence for `current_confidence_ambiguity_gate`) to also cap the reported confidence when `_reading_reliability(current_est)` is low — not just when `best_to_second_score_ratio` is high. This propagates to `hint_arbiter_min_relocalization_confidence` (0.90) and `stop_gate_min_confidence` automatically.
- **In `stop_gate.py`: when the distance authority comes from a low-reliability reading, do not `veto` a VLM stop — `defer` to the VLM.** This is the most direct d-class fix: a robot that is confidently at home (VLM repeatedly issuing stop) should not be blocked by a distance authority the system itself can't trust.

New flag `--sequential_pair_reliability_confidence_gate` (or fold into the existing `current_confidence_ambiguity_gate` by swapping the signal). Off by default.

Effect: recovers most of the 8 "reached home but failed" episodes → return ~27 % toward ~50 %.

---

## Phasing & validation

- **Phase 0 (quick win, do first):** injection C only, dataclass fields only. Smallest change, targets the confirmed d-class (~8 episodes). No new score plumbing beyond the helper.
- **Phase 1:** injections A + B, dataclass fields only (`inlier_count + best_to_second_score_ratio + near_tie + confidence`, the hand-combo).
- **Phase 2:** thread `loc_min_eig` + `mean_residual_m` onto `AnchorRelocalization` in `relocalization.py` (+0.02–0.04); optionally replace the hand-combo constants in `_reading_reliability` with the logistic/GBDT coefficients from `icp_dataset.csv`.

**Validate offline before any live run.** Reuse the saved `covisibility_records` (no Isaac/VLM): replay the 13 stuck + 8 stop-decision episodes with the reliability score computed per attempt, and check (a) does `current` now skip past the degenerate region (injection A/B), and (b) how many d-class episodes would have registered a stop (injection C). Only promote to a live hard-11 / 50 ep A/B if the offline replay shows a net recovery with no regression on the currently-succeeding episodes.

**Every flag defaults off** — no validated batch's behavior changes until each is turned on deliberately, per project convention.

---

## Files touched

| File | Change |
|---|---|
| `route_memory_agent.py` | `_reading_reliability` (new); `_record_next_anchor_reliability` (new / re-enabled `_record_next_anchor_quality` + stall-relief); closure-reject veto gate + current eviction in `_select_sequential_pair_relocalization` (line ~1677, ~1710); extend `_current_reported_confidence` (line 1323); 3 new flags |
| `stop_gate.py` | defer-not-veto when authority reading is low-reliability |
| `relocalization.py` | Phase 2: thread `localizability` min-eigenvalue + `mean_residual_m` onto `AnchorRelocalization` |
| `tests/…` | unit tests per new gate + stall-relief; offline counterfactual replay harness |
