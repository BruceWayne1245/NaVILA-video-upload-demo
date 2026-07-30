# Runtime snapshot at 2026-07-30 handoff

## Current state

- Last service:
  `navila-unified-shadow50-retry1-20260730.service`
- Started: 2026-07-30 11:32:48 BST
- Ended: 2026-07-30 11:33:28 BST
- Final state: failed, exit status 1
- Valid trajectories: 0
- Scored experimental episodes: 0
- ep670 replication result: unavailable
- fresh49 started: no
- Active valid unified batch at handoff: no

## Attempt 0

The VLM process failed during checkpoint startup before Isaac or a trajectory
started.  It is infrastructure audit only.

## Retry1

Preflight passed and the VLM server became ready.  The evaluator then failed
before capture creation because the Anchor module was placed under a second
`reliability` package root while the evaluator had already imported the
established V1.1 package.

The batch driver reported an episode exit code of zero, but no result
directory/capture completion artifact existed.  The outer integrity gate
raised:

```text
FileNotFoundError: .../capture_completion.json
```

and correctly prevented the fresh cohort from launching.

## Blocker

Resolve the package namespace collision with a unique Anchor runtime package
or explicit file-backed import, and make evaluator failure propagate through
the driver.  Keep all experiment inputs frozen.
