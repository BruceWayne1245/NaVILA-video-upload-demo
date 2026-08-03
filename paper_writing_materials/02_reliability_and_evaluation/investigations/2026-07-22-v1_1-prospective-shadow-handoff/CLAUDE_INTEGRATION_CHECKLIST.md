# Claude integration checklist

Use this only after the non-model controller changes and their small-scale
checks are complete.

## 1. Start from authoritative code

- Read the newest GitHub `README.md` and subsequent investigations first.
- Locate the live files named there; do not use stale local copies.
- Record the GitHub commit and the exact live working-tree source hashes used
  for the run.

## 2. Merge the controller, not the model

- Put Claude's finalized controller flags in `COMMON_EXTRA` in
  `run_batch_template.sh`.
- Preserve `ROUTE_HINT_SOURCE=integrated` and the intended relocalization
  backend unless Claude's investigation explicitly changes them.
- Preserve `--capture_icp_replay_dataset`.
- Do not load V1/V1.1 online and do not enable any learned-model consumer.
- State clearly in provenance that Claude's configuration is the sole
  controller and V1.1 is offline capture shadow only.

## 3. Refresh implementation locks

Recompute and replace the expected hashes for the batch driver and every live
navigation file used by the template. At minimum recheck:

```bash
sha256sum \
  scripts/run_oracle_anchor_100ep_batch_20260720.sh \
  scripts/round_trip_eval.py \
  scripts/route_memory_agent.py \
  scripts/relocalization.py \
  scripts/stop_gate.py
```

Do not change the frozen episode-manifest or V1.1 artifact hashes. If Claude's
work renames/replaces a live file or changes the base-driver function boundary,
update the runner structure and provenance explicitly.

## 4. Preserve the episode and retry policy

- Use every row of `episodes.tsv` exactly once as a physical episode.
- A prior successful/non-98 row is resume-complete.
- A pure VLM startup `exit_code=98` may be retried once after 120 seconds.
- Preserve both infrastructure-attempt rows under the same physical-episode
  cluster.
- Do not retry or replace an episode based on navigation result, model score,
  ground-truth label, missing return, or perceived difficulty.

## 5. Preflight before launch

Run:

```bash
bash run_batch_template.sh --preflight-only
```

Require all of the following:

- 100 unique episode IDs;
- no overlap with the preceding fix-ON 100ep set;
- exact manifest and frozen artifact hashes;
- exact hashes for Claude's finalized live code;
- sufficient disk space for full per-step ICP replay capture;
- no existing process or batch using the chosen ports/run tag.

Only after preflight passes should the template be made executable or embedded
in Claude's final launcher. Do not automatically chain it while code/config is
still changing.

## 6. Analysis contract after completion

- Keep unopened aggregate model outcomes frozen until capture integrity is
  audited.
- Score with the existing V1.1 development artifact without refitting.
- Cluster uncertainty by physical CLI episode ID.
- Report the operational waterfall: all scheduled episodes -> launched ->
  outbound success -> return capture -> valid V1.1 rows -> trusted rows.
- Report each head, joint trust, current/next role, scene, and return stage.
- Compare V1.1/Claude heuristic disagreement cells against ground-truth error.
- Do not attribute Claude's navigation outcome to the model, which had no
  control authority.
