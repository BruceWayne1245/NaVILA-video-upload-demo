# Amendment — Route 1 episode-gap queue race (2026-07-31)

## Incident

After the first guarded queue worker was attached, it still launched the
Unified50 canary while Route 1 was running. This was **not** a diagnostic
process. At 09:57 BST the queue log reported Route 1 complete and started
Unified50 ep670, while the Route 1 master driver
`run_promotion_shadow_reliable30v3_20260731.sh` was still alive and advancing
to later episodes.

GPU inspection showed two independent 8-bit VLM servers, each using about
10,110 MiB:

- Route 1: port 63005, `promotion_shadow_reliable30v3_20260731_ep5`;
- erroneously started Route 2: port 59670,
  `unified_shadow50_ep670_replication_retry4_20260730_ep670`.

The Route 2 canary was stopped by its exact process groups and unique result
suffix. Route 1 was not terminated. After cleanup, only the Route 1 VLM
remained on the GPU, plus the small AnyDesk allocation. The interrupted Route
2 canary is infrastructure audit only and must not be counted as a valid
episode.

## Root cause

The queue checked Route 1 systemd units, old launcher names, and episode
processes matching `result_suffix=..._epN`. During normal between-episode setup,
the current episode process disappears briefly before the next one is created.
The Route 1 master and driver remained alive, but the queue did not inspect
them, so it falsely concluded that Route 1 had completed.

GPU-free memory was therefore an unsafe second gate: the GPU happened to be
free during that short setup interval, even though the Route 1 batch was about
to create its next VLM.

## Repair and verification

The queue now also requires these explicit Route 1 master/driver paths to be
absent:

- `/home/teambruce/run_promotion_shadow_reliable30v3_20260731.sh`
- `/home/teambruce/run_promotion_shadow_reliable30v3_driver_20260731.sh`

Episode processes remain a secondary signal; they are no longer the sole
completion criterion. `bash -n` passes after the change. A new detached queue
worker (PID `338239` at verification) was started while the Route 1 master was
still active. Its log remained in the waiting state, no Route 2 process was
present, and GPU inspection showed only the Route 1 VLM.

## Revised rule

Route 2 may start only when the Route 1 service/master/driver **and** all
matching episode descendants have exited, followed by the configured GPU-free
check. A between-episode gap is not completion evidence.
