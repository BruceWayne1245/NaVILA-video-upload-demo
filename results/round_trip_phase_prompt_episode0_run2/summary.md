# Round-Trip Phase-Prompt Baseline — Episode 0, Run 2

Run date: 2026-06-05

Purpose:

Validate the evaluator fix that computes outbound success at the first outbound `stop` using the outbound goal radius.

Outcome:

- Outbound reached the original target region.
- NaVILA emitted `stop` at the outbound target.
- Confirm phase completed as the scripted 360-degree scan.
- Return phase ran inside the same simulator episode.
- NaVILA emitted `stop` during Return, but the robot was still far from the original start point.

Key metrics:

```text
outbound stop step: 1425
outbound stop distance to goal: 0.780 m
outbound goal radius: 3.0 m
outbound success: true
return stop step: 4801
return stop distance to start: 6.055 m
final distance to start: 6.062 m
return success: false
round-trip success: false
top-level path length: 29.794 m
```

Artifacts:

```text
measurement.json
output_0.mp4
```
