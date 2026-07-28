# Return-terminal evidence state machine

Date: 2026-07-28

## Outcome

The stop gate has been replaced in the isolated Route-2 anchor-support
candidate:

`/home/teambruce/navila-reliability-v1_1-anchor-support-recovery-20260728`

The implementation covers the failure mechanism found in episodes 19, 89, 95,
196, 205, 264, 276, 310 and 490.  It was launched in a two-episode Isaac Sim
smoke test on 2026-07-28; the results are recorded below.

The central invariant is:

> A VLM STOP is a proposal.  Only explicit positive terminal evidence may turn
> it into return success.

The old `deferred` pass-through no longer exists.  A decision other than
`accepted` or `forced` cannot end the return phase.

## Why the old gate failed

The previous gate read one `distance_to_start_m` scalar and treated it as a
complete terminal authority:

- low confidence and low-reliability readings returned `deferred`, but the
  caller left `_vlm_stop_requested=True`, so `deferred` was actually ACCEPT;
- high-confidence wrong/stale distance could veto a correct VLM STOP
  indefinitely;
- a veto injected ten steps of motion toward the bearing supplied by the same
  potentially wrong estimate;
- the gate did not distinguish rear/current support from forward/next
  guidance;
- only `forced` and `vetoed` passed through the Route-2 consumer guard, so a
  false `accepted` decision bypassed model trust entirely;
- Route-2 VLM-only mode disabled the complete stop gate and passed a VLM STOP
  directly through.

That combination caused the premature stops in ep19/95/196/205/264/276/310
and the repeated correct-stop veto loops in ep89/490.

## Implemented state machine

The states are:

1. `navigating`
2. `terminal_verify`
3. `terminal_blind`
4. `arrived`
5. `safe_fail`

### `navigating`

Normal route consumers may run.  A STOP proposal is classified using an
explicit distance interval rather than a point scalar.

Only fresh, Route-2-trusted raw evidence whose role is `next` has positive
numeric authority:

- two consecutive trusted-near readings plus two consecutive VLM STOP
  proposals may produce `accepted`;
- three consecutive trusted-near readings may produce `forced`;
- a definitely-outside interval may reject a premature STOP.

The direct-oracle evaluation source follows the same temporal confirmation
rule.

### `terminal_verify`

An unproven STOP is suppressed and replaced by a short zero-velocity hold.
Navigation hint injection, hint-action override and stuck recovery are paused.
The terminal gate itself remains active.

The hold lasts only two VLM-query cycles by default.  It is a decision barrier,
not a claim that stopping will make missing sensors recover.

### `terminal_blind`

If resampling still supplies no authority, the system enters bounded VLM-only
navigation:

- route-derived navigation consumers remain paused;
- the VLM receives an explicit instruction not to stop from route numbers;
- Route-2/A0/expanded-anchor probing continues;
- the gate keeps evaluating terminal evidence;
- the budget is eight VLM queries by default.

If a fresh trusted next reading returns, normal navigation resumes.  If no
terminal evidence returns before budget exhaustion, the result is
`safe_fail`, not success.

### `arrived`

The only accepted positive paths are:

- repeated VLM STOP plus repeated fresh trusted-next near evidence; or
- repeated VLM STOP plus repeated independent A0 RGB-D/LoFTR home-place
  confirmation.

### `safe_fail`

The evaluator commands zero velocity, marks
`return_terminal_safe_fail=true`, leaves `return_success=false`, logs the
failure reason and terminates the episode.

This is the unavoidable safety choice when ICP, Route-2, A0 RGB-D and the
last-trusted motion bound all fail to provide a terminal answer.

## Evidence authority matrix

| Evidence | Accept/force | Reject definitely-outside STOP |
|---|---:|---:|
| Fresh Route-2-trusted raw `next` | yes, after streak | yes |
| Direct oracle source | yes, after streak | yes |
| Fresh trusted one-hop geometry reconstruction | no | yes, with wider interval |
| Raw `current`/rear support | no | no |
| Multi-hop reconstruction | no | no |
| Evidence older than 25 return updates | no | no |
| Route-2-untrusted or missing assessment | no | no |
| VLM STOP alone | no | no |
| Repeated A0 RGB-D confirmation + repeated VLM STOP | yes | n/a |

The current anchor may be a correct rear support after the robot has already
passed it.  Therefore its identity or fixed route distance is never terminal
authority by itself.

## Distance interval and signal-loss handling

Fresh raw distance is represented as:

`[max(0, d - 0.35 m), d + 0.35 m]`

One-hop reconstruction adds another 0.50 m of uncertainty.

Whenever fresh trusted raw-next evidence is observed, the gate saves its
interval.  On later signal loss it expands the saved interval by the actual
travelled path length accumulated by `notify_sim_step`:

`[max(0, low - travelled), high + travelled]`

This envelope may disprove arrival if its lower bound remains above
`r_out`.  It can never prove arrival: movement direction is unknown, so the
upper expansion cannot safely collapse into a near claim.

Teleport frames clear the saved interval and all confirmation streaks.

## A0 visual confirmation

On an uncertain STOP, the evaluator runs the existing RGB-D LoFTR + 3-D RANSAC
relocalizer against only the saved A0 descriptor.  A positive sample requires:

- selected anchor A0;
- estimated A0 distance at most 1.5 m;
- RGB-D match confidence at least 0.45.

Two consecutive positive A0 samples and two consecutive VLM STOP proposals are
required.  No match is `unknown`, not a negative proof and not an acceptance.

This requires `--route_memory_capture_start_anchor_descriptor`, already part
of the Route-2 recovery design.

## Runtime wiring changes

`RelativeStartProgress` now records `estimate_role` as `next`, `current` or
`unknown`.  `RouteMemoryAgent._anchor_progress()` sets it from the actual
estimate source.

At every return VLM query the evaluator:

1. obtains progress for terminal safety even if navigation consumers are
   paused;
2. resolves Route-2 trust directly from the latest model assessment;
3. uses the source-anchor assessment for geometry reconstruction;
4. appends the terminal-state prompt when verification/blind navigation is
   active;
5. calls the gate regardless of Route-2 VLM-only state;
6. suppresses every STOP unless the decision is `accepted` or `forced`.

The legacy generic `forced_stop`/`vlm_stop_veto` consumer post-processing is no
longer the terminal authority.  The state machine enforces role, model trust,
provenance and freshness together before producing its decision.

## Recorded Active-50 counterfactual

`tools/replay_terminal_stop_gate_failures.py` replays the recorded STOP-query
rows and Route-2 assessments for the nine stop-related failures.  This is a
local decision replay, not a dynamics replay: after the first changed decision,
later historical positions are counterfactual.  Old logs also contain no A0
visual result, so the replay supplies no visual confirmation.

Results:

```text
new decisions: verifying=8, resume=20, safe_fail=2
unsafe outside-radius accepts: 0
authorized inside-radius resumes: 0

ep205 historical accepted -> new verifying
ep89  historical 60 vetoes -> bounded safe_fail on replayed query 9
ep490 historical 148 vetoes -> bounded safe_fail on replayed query 9
```

The two `safe_fail` results are the intended no-visual/no-fresh-signal outcome,
not a claim that those episodes should fail live.  A live A0 RGB-D match or
fresh trusted-next recovery may positively accept them before the budget ends.

## Verification

Targeted state-machine/Route-2 regression:

```text
59 passed
```

The new tests cover:

- repeated confirmation for accept and force;
- no authority from untrusted, stale or current/rear evidence;
- bounded reconstructed-distance rejection only;
- no authority from multi-hop reconstruction;
- A0 visual plus VLM positive confirmation;
- last-trusted motion-envelope expansion;
- teleport invalidation;
- VLM-only prompt behavior;
- bounded blind-state safe failure;
- live `estimate_role` wiring.

All changed Python modules pass `py_compile`.

The full isolated test run currently reports `127 passed, 3 failed`.  The
failures are pre-existing/environmental:

- unchanged active-scan test expects 9 seconds while the frozen policy emits
  12 seconds;
- two portable-artifact tests cannot unpickle a NumPy 2 artifact in the
  available NumPy 1 test environment (`numpy._core` missing).

## Required live validation

Before a larger batch:

1. run ep205 to confirm the old false `accepted` path becomes verification;
2. run ep89 and ep490 to confirm correct inside-radius STOP is no longer
   repeatedly vetoed;
3. record A0 LoFTR availability, false-positive rate and confirmation latency;
4. run known successful `deferred` cases ep420/489 to confirm the positive A0
   or trusted-next path completes quickly;
5. verify `safe_fail` is reported as failure by all downstream aggregators;
6. only then run the nine-episode stop cohort and a broader canary.

## 2026-07-28 smoke result

The exact active candidate, two-episode approval, locked-hash runner and full
smoke report are in:

`/home/teambruce/navila-reliability-v1_1-anchor-support-recovery-20260728/experiments/2026-07-28-anchor-stop-smoke/README.md`

### ep205: complete pass

- evaluator exit code 0;
- completion validator passed;
- outbound, return and round trip all succeeded;
- final true distance to start: 0.8420 m;
- 46 stop-gate decisions: 45 `pass`, one final `forced`;
- the gate remained `navigating/pass` through the historical premature-stop
  region and forced arrival only after a fresh trusted raw-next near streak;
- live recovery exercised `next_only`, `reconstruct_next` and
  `pair_recovery`, confirming that the four changes are in the active call
  chain.

### ep490: invalid/incomplete

ep490 entered return and logged normal gate/recovery decisions through step
2451, then Isaac/Kit closed the application before measurement and completion
were written.  There was no Python traceback and the child reported exit code
0, but `capture_completion.json` is absent.  The validator therefore failed,
as required.

This attempt is not evidence for or against terminal correctness because it
did not reach the historical stale-stop region.  No larger batch should be
started until ep490 or ep89 completes and demonstrates either positive
trusted-next/A0 arrival or bounded terminal `safe_fail`.
