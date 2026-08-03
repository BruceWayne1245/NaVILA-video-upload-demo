# 2026-07-22 — Session summary: fix-ON batch ground-truth diagnosis, failure taxonomy, two shipped fixes, and the V1.1 shadow batch launch

Full record of the 2026-07-22 working session. Builds on the fix-ON A+B+C run
(`reliability_fixon_100ep_20260721_accumulated`) analysed here, and ends by shipping two
new default-off controller fixes into live and launching the frozen 100-episode V1.1
prospective-shadow batch. Design detail for the two fixes is in
[`DESIGN_stuck_recovery_and_multiview.md`](DESIGN_stuck_recovery_and_multiview.md).

---

## 0. TL;DR

1. **Ground-truth return rate of the fix-ON run, after reclassifying crash-lost episodes, is ~12/20 (≈60%)** vs batch2's fix-OFF ~7/26 (27%). Injection C's `deferred` (veto→defer) and the anchor-corroborated forced stop carry **all 9** clean successes — **not one** was a clean VLM-initiated stop the gate merely accepted; in 5 of the 9 the VLM never even asked to stop.
2. **The 8 return failures are NOT one problem.** Only ~1.5/8 are the "surrounded by degenerate anchors" pin. The real split: **3 confidently-wrong** (134/813/669), **2 control/wall-wedge** (5/653), **1 VLM turn-oscillation** (491), **1 VLM wrong-navigation** (994), **1 near-miss** (367). ~3/8 are outside the relocalization system entirely.
3. **"Confidently wrong" (clean scalar features + wrong pose, usually rotational aliasing in self-similar corridors) is the single dominant relocalization-internal failure and defeats every scalar/U signal we have** — A, B, C, and a tested closure-relaxation carve-out (33% would wrongly promote) all fail. A multi-view offline go/no-go (AUC 0.737, blind to the symmetric-corridor cases) says this half **needs vision**, not more scalar gating.
4. **Two fixes shipped (default-off flags, merged to live, 309 tests green, 0 regressions):**
   - **`--reliability_quarantine_shared_trend_budget`**: the old position-trend quarantine had **no** `max_chain` and was the mechanism that blacklisted an entire downstream and permanently sealed the ep134 pin (Injection A's `max_chain` correctly capped A at 4; trend cascaded the rest). Now trend draws from A's shared anti-cascade budget.
   - **`--stuck_recovery`**: a pure return-phase locomotion supervisor. Detects no-net-progress (validated offline: 0 false positives on the 9 successes, fires on 5/653/491/994) and scripts a back-out (reverse ~180°, drive out, re-face next). Includes a **flip-turn-direction** escape (if the base can't rotate one way — the ep5 wedge — try the other).
5. **Shadow contract honored:** launched `reliability_v11_prospective_capture_shadow_100ep_20260722_accumulated` — Claude's controller is the sole navigator; codex's frozen V1.1 sklearn model is **offline capture-shadow only** (no online inference, no enforcement). Batch is under `user@1006.service` (cgroup-verified) so it survives disconnect.

---

## 1. Ground-truth return rate of the fix-ON run

Method: true final distance-to-start from measurement `round_trip.distance_to_start` (clean episodes) or reconstructed from `icp_replay_dataset` `robot_world_pose` (crashed episodes). Reclassification per user rule: crashed-too-early-to-judge → **exclude**; crash robbed an at-home/arriving outcome → **success**; clearly failed → **failure**.

- **Return success ≈ 12/20 = 60%** (SUCCESS: 4,88,89,319,368,500,589,647,680,783,889,1038; FAIL: 5,134,367,491,653,669,813,994; EXCLUDED: 189,277,295,382,498,537). Robust: excluding the softest crash-salvage (ep319) still gives 11/19 = 58%.
- Context: fix-ON clean registered-only = 9/15 = 60%; batch2 fix-OFF ground truth = 7/26 = 27%. **Denominators differ (no paired fix-OFF on these 100), so this is not yet a causal A/B claim.**
- **Every one of the 9 clean successes ended via the stop layer, never a clean VLM stop.** 6 = anchor-corroborated `forced` (in 4/89/500/589/647 the VLM never requested a stop during return; 4/500/647 forced at conf 0.2–0.47, far below `min_confidence`); 3 = Injection C `deferred` (368@1.33m, 680@1.45m, 1038). ep88 vetoed 8 within-radius stops then forced; ep1038 vetoed 9 then deferred → **the veto side is still over-aggressive, but the forced/deferred backstop rescues it.**
- **Capture-induced crashes are a real operational problem:** 8/26 completed episodes lost measurement+trajectory+video (only `icp_replay` survived), disproportionately the long-return hard episodes. batch2 (no capture) completed all of them → the crashes correlate with `--capture_icp_replay_dataset` I/O, not the fix.

## 2. Per-failure deep dives (the 8 failures)

| ep | true final | root cause | class |
|---|---|---|---|
| **134** | 7.13m | pin on confidently-wrong `current`15 (B blind: median U 0.34) + true-next `14` degenerate; trend cascade sealed downstream | confidently-wrong |
| **813** | **0.29m (home!)** | pin on wrong `current`6; **B fired** (U 3.19) but promotion still failed → never stopped | confidently-wrong / promotion gap |
| **669** | 4.60m | confidently-wrong `anchor`3 (dtheta 84°/bearing 175°, clean scalars, U 1.13) escaped A/trend, got promoted, then its wrong 1.42m reading fooled the plain high-conf stop | confidently-wrong / false stop |
| **5** | 9.48m | **physical wedge**: VLM cmd forward 0.5 m/s, base moved 0.026; anchor correct, hint accurate 1–6°, VLM following — pure control/wall issue | control/wall |
| **653** | ~9m (crashed) | tracker ~1 ahead → hint off ~25° → drifted off-route to 12m → **physical wedge** (cmd 0.5/act 0.013) | control/wall (+mild hint) |
| **491** | 6.7m | VLM **turn-oscillation** (only turns, never forward); `hint_action_arbiter` gated 82× by `low_relocalization_confidence` (traces to the pin) | VLM oscillation |
| **994** | ~6m | VLM executed fine (cmd 0.5/act 0.398) but navigated wrong + 910× premature "I've finished" | VLM navigation |
| **367** | 3.09m | pin at 11 that **did** release (11→10→…→6); reached 3.09m — 0.09m short | near-miss |

### 2.1 ep813 — the promotion "timing trap" and closure the accomplice
- The only geometric window to promote `current`6→`next`5 is **early** (att 37–52, when the robot physically passes anchor5; next5 `estDist` 0.36–0.73m, `close_enough`). But in that window `current`6 is **confidently-wrong-but-clean** (`clean_full_pose`, U≈−5) → **B does not fire**, and `closure_precheck` flags the current/next disagreement → **forces the vote False**. By the time `current`6's U crosses threshold (B activates att95) the robot has walked **past** anchor5 → `close_enough` false forever → `candidate_promote = quality_ok AND (close_enough OR trend_ok)` = False.
- **closure is the sole blocker:** at att37–52, `quality_ok` PASSED (next5 quality 21–22 vs 0.85·current 17–18); 15/18 attempts satisfied `quality_ok AND close_enough`. Without closure's forced-False, bounded_evidence would have promoted → pin never forms. So closure faithfully detected a real disagreement, but its default (protect current, veto next) is fatal when `current` is the wrong side and B can't flag it.
- **next5 was never quarantined — correctly:** it is the true current (reads 6°@7cm; trend's "improves as robot approaches" check passes: disagreement 1.64m close vs 4.02m far). Quarantine only ever touches `next`; the broken side is `current`, and nothing can evict a bad `current` except a promotion the degeneracy prevents.

### 2.2 Why A/trend miss ep669's anchor3
Its error is **rotational** (dtheta 84°), scalars clean (168/257 `clean_full_pose`, inlier 166, conf 0.78 → U 1.13). A uses scalar U (blind); trend uses **position** disagreement (blind, since position is consistent). Neither examines bearing/rotation correctness. The same low U means Injection C does not flag the stop reading as low-reliability → the plain high-conf stop path (`anchor_route_remaining`=3.01>r_in, so anchor-corroboration did NOT fire) accepts the wrong 1.42m at conf 0.74.

### 2.3 The two "physical wedge" failures (ep5, ep653), by executed-vs-commanded
Trajectory `command` vs actual `speed_mps` distinguishes the classes: **ep5/ep653 = executed ≠ commanded** (cmd forward 0.5, actual 0.01–0.03 → base physically stuck). ep5 reconstruction of the wedge onset (step ~2000→2226 at (1.1,3.5)): anchor correct (报11真11), hint accurate (1–6°), VLM following — everything worked and the base simply drove into a dead corner and could neither translate nor rotate (yaw wiggled ±5°). **ep491 = VLM turn-oscillation** (only turns, never forward). **ep994 = VLM wrong-nav** (executed correctly, drove the wrong way).

## 3. The trend cascade finding + shared max_chain fix

- Faithful replay of Injection A on ep134: A quarantined **exactly 4** anchors (14,10,9,8) then stopped — `max_chain=4` worked. The remaining `offered-next` sweep to anchor 1 (tail: only `current` read, no next at all) was the **old position-trend quarantine** (`quarantine_mode=trend`, canonical), which has **no `max_chain`** and, under a pin, self-fulfillingly blacklists the whole (never-approached) downstream — permanently sealing the pin.
- **trend is not "old A":** the current-independent predecessor of A is `quarantine_next_quality` (2026-07-15, deprecated for cascading, correctly OFF). trend is a **current-relative** signal. 07-21 already showed trend fires **0/13** on the real pins.
- In the 9 successes, trend's unique contribution is net-negative and never decisive: 7/9 zero, ep89 one genuine catch A missed (non-decisive), ep589 **3 false-quarantines of good anchors** (9/7/6).
- **Fix (`--reliability_quarantine_shared_trend_budget`, default off):** a trend quarantine now also consumes A's `_reliability_quarantines_since_promotion` budget, so A+trend together can never blacklist more than `max_chain` anchors between promotions. Off ⇒ byte-identical. 4 new unit tests.

## 4. Go/no-go offline tests

- **① stuck detector — PASS.** Fire when net displacement < 0.15m for ≥`N` consecutive VLM queries **and** believed distance-to-home > 5.0m (near-home is stop_gate's job) **and** the VLM isn't trying to stop (guards ep813). At `N≥6`: **0 false positives on the 9 successes; fires on ep5/491/653/994.** Belief-distance gate (live-realistic) also clean at >5.0m.
- **② multi-view — NO.** Implied-anchor-position spread across viewpoints (baseline ≥0.3m) separates confidently-wrong from good at only **AUC 0.737** (≈ scalar U's 0.80), leaky (T=0.5m → 52% recall / 21% false-positive), and **inverts on the symmetric-corridor anchors that dominate the failures** (ep134 a15, ep669 a3, ep813 a6: confidently-wrong spread ≤ good spread — the wrong lock is consistent across views). Conclusion: **this half is physically irreducible from LiDAR → needs vision.** Not built.

## 5. Code changes (all default-off, merged to live 2026-07-22)

Isolated in `navila-gating-ab-v1/candidate/`, merged to `NaVILA-Bench/scripts` after `309 tests / 14 skips / 0 regressions`. Live source hashes locked for the shadow batch:

```
round_trip_eval.py    7941f9a9611c11c16491ac18db9d2baffc5862c98157c6bfd7c204c304172866
route_memory_agent.py 1e6af8cef24b2743ea68c9fc525a80ea85e7985a087f1f63309684f6b475fbf8
relocalization.py     226a87b68d5727982a03763da19ec10baf7f90f8d61a66f29e288b8e6bfb09c1  (unchanged)
stop_gate.py          0c37014abdc4bc4ad66bf23f167292c3b7ecc21c9a4f09c0d672888bb4f79d0b  (unchanged)
stuck_recovery.py     a23cfc6c18816eb8299b7b75eb7f0882455fb1f81c7c33a609c0ebfaabbb6b72  (new)
```

- **`route_memory_agent.py`** (+shared trend budget): `_record_next_anchor_trend` quarantines now respect/increment the shared `_reliability_quarantines_since_promotion` budget when the new flag is on.
- **`stuck_recovery.py`** (new module) + **`round_trip_eval.py`** integration (highest-priority action override in the return VLM-query block, after `hint_action_arbiter`). Flags: `--stuck_recovery` (+ `_move_min_m`, `_n_queries`, `_belief_far_min_m`, `_escape_forward_m`, `_max_queries`, `_max_attempts`). Recovery state machine: `reverse_turn → escape_forward → face_next → normal`, with a **flip-direction** guard (yaw not progressing ≥12° for 2 queries → flip left/right; target is antipodal so either direction reaches the reversed heading) added after the ep5 live smoke showed a fixed "turn left" spun the command 13× with the base never rotating out.

### 5.1 ep5 live smoke (what it confirmed / didn't)
Merged code + `--stuck_recovery`. **Plumbing validated**: detector fired at the exact wedge step (2226), the scripted turn override replaced the VLM action end-to-end. **Limitation exposed**: ep5's wedge could block rotation entirely (13× turn-left, no yaw change) → motivated the flip-direction fix. A re-run with the flip fix did **not** re-wedge (ep5 took a different, non-wedging trajectory — VLM non-determinism), so the flip is unit-tested but not yet observed firing live. The 100ep will exercise it across many episodes.

## 6. The V1.1 prospective-shadow batch (launched)

- Tag `reliability_v11_prospective_capture_shadow_100ep_20260722_accumulated`; controller `claude_ABC_trendbudget_stuckrecovery_20260722`; config = canonical A+B+C + `--reliability_quarantine_shared_trend_budget` + `--stuck_recovery` + `--capture_icp_replay_dataset`.
- **Shadow contract preserved** (`investigations/2026-07-22-v1_1-prospective-shadow-handoff`): 100 frozen fresh episodes (manifest SHA `60d2adf3…`, no overlap with the prior 100), V1.1 artifact frozen (`5f23aba4…`) but **no online inference, no enforcement** — scored offline after capture. Preflight passes on all 6 code hashes + manifest + artifact.
- **Disconnect-safe (cgroup-verified, not assumed):** relaunched under `systemd-run --user` → cgroup `user.slice/user-1006.slice/user@1006.service/app.slice/v11_shadow_100ep_20260722.service` (NOT a session scope), Linger=yes. Manage via `XDG_RUNTIME_DIR=/run/user/1006 systemctl --user status|stop v11_shadow_100ep_20260722`.
- Not a paired A/B: these 100 have not been run under the old controller. batch2 remains the fix-OFF reference on a different (overlapping-config) 100.

## 7. Plan / next steps

1. **Analyse the shadow batch** once outbound-success episodes accumulate: return rate vs batch2, and — VLM-noise-robust — mechanism firing counts (`stuck_recovery` state transitions incl. `flipped_turn_direction`; trend-budget effect on ep134-class seals; C `deferred`/`forced`). Do-no-harm check on any batch2 successes.
2. **Confidently-wrong is the gating ceiling and needs vision** (multi-view ruled out). The vision-fusion investment should be decided against the measured return-rate gain from the two shipped fixes, not in advance. Do **not** build more scalar-feature gating for it.
3. **ep813 promotion timing trap** — a candidate non-vision fix (remember a next that was recently `close_enough`, so B's late activation can still promote it) is possible but was deprioritised behind the wedge/trend work; revisit if the shadow batch shows it recurring.
4. **ep669 false-stop** — the plain high-conf stop trusting a confidently-wrong reading is a narrow, likely-cheap fix (require anchor-identity agreement even on the high-conf path), 1-episode impact; candidate for a later pass.
5. **Capture-crash instability** — if the shadow batch again loses long-return episodes to `--capture_icp_replay_dataset` I/O, consider sampled-frame capture; otherwise the hardest episodes keep going un-analysed.
6. **codex V1.1** scores the shadow capture offline per its frozen contract; its prospective bearing/distance/pose risk is the model deliverable, navigation success stays Claude's.
