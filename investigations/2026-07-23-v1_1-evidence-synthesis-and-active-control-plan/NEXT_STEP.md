# Next-step plan

## Stage 1 — combined 100ep, decision-complete shadow

Claude's finalized Route-1 controller remains the only real controller. Carry
the companion `2026-07-23-v1_1-control-readiness-shadow-handoff` framework into
the same run.

Before launch:

1. merge Route-1 changes into the archived candidate entry point;
2. run the hash and lock preflight in `runner/CLAUDE_RUNNER_ARGS.sh`;
3. freeze the 100 physical episode IDs and final merged source hashes;
4. keep raw ICP replay capture and both V1.1 shadow flags enabled;
5. permit only the already-declared infrastructure retry policy.

During the run, V1.1 computes the exact candidate set that it would forward
before `RouteMemoryAgent`, but enforcement, identity override, and controller
effects remain locked false. Oracle truth is attached only after scoring and
policy evaluation.

After the run, execute the fixed order in `CONTROL_READINESS_PROTOCOL.md`.
The readiness scorer must see all 100 completion manifests, all shadow logs,
and independently rebuilt offline row predictions.

## Stage 2 — mechanical decision

Only a single result permits activation:

- all integrity gates pass;
- at least 40 physical episodes contain scoreable return decisions;
- online/offline keys, labels, probabilities, and trusted flags agree exactly;
- forwarded-current coverage is at least 35%;
- current pose-bad block recall is at least 70%;
- the frozen upper risk bounds pass;
- episode availability and defer-streak gates pass;
- no qualifying scene exceeds the frozen pose-bad risk limit.

If a gate fails, interpret the specific branch:

- capture/parity failure: repair instrumentation and rerun; the sound rows
  remain evidence but cannot produce formal acceptance;
- risk failure: keep V1.1 shadow and do not tune on this same batch;
- availability/streak failure with good risk: the model is useful but the hard
  filter policy is unsuitable; version a new consumer and gather new
  prospective evidence;
- scene failure: do not hide it inside a pooled average; constrain deployment
  scope or add the missing verification mechanism.

## Stage 3 — exact active integration

After a full Stage-2 pass, implement the already observed policy at one hook:
after raw sequential-pair candidates are scored and before they are returned
to `RouteMemoryAgent.update_relocalization`.

The active mapping is unchanged from shadow:

- untrusted/missing current: forward no relocalization candidate;
- trusted current plus untrusted/missing next: forward current only;
- trusted current plus trusted next: forward both unchanged;
- never substitute next for current;
- never edit a pose or probability.

Infrastructure/model failure is fail-open for that attempt, disables V1.1
enforcement for the rest of the episode, emits a high-severity event, and
fails acceptance. Ten consecutive full defers produce a warning; 30 disable
enforcement for the episode and fail acceptance.

## Stage 4 — 10ep guarded active canary

This is the first run in which V1.1 genuinely participates in control. It is
required because shadow logs cannot reveal integration-only state mutation,
deadlock, or recovery behavior.

Acceptance requires 10/10 valid completions, exact executed/logged filtering,
zero model/policy exceptions, zero state or identity violations, zero
30-attempt starvation fallback, no new adapter-attributable stuck/crash
condition, and a working kill switch.

Ten episodes are enough for integration safety checking, not for a navigation
benefit claim.

## Stage 5 — next 100ep is active A/B

If the guarded canary passes, the following 100ep experiment should no longer
be pure shadow. Predeclare a randomized or paired baseline/active A/B:

- the baseline arm runs the frozen Route-1 path;
- the active arm runs the exact frozen V1.1 filter;
- both arms use the same eligible cohort and infrastructure policy;
- primary endpoint is round-trip success;
- safety endpoints include bad ICP admitted, good ICP deferred, starvation,
  false promotion, forced-stop errors, and enforcement fallback;
- analysis clusters by physical episode and scene;
- no threshold or policy changes after outcomes begin.

This is the experiment that can estimate causal navigation value. Visual
rotation verification should continue in parallel because V1.1 does not solve
the confidently-wrong symmetric-basin root cause.

