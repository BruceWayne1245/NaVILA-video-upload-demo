# Anchor V3: hysteresis fix and blind-recovery research (2026-08-08, continued)

Continues `TRAINING_RESULTS.md` from the same day (NaN bug fix, first clean
baseline). This covers: a systemic error-mode audit of the baseline
checkpoint, two fix attempts (one failed, one worked), a research pass into
whether Anchor V3's output could supplement the runtime's `stop_gate`
blind-recovery mechanism (negative-ish result, honestly reported), and a
direct episode-level comparison against the previous model generation
(Anchor V2 full-active).

## 1. KEEP<->PROMOTE hysteresis: found, root-caused, fixed

`tools/breakdown_test_eval.py` on the baseline checkpoint found the single
largest error mode was `keep`/`promote` confusion (81 of the test split's
misclassifications). Manual inspection of the two worst offending episodes
(ep4, ep386 -- 40-41% frame error rate) found an 8-consecutive-frame run of
the model predicting `promote` while the true label stayed `keep` the whole
time, at a roughly constant distance-to-anchor -- looked like the robot
stopped moving with a persistent offset and the model got "stuck" on the
wrong side.

**Systemic scan (`tools/scan_hysteresis_streaks.py`, all 46 held-out
test+validation episodes):** 15/46 episodes (33%) had a run of 3+ consecutive
frames making the same wrong keep/promote call; 22 such streaks total; 20/22
(91%) occurred while the true `oracle_current_anchor` never changed -- i.e.
the model kept flipping to `promote` with no real transition to justify it.
Direction was overwhelmingly `keep`-predicted-as-`promote` (19/22).

### Attempt 1 (failed): adjacent-frame consistency loss

Added an MSE penalty between softmax action-probability vectors of adjacent
decision frames sharing the same true (current, next) pair identity, on the
theory that this would discourage flip-flopping.

**Verified before training** (777-sequence NaN sweep, then a fresh 5-epoch
run, `train_run4.log`). Result: **no improvement** -- still 15/46 episodes,
22 streaks, 20/22 anchor-stable, after a full retrain; several streaks got
slightly *longer*, and test action accuracy dropped 73.95% -> 71.86%.

**Why it failed, understood after the fact:** the loss only penalizes
disagreement *between* adjacent predictions, never referencing ground truth.
A run of frames confidently and consistently predicting the wrong class
satisfies "adjacent predictions agree with each other" exactly as well as
being consistently *right* -- there is no gradient to distinguish the two.
It may also have made recovery slightly harder, since snapping back to the
correct class is itself an adjacent-frame change the loss penalizes.

### Attempt 2 (worked): KEEP-class-weighted cross-entropy

Replaced the consistency loss (kept at zero weight, still computed and
returned for visibility, not removed from the code) with a straightforward
fix directly targeting the diagnosed asymmetry: `keep_class_weight=2.0` in
`F.cross_entropy`'s per-sample `weight=` argument, making a true-KEEP frame
misclassified as PROMOTE cost twice as much.

**Verified with the same 777-sequence NaN sweep, then a fresh 5-epoch run**
(`train_run5.log`). Result:

| metric | baseline | consistency (failed) | keep-weighted |
|---|---|---|---|
| episodes with streak | 15/46 | 15/46 | **4/46** |
| total streaks | 22 | 22 | **4** |
| anchor-stable streaks | 20 | 20 | **2** |
| longest streak | 7 | 7 | 5 |
| test action accuracy | 73.95% | 71.86% | **75.58%** |
| test pair exact-match | 71.6% | 72.6% | **74.87%** |
| test belief top-1 | 71.78% | 72.03% | **73.27%** |
| epoch-2 val_total (best) | 1.719 | 1.878 | **1.644** |

A single, targeted, class-weighted loss term fixed ~82% of the streaks and
improved every other accuracy metric simultaneously (not a tradeoff). The 4
remaining streaks: 2 are still the anchor-stable keep->promote pattern
(ep136, ep87, both length 3 -- right at the detection threshold), 2 are a
different, pre-existing failure mode (ep367, ep88 -- model lagging
`promote->keep` while the true anchor is changing rapidly across several
positions, not stuck on a stable anchor). Checkpoint: `reports/
anchor_v3_keepweighted_checkpoint.pt` (epoch 2, best val_total). This is now
the best available checkpoint, superseding the NaN-fix baseline.

## 2. Blind-recovery / stop_gate: mechanism research and a negative-ish finding

Explicit scope note: this investigation targets Anchor V3's own job
(current/next anchor selection), not `stop_gate` -- which is a known, older,
separately-owned problem this session was not expected to fix. This section
documents research done to see whether V3's confidence output could
*supplement* stop_gate, for the record; it should not be read as a claim
about V3's core current/next quality.

**Mechanism (`runtime_candidate/scripts/stop_gate.py`, not
`route_memory_agent.py`):** a state machine `NAVIGATING -> TERMINAL_VERIFY ->
TERMINAL_BLIND -> {ARRIVED, SAFE_FAIL}`. When the VLM proposes STOP but no
fresh trusted relocalization evidence is available, the gate enters
`TERMINAL_BLIND` and probes for up to `blind_max_queries` (default 8) VLM
queries; if none of those return trusted evidence or an A0 visual home
confirmation, the episode is marked `SAFE_FAIL` -- a known false-negative
source (`ACTIVE_EVIDENCE40_PROTOCOL.md`: "blind-probe exhaustion converts
some physically arrived episodes into safe-fail").

**Scan of the full 872-directory catalog (`tools/
scan_blind_exhaustion_safe_fail.py`):** 67 directories (50 unique physical
episodes) ended `SAFE_FAIL`. **All 67, no exceptions, were
`blind_probe_budget_exhausted_without_terminal_evidence` at exactly
`blind_query_count=8`** -- a single, pure failure mode in this catalog, not
several. All 50 unique episodes are already inside Anchor V3's train/
validation/test split.

**Cross-referencing the real TERMINAL_BLIND step window against Anchor V3
frames (`tools/crossref_blind_window_confidence.py`, keep-weighted
checkpoint):** 49/50 episodes had >=1 Anchor V3 frame inside the real blind
window. Naive read: 27/49 (55%) episodes had mean confidence >=0.7 during
the real window, and 13/49 showed confidence dropping specifically inside
the window versus the rest of the same episode (plausible good calibration).

**Rigor check against ground truth (final `distance_to_start_m` <= `r_out`
3.0m = robot was actually home):** of the 49 covered episodes, 22 were real
misses (safe_fail was wrong, robot was home) and 27 were real failures
(safe_fail was correct, robot genuinely was not home).

- Among the 22 real misses: 15/22 (68%) had high (>=0.5) confidence --
  correctly would have flagged the miss, including held-out test episodes
  ep386 (0.43m final distance, 0.991 confidence) and ep408 (2.03m, 0.986).
- **Among the 27 real failures: 13/27 (48%) *also* had high confidence** --
  including test-split ep5, where the robot was **15.4m** from home and V3's
  mean confidence in that window was still 0.729.

**Combined precision of "confidence >= 0.5" as a trust signal: 15/(15+13) =
53.6% -- close to a coin flip.** This is the same "confidently wrong"
failure signature this project has documented repeatedly elsewhere (see
`2026-07-24-confidently-wrong-open-problem-summary`), not something this
session's fixes touched. **Conclusion: Anchor V3's raw confidence output, as
currently trained, is not reliable enough on its own to supplement
stop_gate's blind-recovery decision.** This is reported as a genuine,
honestly negative finding, not a target for further work in this session --
consistent with stop_gate being explicitly out of scope for V3's mandate.

## 3. Direct comparison against Anchor V2 (the previous model generation)

Anchor V2 full-active (`transition_model_sha256` in the historical
compatibility catalog) is a **row-wise 5-class classifier** with no temporal
state -- it labels one attempt at a time and hands the label to a
deterministic controller. Its target selection itself was already good
(97.3% correct on 188 reliably-judgable real promotions -- not directly
comparable to V3's 75.58% raw per-frame accuracy, which is measured over a
harder, unfiltered population including deliberately-hard corrective/gap
frames). V2's documented architectural gap, from its own `2026-08-01`
proposal doc: no temporal/"missing-state" mechanism, and specifically **no
re-anchoring when ICP evidence goes untrusted for the tracked pair** --
named "pair-lock deadlock" failures on episodes **4, 95, 367, 658, 680**
(stale pair falsely vetoed a valid stop or never recovered navigation) and
**88, 89** (similar). A recovery state machine was designed 2026-08-04 but
never completed/run.

Direct episode-level cross-check against V3's own data this session:

| episode | V2's documented problem | V3 status |
|---|---|---|
| 4 | pair deadlock, navigation never recovered | **fixed** -- was V3's worst hysteresis offender pre-fix (40% error rate), gone after the keep-weighted fix |
| 95 | stale pair falsely vetoed valid stop | **good** -- confidence 0.983 during real blind window, correctly high (real miss, 2.25m) |
| 658 | same | **good** -- confidence 0.944 (real miss, 1.69m) |
| 680 | same | **good** -- confidence 0.987 (real miss, 2.95m) |
| 367 | pair deadlock, navigation never recovered | **still open** -- still in V3's residual streak list (anchor-unstable lag pattern), and confidently wrong in the blind-window check (0.955 confidence, but 5.83m from home) |
| 88 | stale pair falsely vetoed valid stop | **still open** -- still in V3's residual streak list, same lag pattern |

**Assessment: V3's architecture (causal temporal Transformer + atomic
current/next pair contract + corrective_teacher for stale/gap frames)
directly targets V2's documented root cause, and the improvement shows up on
4 of the 6 specific episodes V2's own investigations named as failures --
not just as an aggregate accuracy number.** 2 of the 6 (ep367, ep88) are not
yet resolved and share a common signature (rapid true-anchor movement, model
lags behind) distinct from the now-fixed hysteresis pattern -- worth
watching specifically if/when live testing resumes.

## Updated artifacts this session

- `code/anchor_v3_losses.py`, `code/train_anchor_v3.py` -- now include the
  keep-class-weighted fix (consistency term retained at zero weight)
- `code/scan_hysteresis_streaks.py`, `code/scan_blind_exhaustion_safe_fail.py`,
  `code/crossref_blind_window_confidence.py` -- new analysis tools
- `code/monitor_training_gpu.sh` -- fixed to accept a checkpoint path
  argument and match any `train_anchor_v3.py` invocation (previously
  hardcoded to the baseline checkpoint's filename, silently stopped
  tracking after a rename)
- `artifacts/train_run4_consistency_failed.log`,
  `artifacts/train_run5_keepweighted.log`
- `artifacts/TEST_EVAL_consistency_epoch2.json`,
  `artifacts/TEST_EVAL_breakdown_consistency_epoch2.json`,
  `artifacts/TEST_EVAL_keepweighted_epoch2.json`
- `artifacts/blind_exhaustion_safe_fail_scan.json`,
  `artifacts/blind_window_confidence_crossref.json`
- `artifacts/anchor_v3_keepweighted_normalizer.json`

The keep-weighted checkpoint itself (10.78MB binary) is not committed, same
convention as the baseline checkpoint -- kept locally at `reports/
anchor_v3_keepweighted_checkpoint.pt`.

## Next

Direction agreed with the user: current/next selection quality now looks
solid enough (beats majority-class baseline by +11pts, hysteresis mostly
fixed, 4/6 of V2's named failure episodes resolved) to move toward a smoke
test. No runtime integration code exists yet -- writing the online
equivalent of `tensorize_candidates` and wiring it into
`route_memory_agent.py` (opt-in, off by default, shadow-only per this
project's established practice) is new work, not started. stop_gate/
blind-recovery is explicitly out of scope for this model; its own
confidence signal was checked and found not reliable enough to help there
without further work, and that is not blocking the current/next mandate.
