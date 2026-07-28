# Anchor/stop Active-50 readiness

Date: 2026-07-28

## Decision

GO for the exact frozen 50-episode cohort, with normal batch monitoring. The
runner is prepared but was not launched by this readiness task.

## Live evidence

- ep205 completed round trip successfully at a true final distance of 0.842 m.
  The terminal decision was forced only after a fresh trusted raw-next near
  streak.
- ep89 crossed the fixed short-route recovery boundary without requesting a
  non-existent anchor. It then exposed a pre-STOP blind loop: true distance
  entered 3 m twice and later degraded to 4.203 m without a STOP proposal.
  The exact sequence now ends in bounded `safe_fail` in regression.
- ep420 reached return in one attempt and exposed the recurring Scan Context
  connected-region crash after stuck recovery engaged. A second stochastic
  attempt completed cleanly as an outbound failure because the VLM never
  issued outbound STOP; it is a valid completion, not a terminal-gate result.

## Additional repairs

- Short routes skip unavailable recovery pairs and retain the last valid
  support pair before VLM-only probing.
- Terminal-corridor signal loss is bounded before as well as after STOP.
- Scan Context flood fill uses a checked 2-D boolean grid and Python visited
  set; 500 randomized stress iterations pass.
- Fatal evaluator exceptions print traceback, close Isaac and request nonzero
  exit.
- SIGINT/SIGTERM clean evaluator and VLM process groups.

## Frozen runtime

- manifest SHA-256:
  `5c31cf60c05e64f97e1842a5d9d36cf95484ac775f0b9a50bd3afc9b93dac957`
- focused tests: 49 passed
- 50ep preflight: passed
- out-of-scope ep999: rejected with exit 2
- final GPU state: 24,018 MiB free, 0% utilization

Only Route2 consumer enforcement and anchor-support recovery are active.
Integrated promotion, anchor-state mutation, candidate selector, candidate
controller and active scan plan are off.

Prepared files:

- `runner/run_anchor_stop_active50.sh`
- `configs/v11_anchor_support_recovery_active_v1_active50_approved_20260728.json`
- `tests/test_terminal_stop_gate.py`
- `tests/test_scan_context_runtime.py`
