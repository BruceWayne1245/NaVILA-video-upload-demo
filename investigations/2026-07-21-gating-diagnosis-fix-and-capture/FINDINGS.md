# 2026-07-21 — Session summary: batch2 gating-failure diagnosis, the reliability fix, and the capture subsystem

This is the full record of the 2026-07-21 working session. It covers every finding, the
supporting data, the code changes made, current progress, and the plan. The ML-model
feasibility deep-dive and its analysis scripts live in the sibling folder
`investigations/2026-07-21-icp-reliability-signal/` (referenced below, not duplicated here).

---

## 0. TL;DR

1. **batch2's low return rate is not mainly a navigation problem — it's the stop/gating decision.**
   Of the 19 return-failures among `canonical_report_next_stopgate_100ep_20260720`'s outbound-success
   episodes, **8 physically ended inside the 3 m success radius (0.01–2.64 m) yet were logged as
   failures** — the robot walked home but no valid stop registered. If the stop decision worked,
   return would be ~15/26 (~58 %) instead of 7/26 (27 %).
2. **The immediate cause is a permanent tracker "pin"**: `current` advances normally until it lands
   on a degenerate anchor, then freezes. The robot keeps walking home while the hint / `stop_gate`
   distance authority stays frozen and wrong.
3. **The pin is H2 (intrinsically degenerate anchors), not H1 (a lock-in feedback).** The ICP path is
   memoryless — no accumulating state — so "ICP gets worse over time" is a viewpoint artifact of the
   robot walking away from the pinned anchor, not a self-reinforcing loop.
4. **The gating cannot escape because every next-side gate is measured relative to `current`**, so a
   bad `current` poisons all of them, there is no mechanism to evict a bad `current`, and the escape
   hatch (`quarantine`) fired **0/13** on the stuck episodes (it keys on position, blind to the
   rotational aliasing that is the actual defect; and its sigma-normalized trip point is ~2–4 m).
5. **An absolute, current-independent reliability signal is buildable** and far better than what the
   gates use today. A **zero-training hand combination of 4 diagnostics reaches AUC ~0.80**; a trained
   model tops out at **~0.84** — the "confidently wrong" residual (~16 %) is unseparable from these
   scalar features and needs point-cloud/vision.
6. **Offline counterfactual replay is humbling**: distrusting the bad reading in `stop_gate`
   (Injection C) recovers only **2/8** stop-decision episodes on its own; the rest are coupled to
   un-sticking the pin (Injection A/B), which **cannot be validated offline** from the existing batch
   because the pin prevented the below-pin anchors from ever being read. Hence the capture re-run.

---

## 1. Findings

### 1.1 Return-rate reality (ground truth, not self-reported)

- batch2 (`canonical_report_next_stopgate_100ep_20260720`), 26 usable outbound-success episodes:
  **return 7/26 (27 %)** on the outbound-success subset.
- **The old-50 subset, re-run, gives 5/15 = 33 % — not the 6/8 = 75 % headline of the 50 ep batch.**
  Same byte-identical config, same 50 episodes. `ep367` even flipped success→fail. So the 75 % was a
  small-sample + VLM-non-determinism artifact; the realistic return rate is ~30 %.
- New vs old episodes: same 9 scenes, `dataset_reverse_path_neighbor` provider for all (return paths
  are structurally fine), 2 new episodes returned successfully. New episodes are not "broken"; they
  are simply harder-on-return and there are more of them.

### 1.2 The dominant failure is the stop decision, not navigation

Trajectory-confirmed true final distance for the 19 fails:

| Bucket | Count | Episodes |
|---|---:|---|
| Ended **≤ 3 m from start** but logged as fail | **8** | 5(0.01), 20(0.03), 498(0.03), 680(0.26), 889(1.63), 382(1.70), 537(2.42), 89(2.64) |
| Passed ≤ 3 m then driven back out | 3 | 88, 813, 319 |
| Genuine navigation failure (never near home) | 8 | 277, 500, 1038, 669, 491, 994, 367, 653 |

Code fact (`round_trip_eval.py:2841,3047,3077`): `return_success` is only set inside
`if _vlm_stop_requested:` — a stop event must fire *and* be within radius. Being physically within the
radius at episode end (via timeout/step-limit) is **not** success. The mechanism: degraded ICP →
`stop_gate`'s believed distance `gate_authority_d` is wildly overestimated → it **vetoes the VLM's
correct stops** (ep680 vetoed 258 stops while truly at 0.26 m; ep498 162; ep5 39). For the "no-stop"
subset (89/382/537/889) the pinned tracker's "you're far" hint suppressed the VLM's stop entirely and
the anchor-corroborated forced-stop never fired.

### 1.3 Failure classification (a/b/c/d)

- **(d) stop-decision failure, robot at home — ~8**: gate vetoed correct stops / no stop ever fired.
  Root = corrupted route distance from the pin.
- **(a) bad ICP → wrong hints → navigation drift, never got home — ~7**: ICP joint rate 11–29 %.
- **(c) VLM deviates + arbiter/gate can't hold — ~3** (319, 813, 88): reached home vicinity then
  driven back out.
- **(b) robot physically can't advance — ~0**: the "stuck" cases were stuck *trackers* while the
  robot kept moving home.

### 1.4 The pin: intrinsically degenerate anchors (H2), not a lock-in feedback (H1)

Per-anchor ICP breakdown (`data/02`) and pin-anchor time-course (`data/03`) over 13 stuck episodes:

- In 13/19 fails, `current` pins on a specific **bad** anchor. Two sub-patterns:
  - **current itself intrinsically bad** (7): ICP bearing error 28–128° **even at 2–10 cm from the
    anchor** (ep994 128° at 2 cm, ep20 83° at 4 cm). Bad from first close contact; `near_tie` 1–2,
    `match_class` = `ambiguous_high_confidence` / confidently-wrong `clean_full_pose`.
  - **current fine, but next (=current−1) intrinsically bad** (5): ep319/669/1038/367 register the
    current anchor at 0.1–5.8° when near it, but the promotion target is degenerate.
- All 13 pin anchors have `localizability` weakest-eigenvalue ≈ 0 and elevated corridor-degeneracy —
  the geometric under-constraint signature.
- **"ICP gets worse over time" is a viewpoint artifact, not H1 feedback**: last-contact true distance
  grew from ~1–2 m to 4–10 m as the robot walked away from the pinned anchor; the ICP is recomputed
  fresh each attempt (no accumulating state since 2026-07-05), so a "stuck" state cannot degrade a
  fresh registration. **Verdict: H2.**

### 1.5 Why the gating cannot escape (mechanism diagnosis)

Two doors must open to leave a bad anchor: **A) promote past it**, or **B) blacklist + skip it**.
Both are jammed (`data/04`):

- **Door A (promotion)**: `closure_precheck` (bearing signal) flags the current/next disagreement and,
  because both degenerate sides have saturated similar quality (neither dominates 1.5×), returns
  `mismatch` → forces `candidate_promote=False` every attempt → `bounded_evidence` never accumulates a
  True vote. The alias stall-relief only relaxes the vote *count* (8/5→5/3), useless when there are 0
  True votes. (`quality_ok` at 0.85× is lenient and not the blocker; `promotion_score_ratio=0.85`.)
- **Door B (quarantine)**: `_record_next_anchor_trend` keys on **position** disagreement
  (`route_memory_agent.py:1270`), blind to the **bearing** defect; the sigma normalization
  (`_closure_disagreement_sigma_m` ≈ 1.4–2.8 × `z_threshold` 1.5) pushes the trip point to **~2–4 m**
  while degenerate anchors disagree by only ~1 m in position; and the "improving as robot approaches"
  check (line 1290) is fooled once the robot walks away. **Result: quarantine fired 0/13** (offered
  next was always exactly current−1, gap never > 1).
- **Structural root**: `closure`, `quarantine-trend`, and promotion `quality_ok` are all *relative to
  `current`*, so a bad `current` poisons all of them; the one current-independent supervisor
  (`_record_next_anchor_quality`) is OFF (it cascaded for lack of a stall-relief). And **nothing can
  evict a bad `current`** — it can only leave via a promotion the degeneracy prevents.

### 1.6 Reliability-signal feasibility and the 0.84 ceiling

(Full detail + scripts in `investigations/2026-07-21-icp-reliability-signal/`.) 90,076 ground-truth-
labeled readings, episode-grouped CV:

- Single-signal AUC: `inlier_count` 0.787, `best_to_second_score_ratio` 0.780, `localizability`
  min-eig 0.771, `confidence` 0.759, residuals ~0.75; near-useless: `corridor_degeneracy_ratio` 0.523.
- **Direct use ≈ model**: hand z-score sum of top-4 = **0.799**; logistic = 0.801; GBDT all features =
  **0.841**. The model buys only +0.04, so **Route 1 needs no ML — use the signals directly.**
- **0.84 is the ceiling with scalar features**; the confidently-wrong core (~16 %) is unseparable and
  needs raw point clouds / basin landscape / multi-view, and a residual is physically irreducible from
  LiDAR (self-similar corridors) → vision fusion. Codex's Route-2 model independently reproduced this
  (bearing head AUC 0.816 on a stricter chronological split; 13/13 pin detection; **0/8 stop
  recovery**; all three trusted-bad-rate gates FAILED → it correctly locked enforcement to shadow).

### 1.7 Offline counterfactual replay of the fix (`data/05`)

- **Injection C** (stop_gate defers instead of vetoing when the distance-authority reading is
  low-reliability): recovers **2/8** — ep5 and ep680, where the robot issued within-radius stops that
  were flagged low-reliability by the 0.80 signal (validating the signal end-to-end). The other 6
  reached home but issued **no** within-radius stop, so there is nothing to accept — they need a
  forced-stop-when-home that is itself blocked by the pin.
- **Injection A/B** (un-stick the pin) **cannot be validated offline** from this batch: the pin
  prevented the tracker from ever reading the below-pin anchors, so their registrability along the
  real home-bound trajectory was never captured. → motivates the capture re-run.

---

## 2. Code changes made this session (isolated workspace `navila-gating-ab-v1/`, live untouched)

Same isolation discipline as codex's `navila-reliability-v1`: `upstream_snapshot/` byte-identical to
live (SHA-256 `29915c12…e693005`), `candidate/` the only edited copy, all changes behind default-off
flags. `route_memory_agent.py` diff = 106 additions, 1 condition line widened; `py_compile` clean.

### 2.1 Injection A core (`code/injection_A_route_memory_agent.diff`)

Absolute, current-independent reliability quarantine of `next` — the escape hatch quarantine-trend
never opened:
- `_reading_unreliability(estimate)`: the zero-training ~0.80 combo, dataclass fields only
  (`inlier_count`, `best_to_second_score_ratio`, `near_tie_basin_count`, `confidence`), z-stats
  embedded from the 90 k dataset.
- `_record_next_anchor_reliability(estimates)`: blacklists a `next` whose own reliability is
  persistently low, **with the stall-relief the 2026-07-15 version lacked** (`max_chain` caps
  quarantines-without-promotion; per-anchor `stall_attempts`; counter + history reset on promotion).
- Wired into the update path and `_next_candidate_index` skip. Flag
  `--sequential_pair_reliability_quarantine` (+ threshold/min_history/bad_fraction/stall/max_chain),
  default OFF.

**Not yet done**: Injection B (evict bad `current`; gate the closure-reject veto on `current` being
reliable), Injection C (downstream distrust + `stop_gate` defer-not-veto), CLI wiring, unit tests.

### 2.2 Capture subsystem (`code/reliability_capture.py` + `test_reliability_capture.py`)

Self-contained, non-perturbing capture for the Route-2 dataset (owned by us, not codex, per the
2026-07-21 decision that only we touch the runtime scripts). Implements codex's file organization:
`manifest.json` + `attempts.jsonl` (A per-attempt scalars + C temporal fields + GT labels) +
sharded `pointcloud_shards/*.npz` (B, fixed-size 1024/2048 always + full clouds on sampled events) +
`anchors/*.npz` + `rgbd/` (D, JPEG/uint16-PNG with NPZ fallback). Atomic temp→rename writes,
sha256 checksums, deterministic-8% + event-triggered sampling with `sampling_reason`/`_probability`,
append-only crash-safe logs, every write best-effort so I/O failure never enters the control loop.
**Standalone smoke test passes 14/14** (real JPEG/PNG encoding confirmed available in the runtime env).

**Not yet done**: `round_trip_eval.py` hooks (anchor-creation / per-attempt / stop-veto) behind
`--capture_reliability_dataset`, and the real-episode smoke test (gated on GPU — the 16 ep capture
run is using it).

### 2.3 Capture re-run script (`code/run_capture_reliability_16ep_20260721.sh`)

Byte-identical canonical config + `--capture_icp_replay_dataset`, `ONLY_EPISODES` = the 13 pinned ∪ 8
stop-decision = 16 episodes (7 scenes), fix OFF. Purpose: collect the raw clouds needed to answer,
offline, whether the below-pin anchors are registrable along the real trajectory (decides Route 1 vs
the vision/mapping wall) and to tune `reliability_quarantine_threshold`.

### 2.4 Offline counterfactual replay (`code/offline_counterfactual_replay.py`)

The Injection C / A/B offline replay that produced §1.7.

---

## 3. Current progress

| Item | Status |
|---|---|
| batch2 ground-truth failure diagnosis (§1.1–1.5) | ✅ done |
| Reliability-signal feasibility + ceiling (§1.6) | ✅ done (sibling folder) |
| Codex Route-2 assessment | ✅ done — copy correct, plan sound, independently confirms findings, correctly shadow-locked |
| Injection A core | ✅ implemented + `py_compile`, isolated, default-off |
| Injection B / C / CLI / unit tests | ⬜ next |
| Capture module | ✅ implemented + 14/14 standalone smoke test |
| Capture `round_trip_eval` hooks + real-episode smoke | ⬜ next (GPU-gated) |
| 16 ep capture re-run | ⏳ running (~10–20 h, detached) |

---

## 4. Current & next-step plan (sequenced; agreed)

1. **⏳ Now**: 16 ep capture re-run collects raw clouds for the 13 pinned + 8 stop-decision episodes.
2. **On completion → offline analysis**: (a) below-pin anchor registrability along the real trajectory
   → does un-sticking the pin even help, or is the home stretch degenerate too (vision wall)?
   (b) tune `reliability_quarantine_threshold` against ground truth.
3. **Finish the fix**: Injection B + C, CLI wiring, unit tests.
4. **Capture integration**: `round_trip_eval.py` hooks + real-episode smoke test (once GPU is free).
5. **Clean 100 ep A/B**: fix-OFF vs fix-ON, byte-identical otherwise, with the full capture on — this
   single run then both validates the fix (attributable return-rate delta) and feeds codex's model a
   large fresh dataset. **Do NOT enable an unvalidated fix in a 100 ep run before steps 2–4.**

**Division of labor**: we own all runtime/navigation code (the fix + the capture subsystem); codex owns
the Route-2 model in its isolated `navila-reliability-v1`. One deliberate reviewed integration merges
the validated fix + capture into live before the 100 ep A/B.

**Strategic note**: both routes converge on the same first step — an absolute per-reading reliability
signal (heuristic ~0.80 for Route 1, learned for Route 2). The fork (invest in point-cloud/vision to
break 0.84) should be decided against the measured return-rate gain from step 5, not in advance.

---

## 5. Data appendix (`data/`)

- `01_batch2_27ep_anchor_icp_failure_signals.txt` — per-episode anchor-identity + ICP + arbiter +
  stop-gate signal table (success vs fail).
- `02_per_anchor_icp_breakdown.txt` — bad-anchor localization per episode; pin-anchor quality.
- `03_pin_anchor_timecourse_H1_vs_H2.txt` — pin-anchor error vs true distance + diagnostics.
- `04_quarantine_firing_pos_vs_bearing.txt` — quarantine fired 0/13; position vs bearing disagreement.
- `05_offline_counterfactual_replay.txt` — Injection C 2/8; A/B needs capture.

Analysis scripts that produced these are in `investigations/2026-07-21-icp-reliability-signal/code/`
(`batch2.py`, `peranchor.py`, `lockin.py`, `whichlink.py`) plus `code/offline_counterfactual_replay.py`
here.
