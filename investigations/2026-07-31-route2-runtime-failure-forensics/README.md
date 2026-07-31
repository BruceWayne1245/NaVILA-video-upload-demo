# Route 2 — 2026-07-31 runtime failure forensics and guarded queue repair

## Scope and authority

This investigation records the Route 2 Unified Shadow50 runtime failures
observed on 2026-07-30/31, the GPU cleanup, the driver/orchestrator repairs,
and the guarded handoff behind the currently running Route 1 30-episode batch.
It is an operational/runtime investigation only: no Route 2 experiment member,
model, threshold, manifest, or consumer authority was changed.

The authoritative project state remains the latest GitHub `README.md` and
investigations. Local runtime files are operational artifacts and must not be
treated as experiment authority unless their hashes and provenance are
explicitly recorded.

## Executive conclusion

The repeated zero-result failures were primarily a **runner/lifecycle defect**,
not evidence that the selected 50-episode cohort was intrinsically invalid.
The added 900-second evaluator-startup watchdog treated delayed/buffered
episode output as proof that an episode had not started. It therefore killed
episodes that were still running normally. Because the old launcher did not
hold exclusive locks or reliably reap descendants, a failed-looking wrapper
could also leave evaluator/VLM descendants alive and consume the GPU. A later
episode could then be started while the previous process tree still existed.

The repaired driver removes that false liveness test, uses an outer episode
timeout as the only runtime bound, snapshots the exact driver before launch,
and cleans the complete process tree on exit. The repaired queue now recognizes
the actual Route 1 tag in use and waits for both Route 1 completion and a nearly
empty GPU before starting Route 2.

At the time of this record, Route 1 was still active (`promotion_shadow_reliable30v3_20260731`,
episode 4), so the repaired 50-episode run was queued but had not started.

## What failed and why no episode was valid

### 1. The 900-second startup watchdog was an invalid liveness signal

The watchdog required evaluator log growth and/or a result-directory change
within 900 seconds. Historical successful episodes show that simulator/VLM
output is buffered and may only become visible in the redirected log after the
episode exits. A quiet log therefore meant “output has not flushed”, not “the
episode is stuck”.

The watchdog killed in-progress episodes before they could write a valid
trajectory or completion record. This explains the repeated runs with no
effective episodes: the process was terminated by the runner, not rejected by
the Route 2 policy or by the selected episode cohort.

### 2. Active code was changed while a batch was running

The retry4 driver was edited in place while a previous invocation was still
executing. The running shell could consequently observe a mixed/partial script
state. The observed `line 459: 0.000000: command not found` and the subsequent
unexpected episode restart are consistent with this unsafe deployment pattern.

An episode must never execute a mutable source file that is being edited.

### 3. Wrapper failure did not imply process-tree termination

The old cleanup path primarily targeted the wrapper PID/process group. Once a
wrapper had already exited, evaluator descendants could remain orphaned. A
process-group kill alone then missed them. Direct inspection found dozens of
orphan evaluator processes carrying the unique retry4 result suffix; they held
VLM/Isaac resources after the batch had apparently failed.

This is why a later episode could be launched even though the GPU was still
occupied: the launcher tracked the wrapper state, not the complete descendant
tree.

## Repairs implemented

### Manifest batch driver

- Removed the evaluator startup watchdog entirely. No log-size, log-mtime, or
  result-directory-growth check is used as an in-progress signal.
- Kept the bounded outer episode timeout (`7200s`, with `300s` kill-after) and
  waits for the evaluator process to exit.
- Sets `PYTHONUNBUFFERED=1` for the evaluator, while still treating output only
  as diagnostics rather than as a liveness contract.
- Captures the evaluator/VLM process group immediately after launch.
- On `EXIT`, `INT`, or `TERM`, recursively enumerates descendants and sends
  `TERM`, then `KILL` if necessary; cleanup also works when the wrapper PID has
  already disappeared but its captured process group remains.
- Adds a driver-wide `flock` so two manifest drivers cannot run concurrently.
- Places the former unreachable legacy episode block inside a non-executable
  heredoc guard so it cannot accidentally launch a second batch.

### Unified50 orchestrator

- Adds an orchestrator-wide `flock`.
- Requires the expected driver SHA-256 before launch. The current repaired
  driver SHA-256 is:

  `887fec7ad8296ec8b6c19af7e8a4639d2cdfa2d3ca7cf03fde46f01133ef80bb`

- Creates an immutable per-run driver snapshot, verifies its SHA-256, and
  invokes that snapshot instead of a mutable working file.
- Checks for matching evaluator processes after the driver exits, so a false
  clean exit cannot silently leave a tagged child process behind.

### Route 1 → Route 2 queue

- Adds a queue-worker `flock` to prevent duplicate queued Route 2 workers.
- Recognizes the actual Route 1 tag used on 2026-07-31:

  `promotion_shadow_reliable30v3_20260731`

  Older unseen30 tags remain recognized for compatibility.
- Waits until all matching Route 1 units and evaluator processes have exited.
- Requires at least `22,000 MiB` free GPU memory before starting Route 2. This
  intentionally prevents a second VLM/Isaac workload from starting during a
  transient between-episode gap.

## Verification performed

- `bash -n` passed for the queue, orchestrator, and manifest driver.
- Frozen-cohort static preflight passed: `49 fresh + ep670 replication`.
- GPU preflight passed: `49 fresh + ep670, 8 scenes, all consumers off`.
- The queue was launched detached and verified waiting while Route 1 episode 4
  was active.
- At verification, Route 1 held approximately `10,110 MiB`; free GPU memory was
  approximately `13,758 MiB`; no Route 2 process had started.
- The queue log recorded the correct Route 1 tag and did not record a Route 2
  start.

## Current handoff state

The queue worker is intentionally waiting for Route 1 completion and GPU
cleanup. It will then invoke the repaired Unified50 orchestrator. If another
unrelated GPU workload appears, the queue will wait rather than contend with
it; after its configured GPU-wait deadline it fails closed instead of launching
an unsafe concurrent run.

The repaired runtime does not claim an episode succeeded merely because the
simulator process returned zero. Episode validity remains tied to the existing
capture-completion, measurement, trajectory, and integrity checks from the
Unified50 protocol.

## Operational rules going forward

1. Never use redirected log growth as an episode-start or episode-health
   watchdog.
2. Never edit a driver that is currently running; launch an immutable,
   hash-verified snapshot.
3. Use unique result tags and process-tree cleanup, including orphan-descendant
   cleanup after wrapper failure.
4. Hold locks at the orchestrator, driver, and queue layers.
5. Start a queued Route 2 run only after Route 1 has fully disappeared and GPU
   memory has returned to the configured safe level.
6. Record only integrity-validated captures as valid episodes; infrastructure
   failures remain infrastructure failures.

No credential, private token, model binary, simulator log bundle, or video is
stored in this investigation.
