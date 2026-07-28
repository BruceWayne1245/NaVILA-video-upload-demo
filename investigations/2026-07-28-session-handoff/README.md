# 2026-07-28 session handoff

This is the primary restart point for the next session. It records the code
changes, live evidence, open interpretation, and the running 30ep -> 50ep
queue without relying on chat history.

## Current objective

Validate the redesigned terminal stop behavior at scale. Route1's existing
30-episode promotion-shadow batch is running first. The frozen anchor/stop
Active-50 batch is armed behind it and will start automatically only after a
strict fail-closed handoff.

## What changed today

Four stop/recovery changes were implemented:

1. Current/rear support is no longer conflated with next/forward guidance.
2. A one-sided support failure keeps the still-trusted side instead of
   discarding the whole pair.
3. A two-sided failure tries only bounded alternating support pairs, then
   enters VLM-only probing.
4. Terminal stopping is an evidence state machine rather than a single
   possibly stale stop-gate lookup.

Two blind spots found during smoke testing were then repaired:

- Short routes now receive their actual available anchor indices. Invalid
  recovery pairs are skipped, the last valid pair is retained, and recovery
  enters VLM-only probing when no later valid pair exists.
- Loss of valid terminal evidence before a STOP proposal is bounded too. It
  arms only after fresh trusted raw-next evidence enters the terminal corridor;
  four consecutive unknown observations enter terminal-blind mode, eight total
  blind queries are shared across that episode phase, fresh evidence resets
  the blind state, and exhausted evidence ends in `safe_fail`.

Runtime hardening added during ep420:

- Scan Context connected-region traversal uses a checked 2-D boolean array and
  a Python set for visited cells, eliminating the recurring
  `TypeError: 'int' object is not subscriptable`.
- Fatal evaluator exceptions print a traceback, close Isaac, and exit nonzero.
- The batch runner cleans evaluator/VLM process groups on SIGINT/SIGTERM.

The implementation and tests are snapshotted in:

- `../2026-07-28-anchor-support-recovery/`
- `../2026-07-28-terminal-stop-evidence-state-machine/`
- `../2026-07-28-anchor-stop-active50-readiness/`

## Evidence from live episodes

### ep205

Completed the round trip successfully. Final true distance was 0.842 m. Of 46
terminal-gate decisions, 45 passed normally and one was forced only after a
fresh trusted raw-next near streak. This is the positive terminal-stop smoke
case.

### ep89

The first run exposed an invalid short-route support request:
`RuntimeError('unknown V11 support current anchor 6')`. After the short-route
repair, it crossed that former crash point. It later entered true distance
2.629 m and 2.821 m without a VLM STOP, then degraded to 4.203 m at step 2525
and could not plausibly recover, so it was terminated early. Its exact signal
sequence is now a bounded pre-STOP regression ending in `safe_fail`.

### ep420

One run reached return, then repeated hint-override right turns triggered stuck
recovery and the historical Scan Context connected-region crash. That crash
was repaired and stress-tested. A rerun completed validly but failed outbound
because the VLM never proposed outbound STOP; it is not a positive
terminal-gate case.

### ep490

The attempted result is invalid/incomplete because Isaac Kit shut down. Do not
use it as behavior evidence.

## Validation state

- focused candidate suite: 49 passed
- terminal state-machine snapshot suite: 40 passed
- Active-50 readiness snapshot suites: 24 passed when run by package
- Scan Context randomized stress: 500 iterations passed
- Active-50 frozen-cohort preflight: passed
- out-of-scope ep999 launch: correctly rejected with exit 2
- exact Active-50 manifest SHA-256:
  `5c31cf60c05e64f97e1842a5d9d36cf95484ac775f0b9a50bd3afc9b93dac957`

Only Route2 consumer enforcement and anchor-support recovery are active in the
50ep policy. Integrated promotion, anchor-state mutation, candidate selector,
candidate controller, and active scan plan remain off.

## Running queue at handoff

Upstream Route1 unit:

```text
navila-promotion-shadow-30ep-20260728.service
run tag: promotion_shadow_30ep_20260728
started: 2026-07-28 20:30:31 BST
snapshot PID: 36648
snapshot state: active/running
```

Downstream queue unit:

```text
navila-anchor-stop-active50-after-promotion30-20260728.service
started: 2026-07-28 20:40:07 BST
snapshot PID: 37808
snapshot state: active/running
```

At 20:42 BST the downstream preflight had passed, Route1's summary contained
only its header, and Active-50 had not started. The queue script and complete
gate contract are preserved in
`../2026-07-28-anchor-stop-active50-readiness/runner/wait_for_promotion30_then_anchor50_20260728.sh`.

Important paths:

```text
Route1 summary:
/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/promotion_shadow_30ep_20260728/summary.tsv

Route1 batch log:
/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/promotion_shadow_30ep_20260728/batch.log

queue / Active-50 log directory:
/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/reliability_v11_anchor_stop_active50_20260728
```

## First actions next session

1. Read the tail of `queue.log`.
2. Inspect both systemd units.
3. Check Route1's `summary.tsv` and final batch marker.
4. If Active-50 is running, monitor its batch log and summary; do not start a
   second copy.
5. If the queue failed, use its explicit `FATAL` reason. Do not bypass the
   completion, process, GPU, hash, or preflight gates.
6. Classify results with special attention to stop-gate source selection,
   pre-STOP terminal blindness, post-STOP verification blindness, recovery
   pair validity, and any remaining wrong-object linkage.

Operational policy allows a stuck episode to be terminated early when logs and
trajectory show it cannot escape; there is no need to wait for the nominal
timeout merely to confirm an irreversible deadlock.
