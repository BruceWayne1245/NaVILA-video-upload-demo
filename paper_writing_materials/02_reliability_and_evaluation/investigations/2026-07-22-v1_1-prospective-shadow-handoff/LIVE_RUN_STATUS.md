# Live run status and launch audit

## Launch state

- Audit time: 2026-07-22 22:33 BST.
- Start time: 2026-07-22 22:26:57 BST.
- State at audit: running the first scheduled physical episode, CLI episode
  `579` (`2azQ1b91cZZ`); no completed summary row yet.
- Run tag:
  `reliability_v11_prospective_capture_shadow_100ep_20260722_accumulated`.
- Sole controller:
  `claude_ABC_trendbudget_stuckrecovery_20260722`.
- Model state: V1.1 online inference OFF; all model enforcement OFF; raw replay
  capture ON for later frozen offline scoring.

The absence of a summary row at this audit was expected: episode 579 was still
inside its return phase. The running process and replay files were advancing.

## Runtime paths

- Master log:
  `/home/teambruce/reliability_v11_shadow_100ep_20260722_master.log`
- Launched runner:
  `/home/teambruce/navila-v11-shadow-batch/run_batch_template.sh`
- Frozen manifest used by the runner:
  `/home/teambruce/navila-v11-shadow-batch/episodes.tsv`
- Batch directory:
  `/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/reliability_v11_prospective_capture_shadow_100ep_20260722_accumulated`
- Evaluation result prefix:
  `/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_reliability_v11_prospective_capture_shadow_100ep_20260722_accumulated_ep*`

`run_batch_launched_20260722.sh` is the GitHub archive of the launched runner.
Its SHA-256 is
`e958286f0e9e908434056dd655a114f5487efad997ca3d62c5ed03e71fc05954`.

## Actual controller delta

The launch preserves the prior integrated sequential-pair A+B+C controller and
adds Claude's two default-off, explicitly enabled non-model changes:

- `--reliability_quarantine_shared_trend_budget`
- `--stuck_recovery`

The actual Isaac argv contains `--route_hint_source=integrated`,
`--route_relocalization_backend=sequential_pair`, the full prior A+B+C flags,
the two additions above, and `--capture_icp_replay_dataset`. It contains no V1
or V1.1 model/artifact/runtime argument. The old `oracle_anchor` backend is not
the controller.

## Frozen launch hashes

The runner's preflight passed, and every value below was independently
recomputed from the live file after launch:

| Item | SHA-256 |
|---|---|
| batch driver | `ef05eb8464170a801b0043f5bcef35b9c00601734d466c4c5d5523b50d8786d8` |
| `round_trip_eval.py` | `7941f9a9611c11c16491ac18db9d2baffc5862c98157c6bfd7c204c304172866` |
| `route_memory_agent.py` | `1e6af8cef24b2743ea68c9fc525a80ea85e7985a087f1f63309684f6b475fbf8` |
| `relocalization.py` | `226a87b68d5727982a03763da19ec10baf7f90f8d61a66f29e288b8e6bfb09c1` |
| `stop_gate.py` | `0c37014abdc4bc4ad66bf23f167292c3b7ecc21c9a4f09c0d672888bb4f79d0b` |
| `stuck_recovery.py` | `a23cfc6c18816eb8299b7b75eb7f0882455fb1f81c7c33a609c0ebfaabbb6b72` |
| frozen V1.1 artifact | `5f23aba46a45d564131dccd093b1e76160a513162910709503ac8c0a49cb35ce` |
| 100ep manifest | `60d2adf33efeaeb985dc2b234a284a4698ff69160b2a284adfa0ed060b1c60c7` |

The batch's own `run_provenance.txt` contains the same values. The 100-row
manifest is byte-identical to `episodes.tsv`, has 100 unique physical IDs, and
has zero overlap with the preceding fix-ON 100ep set.

## Early capture-integrity audit

Episode 579 entered return at environment step 2150. An early read-only audit
found:

- 17 frozen anchors with contiguous indices 0-16;
- all 17 anchors had world poses;
- 90 replay step files covering steps 2150-2239 with zero gaps;
- every step had a robot world pose and a non-empty raw local point cloud;
- observed current-cloud sizes were 6,769-7,217 points.

Anchor 0 had no local point cloud. The same anchor-0 condition occurs
systematically in the preceding capture batches and is not a new corruption in
this run. It must still remain visible in missingness/availability reporting.

## Runtime durability and capacity

- The batch shell had `PPID=1` at audit.
- Its user has lingering enabled.
- Effective logind configuration uses `KillUserProcesses=no`.
- The batch was still in the active SSH session scope rather than a dedicated
  user service; the current host policy nevertheless does not kill remaining
  user processes on logout.
- SSD4T had approximately 2.6 TiB free at launch audit.

## What this status does not establish

- It does not establish that all 100 scheduled episodes will finish.
- It does not establish zero capture drops across the complete batch.
- It does not provide any prospective V1.1 metric yet.
- It does not test a V1.1 online runtime.
- Navigation outcomes test Claude's controller, not the model.
- Because these are new episodes without an old-controller paired arm, the
  Claude result is a scale-up/historical comparison, not a clean causal A/B.
