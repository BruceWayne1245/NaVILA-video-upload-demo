# Anchor V3 handoff — 2026-08-08

## Current state

The offline Anchor V3 replay dataset has been completed and audited. The
original materialized shards remain untouched in the local workspace. They
contained 10,620 lines because two concurrent materializer invocations wrote
the same deterministic rows; 4,929 exact duplicate lines were removed into a
separate output directory.

The canonical deduplicated dataset contains exactly 5,691 unique frames and
matches the locked replay plan with zero missing or unexpected keys. All eight
shards passed JSON, candidate-coverage, tensorization, and runtime-hash audits.
The canonical relocalization hash is:

`c53e6be4e3800c7b4e30a54ac4faa144b746928ecc4713af40ff482f7d49b40d`

Scene-disjoint formal splits were generated locally:

- train: 4,128 frames, 94 episodes, 5 scenes
- validation: 1,133 frames, 31 episodes, 2 scenes
- test: 430 frames, 15 episodes, 2 scenes

There is no scene overlap between the three splits. The causal sequence
materialization produced 563 train, 154 validation, and 60 test sequences.
Train-only scalar normalization was computed and saved.

## Local paths

Workspace: `/home/teambruce/anchor-v3-20260808`

- Deduplicated shards: `shards/full_replay_dedup/`
- Formal split JSONL: `shards/formal_dataset/{train,validation,test}.jsonl`
- Dataset manifest: `shards/formal_dataset/manifest.json`
- Dataset summary: `shards/formal_dataset/dataset_summary.json`
- Train normalizer: `shards/formal_dataset/train_normalizer.json`
- Deduplication utility: `tools/deduplicate_replay_shards.py`
- Audit utility: `tools/audit_replay_shard.py`

## Training handoff

The isolated environment is `/home/teambruce/anchor-v3-20260808/.conda-env`
with Python 3.10.20, PyTorch 2.5.1+cu121, and NumPy 1.26.4. The NaVILA
environment `/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac` was not modified.

After the user confirmed the GPU was free, baseline training was started with:

```text
/home/teambruce/anchor-v3-20260808/.conda-env/bin/python tools/train_anchor_v3.py \
  --train-shard shards/formal_dataset/train.jsonl \
  --validation-shard shards/formal_dataset/validation.jsonl \
  --checkpoint reports/anchor_v3_baseline_checkpoint.pt \
  --normalizer reports/anchor_v3_baseline_normalizer.json \
  --epochs 5 --batch-size 1 --sequence-length 8 --device cuda
```

At handoff time the command is still running in its CPU dataset/normalizer
preparation phase; no checkpoint has appeared yet and `nvidia-smi` has not
shown a compute process. Do not start a second training job until this one is
confirmed finished or explicitly stopped by the user. The training session is
not an EP runtime and does not modify any NaVILA experiment process.

## Next actions

1. Confirm the current training command transitions into CUDA forward/backward.
2. Record its epoch losses and validation losses.
3. Preserve the best checkpoint and normalizer.
4. Run scene-disjoint offline evaluation on the test split.
5. Analyze action, pair-adjacency, belief, confidence, blind-recovery, and
   stop-gate-related metrics before considering any runtime shadow test.

No runtime integration, EP scheduling, SSH, process termination, or existing
NaVILA environment modification is authorized by this handoff.
