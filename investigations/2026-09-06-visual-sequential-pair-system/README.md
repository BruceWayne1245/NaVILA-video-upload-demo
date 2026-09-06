# 2026-09-06 — Visual sequential-pair online system

## Status

This directory records and packages the first isolated implementation of the
new visual route-memory system discussed on 2026-09-06.  It is a development
candidate, not a completed M50 result.  No live `NaVILA-Bench/scripts` source
file was modified.  All files that required changes were copied into the
standalone path first and edited only there.

Local development root:

```text
/home/teambruce/navila_visual_sequential_pair_20260906
```

The implementation was derived from the code used by the matched-M50 online
system.  `SOURCE_SNAPSHOT.sha256` pins the three source files as they existed
when copied.

## Motivation

The previous online system used LiDAR local-map-to-anchor ICP.  Historical
evaluation showed that approximately 62% of ICP readings were unusable under
the project's reliability definition, while a nominally confident reading
could still have a large bearing or distance error.  Repeated corridor and
planar geometry can create locally convincing but incorrect registrations.

The replacement uses the task's strongest structural prior: return starts at
the last outbound anchor and follows the just-traversed route in reverse.  It
therefore does not need to solve global place recognition.  Anchor identity is
maintained by the existing ordered current/next state.

## Key design decision

The normal return path is strictly:

```text
(current=N, next=N-1)
    -> KEEP or PROMOTE
(current=N-1, next=N-2)
    -> ...
(current=1, next=0)
```

The visual matcher only receives the current and next anchor.  It never ranks
the whole route and cannot jump to a visually similar distant room or corridor.

## Included files

```text
code/
  round_trip_eval_visual.py       isolated Isaac evaluation entry point
  route_memory_agent.py           copied M50 ordered-pair state machine
  relocalization.py               adds the visual ordered-pair backend
  visual_ground_truth_monitor.py  analysis-only Isaac truth recorder
tests/
  test_visual_backend.py
  test_ground_truth_monitor.py
run_visual_sequential_pair_m50.sh  exact matched-M50 episode list and defaults
SOURCE_SNAPSHOT.sha256
ARCHITECTURE.md
IMPLEMENTATION_AND_VALIDATION.md
```

## Current defaults

- anchor spacing: `0.2 m`;
- relocalization interval: every environment update;
- matcher: LoFTR;
- geometry: RGB-D pixel matches, depth back-projection, 3-D RANSAC transform;
- candidate set: only current and next;
- route hint source: integrated visual route memory;
- bounded-evidence promotion: 3 votes in a 5-observation window;
- pair closure check enabled;
- temporal smoothing disabled, matching the later M50 configuration;
- Hint/Arbiter, stop gate, and stuck recovery retained;
- ICP local-map construction disabled for the visual backend;
- ICP-yaw alignment and ICP-trained Reliability V1.1 are not enabled;
- Isaac ground-truth monitor enabled.

The old `0.3 m` short-baseline gate is intentionally not enabled: its threshold
is larger than the new `0.2 m` anchor spacing and would systematically delay
promotion.  All visual promotion thresholds remain provisional until a live
smoke run is inspected.

## Recommended first run

Run one episode before authorizing the full M50:

```bash
cd /home/teambruce/navila_visual_sequential_pair_20260906
ONLY_EPISODES=517 bash run_visual_sequential_pair_m50.sh
```

The first acceptance decision should be based on visual covisibility, match and
RANSAC success rate, per-step bearing error, pair-transition timing, runtime,
and ground-truth-monitor completeness—not only round-trip success.

