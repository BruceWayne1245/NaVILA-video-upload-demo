# 2026-07-21 — Part 2: capture analysis, threshold calibration, and Injection A/B/C completion

Continues [`FINDINGS.md`](FINDINGS.md). Part 1 diagnosed batch2's return-failure as a
stop/gating problem caused by a permanent tracker "pin" (H2: intrinsically degenerate
anchors), established that every next-side gate is measured *relative to `current`* so a
bad `current` poisons all of them, built the Injection-A core + the capture subsystem, and
launched the 16-episode capture re-run. Part 2 is what the completed capture enabled: the
proper below-pin registrability analysis (§1), the `reliability_quarantine_threshold`
calibration (§2), and the completion + validation of Injection A/B/C (§3).

---

## 0. TL;DR

1. **The capture finished cleanly: 15/16 episodes captured** (~24 GB of raw ICP clouds on
   SSD4T), only `ep669` lost — to a VLM-server-startup timeout, unrelated to capture.
2. **Below-pin registrability, redone properly with real ICP re-matching, OVERTURNS the
   earlier live-only "1/13 → home stretch degenerate → need vision".** Among below-pin
   anchors the robot actually approached, **62 % register cleanly**; the "vision wall" at
   point-blank range is the minority (§1). The earlier pessimism was a confound: the pin
   meant each below-pin anchor had only one incidental live reading.
3. **The dominant reason below-pin anchors look bad in aggregate is that the robot never
   approached them (36 % of them)** — a downstream consequence of the pin causing drift,
   which a fix-OFF capture *cannot counterfactually undo*. So the offline data supports
   finishing the fix but cannot, by construction, prove its full return-rate gain.
4. **`reliability_quarantine_threshold` calibrated 5.05 → 2.5** against 90 k ground-truth
   readings (§2). The old 5.05 fired essentially never (anchor-level recall 0.9 %). **2.5
   catches the U-detectable degenerate `next` anchors at ~4 % false-quarantine rate.**
5. **Hard ceiling confirmed and quantified: ~half the pin-blocking `next` anchors are
   "confidently wrong"** (U looks clean despite 74–98 % bad bearing) — uncatchable at any
   safe threshold. This is the vision residual, matching the 0.84 scalar-feature ceiling.
6. **Injection A/B/C finished, wired to CLI, and unit-tested** (§3): 22 new tests pass,
   286 existing tests pass against the candidate code with **zero regressions**. All three
   flags default-OFF. Not yet merged to live — that is the one reviewed integration before
   the clean fix-OFF vs fix-ON 100 ep A/B.

---

## 1. Below-pin anchor registrability (the go/no-go for un-sticking the pin)

**Method** (`code/below_pin_registrability.py`, `code/reclassify_registrability.py`;
full output `data/06_below_pin_registrability.txt`). For each captured pin episode, for
each anchor below the pin, find the return steps where the robot physically passes closest
to that anchor's true world position, and **force-match the anchor's own captured point
cloud against those steps' clouds using the live ICP** (`relocalization.
sequential_pair_anchor_relocalization`, same voxel/objective as live). Score the reported
bearing/distance against ground truth (anchor `world_pose` from the capture; robot pose
from the step's own `robot_world_pose`). This tests the exact question the live-only data
could not: **if the pin were un-stuck, could `current` walk home?**

**The single BAD/OK flag conflated three physically different situations; split them
(approached ≤ 2.0 m; accurate = bearing err < 30° and dist err < 0.5 m):**

- **REG** — robot approached AND the reading is accurate.
- **DEGEN** — robot approached but the reading is wrong → genuine ICP degeneracy ("vision
  wall": no gating fixes a wrong reading of a cloud the robot is standing next to).
- **FAR** — robot never got within 2 m → not a registrability question; the robot had
  already drifted past/away.

**Pooled (12 captured pin episodes):** of **78** below-pin anchors, **28 (36 %) were never
approached (FAR)**. Of the **50 the robot did approach, 31 (62 %) are REG, 19 (38 %)
DEGEN.**

**Per-episode pattern (5 groups):**

| Group | Episodes | n | Meaning |
|---|---|---|---|
| ① Route-1 fixable (isolated DEGEN blocks a clean home stretch) | 680, 813 | 2 | one bad anchor jams an otherwise-registrable route → exactly the reliability-quarantine (Injection A) target |
| ② Final-approach hard | 5, 889 | 2 | clean down to ~a3, but the last ~2 m to home is DEGEN (ep5) or never reached (ep889) |
| ③ Off-route | 319, 367, 653, 994, 1038 | 5 | robot never approached the home stretch (drift; navigation / pin-consequence, NOT a registrability property) |
| ④ Vision wall | 20 | 1 | genuinely DEGEN at point-blank range (incl. a7 at 1 cm with 119° bearing error, `clean_full_pose`, conf 1.0) |
| ⑤ Mixed | 498, 500 | 2 | scattered clean/degenerate, no clean chain |

**Interpretation.**
- The home-stretch **clouds are mostly not a vision wall** — where reachable they register
  cleanly (62 %). The earlier "1/13 → need vision" was a live-only confound.
- The bulk of below-pin "badness" is **never-approached** anchors (36 %), which is a
  *consequence* of the pin+drift and **cannot be counterfactually undone from a fix-OFF
  capture**. Whether un-sticking the pin keeps the robot on-route (so it does approach
  them) is exactly what only the fix-ON live A/B can settle — this quantifies Part 1 §1.7's
  caveat rather than resolving it.
- **The genuine vision wall is narrow** (ep20 + ep5's final approach + scattered
  point-blank confidently-wrong reads), which *narrows* the "invest in vision now" case and
  *strengthens* the Injection-A/B case (un-stick the pin early, before drift).

---

## 2. Calibrating `reliability_quarantine_threshold` (step 2b)

**Method** (`code/calibrate_reliability_threshold.py`; full output
`data/07_reliability_threshold_calibration.txt`). Replay Injection A's exact anchor-level
decision — quarantine when the fraction of a `next` anchor's readings with unreliability
`U ≥ threshold` exceeds `bad_fraction` (0.5) over `≥ min_history` (6) readings — across the
90 076-reading labeled dataset (grouped by tag+episode+anchor, `U` computed with the same
embedded z-stats as `route_memory_agent._RELIABILITY_ZSTATS`). Score anchor-level recall
(of genuinely-degenerate anchors, how many get quarantined) vs. **false-quarantine rate**
(of good anchors, how many get wrongly banned — the dangerous, cascade-prone error).

**The old default 5.05 is inert for quarantine:** anchor-level recall **0.9 %** (2 of 836
groups). It was borrowed from Injection-C's high-precision operating point.

| threshold | recall | false-quar rate | note |
|---|---|---|---|
| 5.05 (old) | 0.9 % | 0.0 % | fires essentially never |
| 3.0 | 20 % | 3.1 % | conservative; misses ep680 (median U 2.53) |
| **2.5 (chosen)** | **29 %** | **4.2 %** | catches ep680 too; still does not false-quarantine the known-good anchors |
| 2.0 | 35 % | 5.5 % | starts false-quarantining ep5's good a10 |

The naïve Youden-J optimum sits at the sweep's aggressive end (thr ≈ −1.0, recall 77 % /
false-quar 16 %) and is **rejected**: it weights a false quarantine (→ cascade, the failure
that disabled `quarantine_next_quality` on 2026-07-15) equally with a miss (→ pin persists
but bounded by `max_chain = 4`), which is the wrong cost model. **Chosen: 2.5**, with the
`bad_fraction > 0.5` persistence rule and `max_chain = 4` as the guardrails.

**The ceiling, quantified.** Of the 10 ground-truth-degenerate pin `next` anchors, **5 are
U-detectable** (median U 3.9–4.8) and **5 are "confidently wrong"** — 74–98 % of their
bearings are wrong yet their median U is only 1.25–2.08, indistinguishable on scalar
features:

```
ep498 a4  U-detectable (median U 4.76)      ep20  a7  confidently-wrong (U 2.08)
ep500 a9  U-detectable (4.33)               ep319 a3  confidently-wrong (1.76)
ep653 a9  U-detectable (3.93)               ep367 a10 confidently-wrong (1.40)
ep994 a5  U-detectable (4.09)               ep813 a5  confidently-wrong (1.72)
ep680 a5  U-detectable (2.53)               ep1038 a3 confidently-wrong (1.25)
```

So **Injection A's ceiling is ~half the pins by construction** — the other half is the
vision residual the 0.84 scalar-feature AUC ceiling already predicted. This is not a bug to
tune away; it is the Route-1/Route-2 fork made concrete.

---

## 3. Injection A/B/C — completed, wired, validated

All in the isolated workspace `navila-gating-ab-v1/candidate/` (upstream_snapshot byte-
identical to live; nothing writes to live). Every change is behind a default-OFF flag; with
flags off, byte-behaviour equals upstream (proven: the full existing suite passes unchanged
against the candidate). Full diffs: `code/injection_ABC_route_memory_agent.diff`,
`code/injection_C_stop_gate.diff`, `code/cli_wiring_round_trip_eval.diff`.

- **Injection A** (un-stick the pin — absolute reliability quarantine of `next`): threshold
  default now **2.5** (§2). `_reading_unreliability` (dataclass fields only) +
  `_record_next_anchor_reliability` with stall-relief (`max_chain`, per-anchor
  `stall_attempts`, reset on promotion). Flag `--sequential_pair_reliability_quarantine`.
- **Injection B** (demote a bad `current`): `_record_current_anchor_reliability` /
  `_current_persistently_unreliable` track current's own U. When current is persistently
  unreliable, `_select_sequential_pair_relocalization` (i) no longer lets a closure
  current/next mismatch force the promotion vote to False, and (ii) waives the
  current-quality dominance bar — so a reliable `next` can promote past a degenerate pinned
  `current` (the one thing Part 1 §1.5 found nothing could do). Current is never itself
  quarantined. Flag `--sequential_pair_reliability_demote_current`.
- **Injection C** (downstream distrust): `_current_reported_confidence` caps reported
  confidence to `reliability_low_confidence_floor` when the reading's own U ≥ threshold;
  a new `RelativeStartProgress.distance_authority_low_reliability` flag makes
  `stop_gate.check()` **defer to the VLM instead of vetoing its stop** — the ep680 class
  (gate vetoed 258 correct within-radius stops on a pinned current). Flags
  `--sequential_pair_reliability_distrust_downstream` (+ `--reliability_low_confidence_floor`).

**Validation.** `code/test_reliability_gating.py` — 22 new unit tests (A: quarantine +
max_chain + stall-cap + skip; B: persistent-unreliable + two behavioural mismatch-promotion
tests confirming a bad current no longer vetoes a promotable next; C: confidence cap +
progress flag + stop_gate defer; off-by-default for all three). **22/22 pass.** The existing
suite (`test_route_memory_agent` + `test_geometry_pipeline` + `test_stop_gate` +
`test_instruction_rewriter`) re-run against the candidate: **286 pass, 14 pre-existing
skips, zero regressions.** `py_compile` clean. Diff totals: route_memory_agent +208/−2,
stop_gate +18/−0, round_trip_eval +91/−0.

---

## 4. Status & next step

| Item | Status |
|---|---|
| 16 ep capture | ✅ 15/16 (ep669 lost to VLM-startup, not capture) |
| Below-pin registrability (§1) | ✅ done — overturns 1/13; vision wall is narrow |
| Threshold calibration 2b (§2) | ✅ done — 5.05 → 2.5; ~half the pins uncatchable (vision residual) |
| Injection A / B / C + CLI + tests (§3) | ✅ done, default-OFF, 308 tests green, zero regressions |
| Merge to live + clean 100 ep fix-OFF vs fix-ON A/B | ⬜ next (the only measure of real return-rate gain) |

**The fork is unchanged but now evidenced:** finish is done; the decision to invest in
point-cloud/vision (to break the ~half-the-pins ceiling) should be made against the measured
return-rate delta from the fix-ON A/B, not in advance. Nothing here is enabled in any live
config yet — the A/B/C flags stay OFF until that one reviewed integration.
