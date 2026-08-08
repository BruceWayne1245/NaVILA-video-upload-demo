# Route 2 Anchor V3 progress — 2026-08-08

## Scope and safety boundary

This investigation is an offline redesign and data-preparation effort for
Route 2 Anchor V3. It has not modified the canonical Route 2 runtime, launched
an evaluator episode, changed any queue, or stopped any existing process.

The canonical relocalization source used for replay is:

`/home/teambruce/navila-route2-v11-core-20260801/runtime_candidate/scripts/relocalization.py`

Its locked SHA-256 is:

`c53e6be4e3800c7b4e30a54ac4faa144b746928ecc4713af40ff482f7d49b40d`

## Completed work

1. Audited the latest Route 2 failure history and identified the core issue:
   candidate visibility cannot be used as a direct SKIP label. Several distant
   anchors can be geometrically observable in one frame.
2. Implemented exact online-log alignment and a continuity-aware physical-route
   oracle over the 14 hard return-failure episodes.
3. Implemented two separate teachers:
   - tracking teacher for consecutive trusted physical states;
   - corrective teacher for stale/inconsistent model states or sampled gaps.
4. Froze the atomic state contract. SKIP moves the complete state across
   multiple route transitions, but the published current/next pair remains an
   adjacent bracket (or a terminal collapse). No downstream code may repair one
   member of the pair independently.
5. Audited 872 historical directories. After physical-episode deduplication and
   scene checks, 140 replayable episodes across 9 scenes were selected. The
   scene-disjoint split is 5 train scenes, 2 validation scenes, and 2 test
   scenes.
6. Created a provenance-locked adaptive replay plan with 5,691 frames (about
   2.87 GB). Every selected frame, anchor map, and trajectory has a SHA-256
   record. Decision ordinal and sampling gaps are included so adaptive frame
   selection cannot be mistaken for consecutive controller attempts.
7. Implemented the tensorizer, causal dataset/collator, masked point encoder,
   candidate-set and temporal Transformers, joint current-by-next pair head,
   multi-task loss, train-only scalar normalizer, checkpointing, and evaluator.
8. Completed CPU and GPU smoke tests. A real four-episode pilot completed one
   GPU epoch with validation total loss 2.6601. The GPU smoke used an isolated
   environment and did not change NaVILA's environment.

## Isolated training environment

Environment:

`/home/teambruce/anchor-v3-20260808/.conda-env`

- Python 3.10.20
- PyTorch 2.5.1+cu121
- CUDA runtime 12.1
- NumPy 1.26.4

An escalated read-only check detected the RTX 4090 and reported
`torch.cuda.is_available() == True` in this environment. The NaVILA environment
`/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac` was not modified.

## Current in-progress work

The 5,691-frame replay plan is split into 8 independently resumable shards.
Materialization is CPU-only and uses the canonical relocalization hash above.
At the latest checkpoint, 780 rows had been written; the shard processes had
been restarted using their existing `(physical_episode_id, step)` keys so no
completed row is recomputed.

GPU training is not running while replay materialization proceeds. The full
training and scene-disjoint evaluation start only after all eight shards pass
JSONL, hash, candidate-coverage, and tensorization audits.

## Relevant local artifacts

- `manifests/historical_compatibility_catalog.json`
- `manifests/replay_cohort_scene_disjoint.json`
- `manifests/adaptive_replay_plan_locked.json`
- `anchor_v3/contract.py`, `teacher.py`, `tensorize.py`, `dataset.py`, `model.py`
- `tools/materialize_replay_shard.py`
- `tools/train_anchor_v3.py`

