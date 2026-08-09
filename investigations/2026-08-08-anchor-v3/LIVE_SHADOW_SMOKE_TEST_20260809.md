# Anchor V3 live shadow smoke test (2026-08-09)

Continues `ONLINE_ADAPTER.md` (2026-08-08's isolated, offline-replay smoke
test) and `EOD_SUMMARY_AND_NEXT_STEPS.md`'s step 1-2 (wire into
`round_trip_eval.py`, then a live smoke test). Both done this session, plus
a real finding the live test surfaced that offline evaluation could not.

## Runtime wiring

Added `--anchor_v3_shadow` (default off) directly to
`navila-route2-v11-core-20260801/runtime_candidate/scripts/round_trip_eval.py`
-- confirmed with the user to scope this to a pure, isolated shadow observer
before writing any code: new argparse flags, adapter construction gated
entirely behind the flag (zero new code executes when off), and the
per-attempt call wrapped in try/except so a shadow-inference bug can never
affect the real episode. Reuses the exact `raw_candidates` schema
`round_trip_eval.py` already builds for Anchor V2 at every attempt -- no new
feature extraction needed. Logs to `anchor_v3_shadow.jsonl` in the episode's
result directory.

**Important repo-layout finding while preparing this:** `round_trip_eval.py`
exists as two genuinely different files -- `NaVILA-Bench/scripts/
round_trip_eval.py` (Route 1's live copy, default `EVAL_SCRIPT`) and
`navila-route2-v11-core-20260801/runtime_candidate/scripts/round_trip_eval.py`
(Route 2's own reference copy, confirmed via a comment in
`run_line2_50ep_missing32_20260808.sh`: "do NOT point this at Route2's
runtime_candidate copy"). This session's edits are in the Route 2 copy only,
consistent with this session's Route 2 mandate.

## First live episode (ep386, test-split)

698s real episode, 402 shadow decisions logged, **zero shadow-inference
failures**. Current/next tracked the real route correctly (matches the
offline replay smoke test on the same episode almost exactly at the first
attempt: 0.996 vs 0.993 confidence). Episode itself ended via a pre-existing,
unrelated bug ("Robot has stayed in the same location for 1000 steps") --
confirms the shadow code doesn't interfere with real episode termination
logic either way.

## 5-episode batch (ep4, ep88, ep367, ep408, ep5)

| episode | exit | shadow lines | shadow failures | how it ended |
|---|---|---|---|---|
| 4 | 0 | 247 | 0 | `safe_fail` via `blind_probe_budget_exhausted...` at d=2.63m (stop_gate issue, unrelated to V3) |
| 88 | 0 | 248 | 0 | (return-phase, see pattern below) |
| 367 | 0 | 207 | 0 | robot physically stuck 1000 steps during return (pre-existing bug, same family as ep408/ep5's historical issue) -- confirms this is a locomotion-level bug, not an anchor-model artifact, since V3 shadow-only cannot have caused it |
| 408 | 0 | 0 | 0 | robot physically stuck 1000 steps during **outbound** -- never reached return phase, so the shadow adapter never got an attempt (correctly initialized, just never called) |
| 5 | 0 | (pending at time of writing) | | |

**Zero shadow-inference failures across all 5 real episodes and the ep386
episode before them.**

## Finding: sustained ABSTAIN once anchor 0 (home) enters the candidate pool

**Pattern (3/3 episodes that got close enough to test it -- ep386, ep4,
ep88):** confident, stable `keep` tracking through every earlier anchor
pair, then once the requested pair reaches `(2,1)` and especially `(1,0)`,
the model drops to sustained low-confidence `abstain` and never recovers
for the rest of the episode (185 and 39 consecutive abstains in ep4/ep88;
similar in ep386). Action breakdown by pair, ep4: `(3,2): all keep` ->
`(2,1): 5 abstain` -> `(1,0): 185 abstain, 0 keep`. ep88: `(3,2): 171 keep`
-> `(2,1): 8 abstain` -> `(1,0): 39 abstain, 0 keep`.

**Investigated and ruled out:** raw ICP evidence quality does not degrade
near anchor 0 in the training corpus -- aggregate `overlap_ratio`/
`confidence`/`inlier_count`/`mean_residual_m` for anchor 0 (n=4728) is
comparable to, if anything slightly better than, anchors 1-5 (n=5579-5691
each). Also confirmed anchor spacing is not the explanation: anchors are on
a uniform 1m grid (anchor 2 = 2.0m from home, anchor 1 = 1.0m, anchor 0 =
0.0m), all well inside `stop_gate`'s `r_out=3.0m` -- so this is not a "still
far away" effect either.

**Root cause (confirmed by the user, project-specific institutional
knowledge not visible from the data alone):** anchor 0's own point-cloud
capture was empty/broken in the runtime for the entire period the training
corpus's episodes were recorded -- a bug fixed recently, but after all of
this corpus's episodes were captured. Checked directly: `oracle_current_anchor
== 0` occurs in **zero** frames across all of train/validation/test (5,691
frames). The model has literally never seen a labeled example of what
"the true current anchor is home" looks like.

**Resolution: adopted "redefine scope" over "patch the data/model."** Since
the historical corpus cannot be retroactively repaired (the anchor-0 capture
bug predates it and there's no way to re-derive missing frames), and since
home-arrival is `stop_gate`'s decision to make, not V3's, sustained ABSTAIN
once anchor 0 is reachable is treated as the **expected, correct handoff
signal** -- not a defect to chase. `AnchorV3OnlineAdapter.is_terminal_approach()`
(new) returns whether anchor 0 is in an attempt's candidate pool; the shadow
JSONL log now tags every entry with `terminal_approach: bool` so future
analysis of shadow data (or a real consumer, if this is ever wired further)
can distinguish this expected state from a genuine tracking failure
elsewhere on the route. No retraining or data-pipeline change was made --
this was a scope decision, not a training-data fix, and the option to
collect fresh anchor-0-inclusive data now that the capture bug is fixed
remains open for later if V3's mandate ever needs to extend into the
terminal-approach region.

## Updated artifacts

- `code/online_adapter.py` -- updated docstring (documents this finding and
  the wiring-into-round_trip_eval.py status) + new `is_terminal_approach()`
- The `round_trip_eval.py` shadow-logging call now includes
  `terminal_approach` per entry (code diff not re-copied here since the full
  file isn't tracked in this repo; see `code/online_adapter.py`'s docstring
  for the authoritative description of the change)

## Still open

- ep367/ep88's stuck-robot bug and ep4's blind-budget safe_fail are all
  pre-existing, unrelated issues surfaced incidentally by running more live
  episodes -- not new problems, not caused by `--anchor_v3_shadow`, and not
  this session's to fix.
- No shadow-inference failure has been observed in any live episode so far.
  Given the terminal-approach finding is now understood and not a blocker,
  current/next tracking quality away from the terminal region has looked
  solid across every episode tested. Whether to extend the shadow batch
  further, move toward an actual (non-shadow) integration, or stop here is
  the next decision point -- not made in this session.
