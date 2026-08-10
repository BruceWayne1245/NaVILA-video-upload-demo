# Anchor V3 self-driven shadow: belief never advances past its starting pair (2026-08-10/11)

## Context

Found incidentally while analyzing Anchor V3's shadow performance in the
same three episodes used for
[../2026-08-10-anchor0-landmark/FINDINGS.md](../2026-08-10-anchor0-landmark/FINDINGS.md)
(ep386, ep95, ep680), all launched with
`--anchor_v3_shadow --anchor_v3_shadow_self_driven` (see
`--anchor_v3_shadow_self_driven`'s own argparse help in `round_trip_eval.py`:
"Instead of relocalizing against sequential_pair's real requested_pair ...
V3 relocalizes against its OWN previous belief -- exercising the full
pair-selection feedback loop an active integration would have"). This is a
different, more serious problem than
[../2026-08-08-anchor-v3/LIVE_SHADOW_SMOKE_TEST_20260809.md](../2026-08-08-anchor-v3/LIVE_SHADOW_SMOKE_TEST_20260809.md)'s
"sustained ABSTAIN once anchor 0 enters the candidate pool" finding --
that finding was from **non**-self-driven (passive, ground-truth-following)
shadow runs and remains valid for that mode. These three self-driven
episodes barely exercise that finding at all, for the reason below.

## Finding: self-driven belief is frozen at its initial pair for the entire episode, in 3/3 episodes

Grouping each episode's `anchor_v3_shadow.jsonl` by `v3_queried_pair` (the
pair V3 is actually being asked to relocalize against in self-driven mode,
as opposed to `requested_pair`, the real system's ground-truth pair) shows
it never changes value even once, across every episode tested:

| episode | `v3_queried_pair` (constant, entire episode) | real `requested_pair` range over the episode | decision counts | `promote` actions |
|---|---|---|---|---|
| ep386 | `(4, 3)`, all 414 attempts | advances `(4,3) -> (3,2) -> (2,1) -> (1,0) -> (0,)` | rebase 1 / keep 201 / abstain 212 | **0** |
| ep95 | `(17, 16)`, all 202 attempts | advances `(17,16) -> ... -> (7,6)` (10 anchors of real progress) | rebase 1 / keep 81 / abstain 120 | **0** |
| ep680 | `(20, 19)`, all 68 attempts | advances `(20,19) -> ... -> (12,11)` | rebase 1 / keep 67 (conf 0.96-0.99 throughout) | **0** |

Across all 3 episodes combined (684 decisions), **`promote` -- the action
that would advance the believed pair forward -- never fires once.**
ep680 is the starkest case: the model reports 0.96-0.99 confidence on
"keep, still at (20,19)" for 67 consecutive attempts while the real system
has already progressed 8 anchor-pairs further along (to (12,11)) -- this is
confidently wrong in the most literal sense, not a calibration/threshold
issue.

## Root cause: a wiring bug in the self-driven query, not a trained-model limitation

Compare the two relocalization calls in `_sequential_pair_relocalizer_with_v11_shadow`:

```python
# Real (non-self-driven) path: gets the current pair PLUS forward-looking probes
sequential_pair_anchor_relocalization(descriptor, *requested_anchors,
    additional_anchors=route_agent.sequential_probe_anchors(), ...)

# Self-driven path: gets ONLY its own believed pair, nothing else
sequential_pair_anchor_relocalization(descriptor, believed_current_obj, believed_next_obj,
    additional_anchors=(), ...)   # <-- always empty
```

`AnchorV3OnlineAdapter.observe_attempt` (`anchor_v3/online_adapter.py`)
selects `current_anchor`/`next_anchor` by indexing into
`candidate_indices` -- the list of anchors actually offered as candidates
this attempt (`pred_current_pos, pred_next_pos = divmod(pair_logits.argmax(),
candidates_dim)`, then `candidate_indices[pred_current_pos]`). **The model
can only ever select an anchor that was included in the candidate list it
was shown.** Because the self-driven path always sets `additional_anchors=()`,
every attempt only ever offers the model its own current 2 believed
anchors as candidates -- there is structurally no third (forward) anchor
for it to ever select, regardless of what the `action` head outputs or how
confident the model is that it should move on. "Promote" cannot occur
because there is nothing to promote *to*.

This is a **mechanical/wiring problem in how the self-driven shadow harness
was set up**, not evidence that the trained Anchor V3 model itself is
incapable of tracking progress -- the same model, when given the real
`requested_pair` plus probe anchors (non-self-driven mode, as in
`LIVE_SHADOW_SMOKE_TEST_20260809.md`), does track current/next correctly
through multiple pair transitions. Self-driven mode as currently wired
cannot exercise that capability at all.

## Implication for the 08-09 near-anchor-0 finding

Because self-driven belief never moved in any of these 3 episodes, none of
them meaningfully tested V3's behavior near anchor 0 in self-driven mode --
ep386's belief stayed at `(4,3)` the whole time even though the real system
reached `(1,0)` and then `(0,)`. The 08-09
`LIVE_SHADOW_SMOKE_TEST_20260809.md` finding ("sustained ABSTAIN once
anchor 0 enters the candidate pool") was from non-self-driven runs and is
unaffected by this -- it remains the correct read of *that* mode. This is a
separate, additional problem specific to `--anchor_v3_shadow_self_driven`.

## Status / next steps

Not fixed this session -- pure analysis, no code changed. If self-driven
shadow data is meant to be informative about V3's real promotion behavior
going forward (i.e. "what would happen if V3 actually drove decisions"),
the self-driven query needs to also pass genuine forward-looking candidates
(e.g. `route_agent.sequential_probe_anchors()`, or an equivalent derived
from the believed pair) instead of `additional_anchors=()`, so the model
has something to promote to. Until that's fixed, self-driven shadow data
from any episode should be treated as **not informative about V3's ability
to advance its own tracking** -- it can only ever demonstrate `keep` vs
`abstain` on a fixed pair chosen once at the start of the episode.

**Safety boundary maintained:** this is a shadow-only diagnostic path
(`--anchor_v3_shadow`, `--anchor_v3_shadow_self_driven`); nothing here
reads from or writes to any real decision (`route_relocalization_diagnostics`,
`v11_shadow_session`, promotion, stop_gate, hint_arbiter all remain
untouched by this code path either way).
