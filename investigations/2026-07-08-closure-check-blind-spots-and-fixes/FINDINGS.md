# 2026-07-08 (afternoon/evening continuation) — the residual bearing-error tail's two failure sub-modes separated with ground truth; two candidate fixes built and offline-validated, one **failed** and was discarded, one **passed aggregate validation but failed a deeper per-action audit**; multi-frame anchor accumulation implemented and a live hard-11 batch launched; a three-way error-category breakdown is in progress

This continues same-day from `investigations/2026-07-08-guard-batch-live-validation/FINDINGS.md`, which ended with "an offline threshold sweep... is running" and no result yet. This document picks up from there. **Read this document in full before trusting any earlier same-day summary of "is the residual tail fixed" — the conclusion changed twice over the course of the day as deeper audits were run.**

---

## 1. The threshold sweep came back, but it's a confound, not a clean answer

The 6-point large-disagreement-threshold sweep (`0.75m/30°`=fully-removed → `1.5m/90°`=current default, 9 episodes, n=3260 pooled) and a follow-up entry-threshold sweep (`10°/0.25m`→`30°/0.75m`, 5 hardest episodes) both came back **looking flat**: pooled bearing-error mean only moved between 15.93–16.54° across the whole main-sweep range, and the entry-threshold sweep's own current default was already the best of the 4 points tried.

**This flatness is itself a confound, not evidence the threshold doesn't matter.** `bounded_evidence`'s promotion timing depends on the *closure-fused* distance (not each anchor's independent raw ICP) — `_select_sequential_pair_relocalization` runs `_sequential_pair_closure_precheck` **before** the promotion logic, and `AnchorRelocalization.distance_to_anchor_m` is a computed property off `anchor_dx_m/dy_m`, which the fusion/guard directly rewrites. So changing the guard threshold changes *which anchor is even "current" at a given attempt*, not just the accuracy of a fixed population — confirmed directly: per-anchor attempt-counts for the same anchor shifted measurably between sweep points (e.g. `ep368 anchor12`: 38 attempts at "removed" vs 25 at "default"). Quarantine (deciding whether to skip an anchor as a next-candidate) is **not** affected — it reads raw, pre-fusion estimates (`_record_next_anchor_stability` runs before closure precheck).

Per-anchor drill-down (matched-attempt-count pairs only, to control for the confound) found **two genuinely opposite effects mixed together in the pooled "flat" number**: some anchors (`ep680 anchor14`, n=42 both sides: 9.07°→15.40° as threshold rises) *want* a lower threshold — the guard genuinely helps them. Others (`ep994 anchor11`, n=28→29: 59.78°→48.60° as threshold rises) *want* a higher threshold — lowering it lets the guard trust a falsely-confident wrong reading it would otherwise not have touched. These cancel in the pool.

## 2. Two distinct, ground-truth-confirmed failure sub-modes, both currently unaddressed by the trust-aware guard

Direct instrumentation of raw per-side ICP output against ground truth (bypassing all fusion) on the offline `icp_replay_capture_hard11_20260706_accumulated` capture found:

**Sub-mode A ("ep680-style" — one side confidently wrong, guard already usually handles it):** `ep680` current=8/next=7 (and later 7/6, 6/5): current's raw bearing error is consistently tiny (0.1–3°); next's is ~170–180° wrong on most attempts, with `closure_heading_disagreement_deg`≈179° almost every time — **always clearing even the largest tested threshold (90°)**, which is exactly why this anchor pair looked "threshold-invariant" in the sweep. The guard *is* invoked essentially every attempt here. Most of the time `next`'s own `match_class` correctly self-reports `partial_pose_degenerate`/`ambiguous_high_confidence`, and the guard correctly substitutes it from `current`. The residual damage happens only in the minority of attempts where `next` **also** momentarily self-reports `clean_full_pose` despite being ~172–176° wrong (confirmed at e.g. `ep680` attempts 193/200/204) — the guard can't discriminate two sides that both claim to be clean.

**Sub-mode B ("ep994-style" — both sides simultaneously, correlatedly wrong, invisible to any disagreement-based check):** `ep994` current=2/next=1: dozens of consecutive attempts (e.g. 337–372) where **both** sides are 50–170°+ wrong vs ground truth, but `closure_heading_disagreement_deg` stays under 10° almost throughout — because both sides agree with each other on the same wrong answer. This is exactly `_sequential_pair_closure_precheck`'s own docstring-documented, previously-theoretical blind spot ("Confirmed NOT to catch the case where both anchors' fits are simultaneously, correlatedly wrong") — now given concrete real numbers. No threshold placement can fix this, because the trigger condition (disagreement > threshold) never fires in the first place.

## 3. Attempt 1 at a fix: rotational self-alias score — good diagnostic, **failed as a live-triggering mechanism**

**Idea:** precompute, per anchor (once, offline, same cost model as the existing identity `alias_score`), whether the anchor's own stored point cloud has genuine rotational self-symmetry — test a fixed-transform (no ICP re-solve) rotation of the point cloud against itself; a real local peak in overlap away from the trivial 0°/360° edge indicates the environment would look the same from a different heading.

**First implementation attempt was circular and wrong**, caught before it wasted more time: letting ICP *search* for the best transform between an anchor's cloud and a rotated copy of itself (mirroring how the existing `compute_anchor_alias_scores` checks cross-anchor identity aliasing) always returns overlap=1.0 for *any* shape at *any* angle, because ICP trivially rediscovers the exact applied rotation with zero residual — this measures "can ICP solve a noise-free problem" (always yes), not "does this shape look like itself from another heading." Fixed by using a **fixed transform, no re-solve**: rotate by a candidate angle about the origin (the anchor's own sensor location) and measure one-shot nearest-neighbor overlap directly, no ICP refinement allowed.

**Also had to exclude a second artifact**: small angles near 0°/360° always score artificially high for any dense point cloud (tiny angular displacement moves points little, especially near the sensor). Fixed by restricting to a genuine local peak in the 45°–315° range, reported as a "bump" (peak minus baseline-min in that range).

**Validated as a real, useful diagnostic**: found genuine, clean, specifically-180°-centered symmetry peaks on `ep680 anchor6` (bump=0.407) / `anchor7` (0.474), `ep994 anchor2` (0.223) / `anchor16` (0.225), `ep368 anchor12` (0.499) — a materially different set of anchors than originally hypothesized (`ep187 anchor16/17`, `ep994 anchor11` — the anchors originally suspected of being "confidently wrong" from the bearing-error survey — showed **no** meaningfully different bump from clean anchors; whatever makes them wrong is not this kind of geometric self-symmetry).

**Failed live-equivalent validation when wired into a "retreat `_target_anchor_index` to the previous current" mechanism**, gated on `(self_alias_score(current) and self_alias_score(next) both >= 0.20) AND small mutual disagreement`. Full 9-episode offline A/B:

| | OFF | ON |
|---|---:|---:|
| exact match | 41.8% | 36.0% |
| overshoot | 2.0% | 23.4% |
| reversals | 0 | 17 |

**Root cause of the failure, confirmed with a concrete case, not just the aggregate numbers**: `self_alias_score` is a static per-anchor shape property (**41% of all 117 anchors scored ≥0.20** when checked across the full population, not just the hand-picked confirmed-symmetric ones) — it says nothing about whether *this specific attempt's* reading is actually wrong. Ground-truth check on `ep680`'s actual retreat trigger found it fired at a moment when current(11)=1.05° error and next(10)=6.43° error — **both genuinely correct** — purely because both anchors' shapes happen to clear the static threshold. **This idea is not being pursued further as a live trigger; do not resurrect `self_alias_score` for real-time gating without a way to condition it on the specific attempt, not just the anchor's static geometry.**

## 4. Point-density / stronger-ICP-objective check: empirically confirmed NOT to help sub-mode B

Directly tested whether raising point density (default 0.10m voxel/512pts → dense 0.05m/2048pts, the existing `--route_local_map_profile=dense` stage-4B profile) shrinks the self-alias "bump" on the 5 confirmed-symmetric anchors above:

| anchor | default bump | dense bump |
|---|---:|---:|
| ep680/6 | 0.407 | 0.391 |
| ep680/7 | 0.474 | 0.470 |
| ep994/2 | 0.223 | 0.212 |
| ep994/16 | 0.225 | 0.248 |
| ep368/12 | 0.499 | 0.463 |

Essentially unchanged (peak overlap at 180° actually rose in most cases — more points made ICP *more* confident in the wrong solution, not less). **Conclusion: raising point density, or upgrading the ICP objective (point_to_line/NDT), cannot fix genuine geometric self-similarity** — a denser sample of the same viewpoint still sees the same symmetric structure. These levers remain plausibly useful for the separate corridor-degeneracy/weak-constraint failure mode (not investigated further today), just not for sub-mode A/B. **Do not invest in point-density/ICP-objective changes as a fix for the confidently-wrong or correlated-wrong sub-modes.**

## 5. `match_class`/`near_tie_basin_count`, used directly (not gated behind large disagreement), is a real, already-existing discriminator

Checked directly against all already-logged ground-truth data (no new anchor-shape signal needed) before building anything:

| grouping (per side, regardless of agreement) | n | both sides actually wrong (>45°) |
|---|---:|---:|
| both self-report trustworthy (`clean_full_pose`+`near_tie==0`) | 71 | 5.6% |
| both self-report NOT trustworthy | 43 | 60.5% |
| — narrow sub-sample, also small mutual disagreement (the exact sub-mode-B signature) | 24 | 79.2% |
| — later, wider sample across more anchor pairs (ep994 anchors 2/3/11/12/13/14, ep368 5/6, ep680 6/7) | 42 / 2 / 5 | 38.1% / 100.0% / 60.0% (per episode) |

**This is a real, meaningfully better signal than `self_alias_score`** (which showed ~0% usable precision on its own triggered case). Per-attempt precision is not perfect and varies a lot by episode (38–100%), which is why the mechanism built on it (§6) was deliberately designed not to act on a single reading.

## 6. Attempt 2 at a fix: `match_class`-based trend-gated reject/retreat — passed aggregate validation, then **failed a deeper per-action audit**

**Design** (mirrors quarantine-trend's "whole dwell-time" philosophy rather than acting on one reading): if current+next both self-report untrustworthy AND their disagreement is small (below the existing entry threshold — exactly the sub-mode-B gap) → **reject this one attempt outright** (cheap, self-correcting). Only if this persists (≥5 of the last 8 attempts, for the same current anchor) → **retreat** `_target_anchor_index` back to whatever anchor was current right before the most recent promotion, capped at 2 retreats per anchor to prevent oscillation.

Confirmed safe to reject outright now (this was *not* true when belief_fusion was first designed): the old odometer-gated `no_sequence_candidates`/`_distance_since_sequence_observation_m` permanent-stall risk that originally justified belief_fusion's "never reject" philosophy is **not in the `sequential_pair` call path at all** — `_select_sequential_pair_relocalization` only calls `_estimate_arc_observation`, which has no reject gate — confirmed by reading the current code, not assumed.

**Full 9-episode offline A/B (`validate_trend_reject_mechanism.py`) looked good in aggregate:**

| | OFF | ON |
|---|---:|---:|
| exact match | 41.8% | 43.3% |
| overshoot | 2.0% | 2.4% |
| reversals | 0 | 7 |

10 total retreat actions fired (6 in `ep994`, 2 in `ep5`, 1 each in `ep368`/`ep680`); 4 of 9 episodes (4, 187, 367, 1040) triggered nothing at all.

**A deeper, definitive audit (`audit_retreat_actions.py`) then walked this conclusion back substantially — this is the current, corrected bottom line, not the aggregate table above:**

- **Recall is poor**: pooled across all 9 episodes, 236 attempts had a genuinely wrong (>45°) reading on whichever anchor was current at the time. Only **27 (11.4%) were caught** (rejected or retreated) — **209 (88.6%) were still silently accepted as normal.**
- **Precision of the retreat action itself is poor**: of the 10 retreats, ground-truth-checking the *actual* recent bearing errors of the anchor being left (not just whether the trigger condition fired) found only **2–3 were clearly justified** (majority of the recent window genuinely >45° wrong — `ep368` attempt 185: 6/8; `ep994` attempt 342: 5/5, the original known-bad `anchor2→3` case). **7 of 10 were false positives to varying degrees**, including **3 with literally zero bad readings in the entire lookback window** (`ep994` attempts 54, 64, 83 — retreating from an anchor whose last 5–8 readings were all genuinely accurate, purely because `match_class` kept reporting "ambiguous" while the winning candidate happened to be correct each time).

**Root cause of this gap: `match_class`/`near_tie_basin_count` measure whether the ICP *matching process* found the solution ambiguous, not whether the *winning candidate* is actually wrong.** An anchor can be persistently flagged "ambiguous" while still consistently picking the correct pose by luck — the persistence-window escalation treats "persistently uncertain" as a proxy for "persistently wrong," and this proxy is not reliable enough on its own (confirmed directly, not assumed).

**Scale/framing correction (the mechanism is not "widespread damage," it's "rare but low-precision when it fires"):** only 10 retreat actions total across 3260+ attempts; 5 of 9 episodes had zero mechanism activity at all; the false positives are concentrated almost entirely in `ep994` (5 of its 6 retreats questionable) and `ep5` (both of its 2 retreats questionable). The earlier aggregate table (41.8%→43.3% exact) is not wrong, but it understates the problem — a wrongly-triggered retreat mostly costs a "lag-1" (adjacent-anchor) reading rather than a catastrophic one, so the aggregate metric absorbs the mistake without it being visible there.

**Current status: this mechanism is validated-as-flawed, not validated-as-ready. It has NOT been ported into the live `route_memory_agent.py` code** (the reference implementation lives only in `/tmp/claude-1006/.../scratchpad/validate_trend_reject_mechanism.py`, offline). **Next step, not yet done**: add a signal that distinguishes "persistently uncertain but the actual reported dx/dy/dtheta values are stable/self-consistent across the window" (probably fine, don't retreat) from "persistently uncertain AND the reported values are themselves drifting/inconsistent" (the real signature of `ep368`/`ep994`'s 2–3 genuinely-justified retreats) — match_class/near_tie alone, even trend-gated, is not sufficient.

## 7. Multi-frame anchor submap — implemented live, a hard-11 batch is running (result pending)

Motivated directly by §4's finding that point density can't fix genuine symmetry — the missing ingredient is *new geometry* (a different vantage point), not denser sampling of the same one.

**Implemented in the live code** (not just offline scratch): `route_memory_agent.py` gained `multiframe_anchor_window` (constructor param, default `1` = old single-instantaneous-frame behavior, byte-identical) — a rolling buffer of the last N outbound frames' `(pose_at_capture, descriptor)` is kept in `update_outbound_motion`; at anchor creation, a new `_merge_outbound_frame_buffer` method reprojects every buffered frame's own raw points from its own capture-time pose into the anchor's final frame (plain SE(2) point transform, same math as the file's existing `compose_pose`/`relative_delta`) and concatenates them into one richer submap before storage — downsampling still happens later at match time via the existing `voxel_downsample_2d`, unchanged. `round_trip_eval.py` gained `--route_memory_multiframe_anchor_window` wired through to the agent.

4 new hand-verified unit tests added (translation-only merge with hand-computed expected coordinates, a 90°-turn-then-move case, default window=1 unchanged, frames with an unrecognized/missing descriptor key skipped without crashing) — full suite **158→162 tests, zero regressions**.

**Window size chosen from real data, not guessed**: `ep4`'s actual outbound trajectory is ~147 outbound env-steps per meter (1300 steps / 8.83m at mean recorded speed 0.35 m/s). Picked **window=120 outbound steps ≈ 0.8m** (close to one full `anchor_spacing_m`) as an untuned first-pass value, specifically so the merged submap has a real chance of reaching new geometry (a door/bend) beyond one viewpoint's local symmetry radius, rather than just padding with a few cm of near-identical points.

**Live batch launched 2026-07-08 19:46** (fully detached — confirmed via `ps`: master script PPID=1, already reparented to init, distinct session ID from any interactive shell, no controlling terminal; survives session/connection close): `multiframe_anchor_hard11_20260708_accumulated`. Master log `/home/teambruce/multiframe_anchor_hard11_20260708_master.log`, launcher `/home/teambruce/run_multiframe_anchor_hard11_20260708.sh`. Identical flags to the already-validated `hard11_live_trust_aware_guard_20260707_accumulated` batch (`bounded_evidence`+`alias_aware`+`trust_aware_guard`, oracle hints, `stop_gate`, `hint_action_arbiter`, `interval=5`) plus only `--route_memory_multiframe_anchor_window=120` — directly comparable against that existing batch's numbers (bearing mean 19.88°, anchor-selection 55.9% exact) as baseline without a fresh window=1 re-run. **As of this writing, only episode 4 (of 11) had started; result pending, not yet analyzed.**

## 8. Three-way error-category breakdown — launched, in progress, no numbers yet

To directly answer "what fraction of all ICP bearing errors >10°/>20° are (1) genuine self-similarity-explained confidently-wrong (`self_alias_score>=0.20` AND trustworthy-but-wrong), (2) ICP-self-flagged uncertain (§5's `match_class`/`near_tie` definition), vs (3) neither — an unexplained residual," across **all** attempts (not a curated/suspicious-anchor sample) in all 9 episodes: `full_error_category_breakdown_v2.py` was written and launched in parallel across all 9 episodes. **Not complete as of this writing — do not trust any percentage for this breakdown unless it was computed after this document's timestamp.**

## Pending / next steps (current front as of this writing)

1. Analyze the `multiframe_anchor_hard11_20260708_accumulated` live batch once it finishes (§7) — re-run the same per-anchor ground-truth forensic methodology used throughout today, focused on the 5 confirmed-symmetric anchors, to see whether the self-alias overlap signature and resulting bearing error actually shrink with ~0.8m of accumulated context.
2. Collect the three-way error-category breakdown (§8) once it finishes.
3. The trend-gated reject/retreat mechanism (§6) needs a value-consistency signal added before it's worth porting live — not yet designed.
4. Sub-mode A's residual gap (the guard occasionally fooled when the wrong side also self-reports clean) is still open and not specifically addressed today.
5. As always: re-fetch the GitHub README fresh for anything newer than this entry before proposing next steps; this document is a same-day supplement to it, not a replacement.
