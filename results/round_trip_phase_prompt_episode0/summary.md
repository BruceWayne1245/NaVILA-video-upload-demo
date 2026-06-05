# Round-Trip Phase-Prompt Baseline — Episode 0

Run date: 2026-06-05

Mode: `phase_prompt`

Command target:

```text
go2_matterport_vision, episode_idx=0, load_run=2024-09-25_23-22-02
```

Outcome:

- Outbound reached the original target region and NaVILA emitted `stop`.
- Confirm phase completed as the scripted 360-degree scan.
- Return phase started and continued inside the same simulator episode.
- Return did not reach the original start point.

Key metrics:

```text
outbound stop step: 1200
outbound stop distance to goal: 0.493 m
outbound goal radius: 3.0 m
outbound success: true by distance threshold
return success: false
round-trip success: false
final distance to start: 8.523 m
final distance to outbound goal: 2.974 m
video: output_0.mp4
```

Note:

The raw measurement JSON from this first run has `round_trip.outbound_success=false` because the initial evaluator computed outbound success from the final post-return measurement. The evaluator code was fixed after this run to compute outbound success at the first outbound `stop` using the outbound goal radius.
