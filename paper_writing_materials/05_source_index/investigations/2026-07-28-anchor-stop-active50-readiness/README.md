# Anchor/stop Active-50 readiness

Date: 2026-07-28

## Decision

GO for the exact frozen 50-episode cohort. It is queued behind the already
running Route1 30-episode batch and must not start until that batch satisfies
the exact completion contract below.

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
- `runner/wait_for_promotion30_then_anchor50_20260728.sh`
- `configs/v11_anchor_support_recovery_active_v1_active50_approved_20260728.json`
- `tests/test_terminal_stop_gate.py`
- `tests/test_scan_context_runtime.py`

## Automatic 30ep -> 50ep handoff

Runtime units:

- upstream: `navila-promotion-shadow-30ep-20260728.service`
- queue/downstream: `navila-anchor-stop-active50-after-promotion30-20260728.service`

The queued handoff is deliberately fail closed. Active-50 starts only after:

1. the upstream unit is inactive and, when still observable, has exit status 0;
2. the Route1 batch log contains its final `Batch finished at` marker;
3. `summary.tsv` contains exactly the frozen 30 episodes, once each;
4. no evaluator or VLM process remains;
5. GPU 0 has at least 12,000 MiB free for six checks spaced 10 seconds apart;
6. the Active-50 runner and policy still match their frozen SHA-256 values; and
7. the Active-50 preflight passes again at the actual handoff.

Frozen handoff hashes:

- Route1 runner:
  `b541226c775175866176794c47fad56338caea92a687783dcc06e6455016edfe`
- Active-50 runner:
  `cd4f5a4cea78b457a120daf664292f2c70157f78b65ac2e5604e558ea07d559d`
- Active-50 policy:
  `04bdfd8260525dac7ed03c63b1189378c3f2eb6ee78a4d36fab3b3ffd2c816f2`
- queue script:
  `b38090579785f6a252d06aacf5bd9270f00d15fad7c3a55b38956a34c776a0a1`

Frozen Route1 order:

```text
669 490 671 5 1062 427 688 581 368 310 351 888 962 658 785
815 264 268 205 961 1038 539 367 88 784 579 646 844 366 647
```

Runtime logs:

- Route1 summary:
  `/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/promotion_shadow_30ep_20260728/summary.tsv`
- Route1 batch log:
  `/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/promotion_shadow_30ep_20260728/batch.log`
- handoff queue log:
  `/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/reliability_v11_anchor_stop_active50_20260728/queue.log`

At the 2026-07-28 20:42 BST snapshot, Route1 was active with main PID 36648
and the queue was active with main PID 37808. The downstream preflight had
passed, Route1 had not yet written a completed summary row, and Active-50 had
not started early.

## Resume checklist

Read `../2026-07-28-session-handoff/README.md` first. Then inspect the queue
log and both units:

```bash
systemctl --user status navila-promotion-shadow-30ep-20260728.service
systemctl --user status navila-anchor-stop-active50-after-promotion30-20260728.service
tail -n 100 /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/reliability_v11_anchor_stop_active50_20260728/queue.log
```

If the queue is still waiting, monitor Route1. If its process has been replaced
by the Active-50 runner, monitor the Active-50 batch log and summary. If it
exited nonzero, read the `FATAL` line in `queue.log` and do not bypass or
blindly relaunch the failed gate.
