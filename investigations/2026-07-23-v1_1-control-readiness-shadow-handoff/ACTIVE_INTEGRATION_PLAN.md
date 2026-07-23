# Active integration plan after a passing shadow cohort

## Integration point

The active adapter belongs immediately after
`sequential_pair_anchor_relocalization` produces the raw current/next
candidates and after V1.1 scores their copied diagnostics, but before the
candidate list is returned to `RouteMemoryAgent.update_relocalization`.

It must not be inserted after `_select_sequential_pair_relocalization`, because
selection can already update promotion/evidence state. It must not gate a
closure/fusion output using a score calculated on a different raw pose.

## Exact active behavior

Apply the already-logged `forwarded_anchor_indices` mapping:

- current missing/untrusted: return no relocalization candidate for that
  attempt;
- current trusted, next missing/untrusted: return current only;
- current and next trusted: return both unchanged;
- never promote/switch to next merely because next has lower predicted risk;
- never modify a candidate pose or probability.

When no candidate is forwarded, the existing controller receives the same
semantic result as an ordinary no-relocalization update. Existing motion and
VLM behavior continue; the model does not invent a replacement pose.

## Runtime failure behavior

For a model exception, malformed output, or non-finite probability:

1. bypass the V1.1 filter for that attempt and preserve baseline controller
   behavior;
2. emit a high-severity activation fault;
3. disable V1.1 enforcement for the rest of that episode;
4. fail the guarded active canary acceptance gate.

This prevents a model infrastructure fault from immobilizing the robot while
also preventing the fault from being silently accepted.

## Starvation guard

The active adapter counts consecutive attempts with no forwarded current.

- At 10 attempts: emit a warning and expose the condition in telemetry.
- At 30 attempts: disable V1.1 enforcement for the rest of the episode and
  fall back to baseline behavior.
- Any 30-attempt fallback fails the guarded active canary.

The guard is a runtime safety fallback, not permission to weaken or tune the
frozen thresholds.

## Required 10-episode guarded active canary

Run after, and only after, every 100-episode control-readiness gate passes.

Acceptance requires:

- 10/10 processes complete with valid provenance;
- zero model/policy exceptions and non-finite outputs;
- zero truth/model linkage or state-reset errors;
- zero identity override;
- zero 30-attempt starvation fallback;
- no newly introduced controller crash or stuck condition attributable to the
  adapter;
- logged candidates exactly equal the filter plan on every attempt;
- a kill switch can disable enforcement without changing the frozen baseline
  path.

The canary is active, so its navigation outcome is descriptive model evidence,
but ten episodes are too small for a final benefit claim.

## Following 100-episode experiment

If the guarded canary passes, do not run another pure shadow cohort. Run a
predeclared active A/B:

- same eligible episode cohort and infrastructure policy;
- randomized or paired baseline and active arms;
- active arm uses the exact frozen filter;
- primary endpoint: round-trip success;
- safety endpoints: bad ICP admitted, good ICP deferred, update starvation,
  false promotion, forced-stop errors, and enforcement fallback;
- cluster analysis by physical episode and scene;
- no threshold or policy change after outcomes begin.

The model genuinely participates in the active arm. A baseline arm is still
necessary to establish causal navigation benefit.

## Scope boundary

This reliability layer cannot resolve rotational symmetry when a wrong ICP
basin looks geometrically clean. It can suppress many bad readings and prevent
them from reaching irreversible consumers, but visual rotation verification
remains necessary for the confidently-wrong root cause.

