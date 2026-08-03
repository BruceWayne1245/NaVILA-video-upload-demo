# Session handoff — 2026-07-31

## How to resume after a reboot

This file is a compact operational handoff, not a replacement for project
authority. On a new conversation, first read the latest GitHub `README.md`, the
latest `investigations/` entries, this file, and the linked 7/31 runtime
forensics record. Then re-check the live machine: all PIDs, ports, GPU usage,
and queue state below are pre-reboot observations and must not be reused as
current facts.

Authoritative GitHub repository:

`BruceWayne1245/NaVILA-video-upload-demo`

Relevant records:

- `investigations/2026-07-31-route2-runtime-failure-forensics/README.md`
- `investigations/2026-07-31-route2-runtime-failure-forensics/AMENDMENT.md`
- `investigations/2026-07-30-route2-anchor-hint-terminal-unified-shadow50/`

## State immediately before the planned reboot

- The Route 2 Unified Shadow50 handoff queue was explicitly cancelled at the
  user's request because the runtime environment is being repaired.
- The queue worker and its process group were terminated. There must be no
  automatic Route 2 restart after reboot.
- The interrupted Route 2 ep670 canary was infrastructure audit only and must
  not be counted as a valid episode.
- Route 1's current 30-episode batch was deliberately left untouched. Before
  reboot it was running `promotion_shadow_reliable30v3_20260731`; after reboot,
  assume nothing about whether it resumed or stopped until checked.
- No route2 result should be trusted from the accidental concurrent canary.

## Root causes established today

1. A 900-second startup watchdog used redirected evaluator-log/result growth as
   liveness. Historical logs are buffered until episode completion, so the
   watchdog killed healthy in-progress episodes and produced zero valid
   captures.
2. Editing an active driver in place caused mixed script state and an observed
   shell error followed by an unexpected episode restart.
3. Wrapper-only cleanup left orphan evaluator/VLM descendants holding GPU
   memory.
4. The first repaired queue still checked only Route 1 episode processes. A
   normal between-episode gap made that signal empty while the Route 1 master
   driver was still alive, so Route 2 ep670 started concurrently. This was
   stopped and documented in `AMENDMENT.md`.

## Runtime repairs present on the workstation

These are local operational scripts, not experiment authority:

- `/home/teambruce/navila-unified-shadow50-20260730/launch/run_manifest_batch_driver.sh`
  - driver lock;
  - immutable process-group capture and recursive cleanup;
  - no startup-log watchdog;
  - outer `7200s` timeout with `300s` kill-after;
  - `PYTHONUNBUFFERED=1`.
  - SHA-256: `887fec7ad8296ec8b6c19af7e8a4639d2cdfa2d3ca7cf03fde46f01133ef80bb`
- `/home/teambruce/navila-unified-shadow50-20260730/launch/run_unified_shadow50.sh`
  - orchestrator lock;
  - expected driver SHA check;
  - immutable per-run driver snapshot;
  - post-run tagged-child check.
  - SHA-256: `bec6a962d76909d70afd79e05a4bbf2948da28fe304d34f2e4dbff68cbfb7ffa`
- `/home/teambruce/navila-unified-shadow50-20260730/launch/wait_for_route1_then_run_unified50.sh`
  - queue lock;
  - recognizes current Route 1 tags;
  - blocks on Route 1 master/driver paths as well as episode descendants;
  - requires `22,000 MiB` free GPU before any future Route 2 start.
  - SHA-256: `487e5e0d2b35a08c2b89094bb2d963e5c6be561108624dcba88da179565c4cab`

Do not launch the queue during environment repair. Re-validate all three
scripts and the machine state first.

## Safe next sequence after reboot

1. Confirm no leftover Route 1/Route 2/VLM/Isaac processes and inspect GPU
   memory, ports, and process trees.
2. Confirm the user has finished repairing the runtime environment.
3. Re-read the latest GitHub README and investigations; do not rely on old
   local README/code copies.
4. Verify the local runtime candidate and the frozen experiment inputs still
   match the authoritative GitHub state.
5. Run shell syntax checks and frozen-cohort/GPU preflight.
6. Decide explicitly whether to resume, rebuild, or discard the Route 1 batch;
   do not infer this from stale PIDs or old queue logs.
7. Only after an explicit new instruction should a Route 2 queue be launched.

No credential, token, model binary, simulator log bundle, or video is stored in
this handoff.
