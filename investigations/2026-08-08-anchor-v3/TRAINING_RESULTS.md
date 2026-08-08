# Anchor V3 baseline training — results and NaN bug fix (2026-08-08, continued)

This continues `HANDOFF.md`/`PROGRESS.md` from the same day. At handoff time,
baseline training had just been launched and had not yet reached CUDA. This
covers what happened after: two full training attempts, a real bug found and
fixed, a third clean training run, and the first offline test-split
evaluation with an error breakdown.

## Attempt 1: silent death, no system-level cause found

The training process launched at handoff time disappeared some time between
16:48 and 17:02 BST with no checkpoint written and no trace in `dmesg` or
`journalctl` (no OOM-killer entry, no systemd kill). Its stdout/stderr had
been piped directly to the launching Codex process rather than a file, so no
traceback survived. GPU free memory was tight at the time (~1.4GB free, a
NaVILA evaluator episode was running concurrently) but this could not be
confirmed as the cause.

## Attempt 2: completed, but every loss was NaN

Relaunched with output redirected to a log file this time
(`reports/train_run2.log`) and a GPU-monitoring watchdog running alongside
(`tools/monitor_training_gpu.sh`, polls every 15s, warns <2048MiB free GPU
memory, critical <512MiB). This run completed all 5 epochs cleanly (no crash,
confirmed via `systemctl`/`journalctl` — no failure recorded) but
`train_total` and `validation.pair`/`validation.total` were `NaN` in every
single epoch. Because `tools/train_anchor_v3.py`'s checkpoint-saving
condition was `if score < best:` and any comparison against `NaN` is `False`
in Python, **no checkpoint was ever written despite 5 completed epochs.**

## Root cause (verified, not inferred)

In `anchor_v3/losses.py`, both the `pair` and `belief` loss terms have a
fallback branch for "this batch has zero valid supervised timesteps":

```python
pair = (... if pair_valid.any() else output["pair_logits"].sum() * 0.0)
belief = (... if belief_valid.any() else output["belief_logits"].sum() * 0.0)
```

`pair_logits`/`belief_logits` are masked with `float("-inf")` at invalid
candidate/pair positions (`model.py`). When the fallback branch fires,
`tensor.sum()` over a tensor containing `-inf` is `-inf`, and **`-inf * 0.0 =
NaN`** under IEEE 754 — the "differentiable zero" idiom silently breaks
whenever the tensor it's derived from contains an infinity.

This fallback fires far more often than expected: a direct sweep of the
training set (`ReplaySequenceDataset`, sequence_length=8, batch_size=1) found
**16/60 sampled sequences (~27%) have zero timesteps with a valid `pair`
target across the whole 8-step window** (`pair_valid = teacher.action is not
ABSTAIN and both anchors visible in that frame's own candidate set` —
routinely unsatisfied, consistent with `PROGRESS.md`'s point 1 that candidate
visibility can't be treated as a direct SKIP signal). Because
`train_total += float(loss["total"])` accumulates across the whole epoch,
one `NaN` batch anywhere poisons the entire epoch's reported total — with a
27% per-sequence hit rate over 563 train sequences, hitting at least one
NaN batch per epoch was effectively guaranteed.

Reproduced directly: a real degenerate sequence (index 23 in `train.jsonl`)
forward-passed through a freshly-initialized model gives
`pair_logits` containing `-inf`, `pair_logits.sum() == -inf`,
`pair_logits.sum() * 0.0 == nan` — confirmed bit-for-bit before any fix.

## Fix

`anchor_v3/losses.py`: replaced all three `tensor.sum() * 0.0` fallback-zero
expressions (top-level empty-batch guard, `pair` fallback, `belief`
fallback) with `torch.zeros((), device=..., dtype=...)` — a literal zero
that cannot be corrupted by `-inf`/`+inf` values elsewhere in the tensor.

`tools/train_anchor_v3.py`: checkpoint condition changed from `if score <
best:` to `if math.isfinite(score) and score < best:` as defense in depth,
independent of the root-cause fix.

**Verified before relaunching training**, not just unit-reasoned:
- The degenerate sequence (index 23) re-run after the fix: `pair` loss goes
  from `NaN` to `0.0`, `total` becomes finite (1.818).
- Full sweep of all 717 sequences in `train.jsonl` + `validation.jsonl`
  (fresh model, forward pass only): **0/717 produce a NaN total**, versus
  the guaranteed-NaN behavior before the fix.

## Attempt 3: clean training run, real results

Relaunched (`reports/train_run3.log`, same watchdog). Completed 5 epochs
cleanly, zero NaN anywhere, watchdog logged GPU-free-memory `WARNING`s
throughout (~1–1.5GB free, a NaVILA evaluator episode was running
concurrently) but never a `CRITICAL` and never an unexpected process death.

| epoch | train_total | val_total | val_action | val_pair | val_belief | val_confidence | checkpoint saved? |
|---|---|---|---|---|---|---|---|
| 0 | 3.107 | 2.318 | 0.591 | 1.179 | 0.963 | 0.269 | yes |
| 1 | 1.943 | 2.086 | 0.484 | 1.132 | 0.841 | 0.197 | yes |
| 2 | 1.468 | **1.719** | 0.488 | 0.816 | 0.743 | 0.172 | yes (best) |
| 3 | 1.143 | 2.097 | 0.486 | 1.201 | 0.700 | 0.243 | no (val worse) |
| 4 | 1.010 | 1.865 | 0.538 | 0.937 | 0.637 | 0.287 | no (val worse) |

`train_total` falls monotonically; `val_total` bottoms out at epoch 2 and
rises again at 3–4 — an early overfitting signal on this small a dataset
(4,128 train frames / 563 sequences) worth watching in any longer run, not
treated as a bug. Saved checkpoint = epoch 2 weights, `reports/
anchor_v3_baseline_checkpoint.pt` (10.78MB), paired normalizer at `reports/
anchor_v3_baseline_normalizer.json`.

## First test-split evaluation (`tools/evaluate_anchor_v3.py`, new)

No test-split evaluator existed before this session — `PROGRESS.md`'s
"evaluator" was only the training-loop validation-loss function. Built
`tools/evaluate_anchor_v3.py`: loss decomposition (reused from training) plus
label-grounded accuracy (action, pair exact-match, pair-adjacency
compliance, belief top-1, confidence Brier score / threshold accuracy).
Deliberately scoped to metrics directly backed by existing target fields;
**blind-recovery and stop-gate-related metrics were explicitly deferred** —
neither concept has any code grounding in the offline `anchor_v3` package
yet (they're runtime concepts from `route_memory_agent.py`), so building them
would mean designing new evaluation logic, not just running an existing one.

Run on `shards/formal_dataset/test.jsonl` (430 frames / 60 sequences, scene-
disjoint from train/validation) with the epoch-2 checkpoint, on CPU (no GPU
needed for a model this size, avoids adding load while the concurrent NaVILA
evaluator was running):

| metric | value |
|---|---|
| test loss (total) | 2.125 |
| action accuracy | 73.95% (n=430) |
| pair exact-match accuracy | 71.6% (n=398 pair-valid frames) |
| pair-adjacency compliance | **100%** (structural — enforced by the model's adjacency mask before argmax, not learned; a sanity check that the atomic-pair contract holds architecturally) |
| belief top-1 accuracy | 71.78% (n=404) |
| confidence Brier score | 0.043 |
| confidence threshold (0.5) accuracy | 94.88% |

Majority-class baseline check: always predicting the dominant action class
(`keep`, 270/430 = 62.8% of test frames) would already score 62.8% action
accuracy — the model's 73.95% beats this by +11.1 points, confirming it is
learning real signal rather than mostly reproducing the class prior.

## Error breakdown (`tools/breakdown_test_eval.py`, new)

Split the same test-set predictions by `teacher_stream`
(`tracking` vs. `corrective_sample_gap`) and by true action class.

**Result contradicted the a priori expectation.** `corrective_sample_gap`
frames — the harder scenario this redesign specifically targets (state
carried across a gap where instantaneous candidate visibility can't be
trusted) — were *not* worse than `tracking` frames. On pair and belief they
were substantially *better*:

| task | tracking | corrective_sample_gap |
|---|---|---|
| action accuracy | 74.8% (n=266) | 72.6% (n=164) |
| pair exact-match | 64.3% (n=252) | **84.2%** (n=146) |
| belief top-1 | 61.2% (n=258) | **90.4%** (n=146) |

Action is roughly flat between the two streams; pair/belief are 20–29 points
*higher* on the corrective/gap stream. Not yet root-caused — one plausible
explanation is that `corrective_teacher` re-anchors pair/belief targets
directly from the oracle at a gap, producing cleaner/less ambiguous labels
than the accumulated real-time ambiguity in long `tracking` runs, but this is
a hypothesis, not confirmed. Recorded here as a finding to dig into next,
not a claim.

Per-true-action-class recall (test set, n in parentheses): `rebase` 89.5%
(57), `keep` 75.6% (270), `promote` 67.1% (73), `abstain` 53.8% (26),
`rollback` 0% (4 — too few examples in train (46) or test (4) to expect a
learned signal; not treated as a real failure yet). Confusion matrix's
single largest error mode: `keep`↔`promote` (keep predicted as promote 60
times, promote predicted as keep 21 times) — the dominant place to look next
if pursuing the `keep`/`promote` confusion thread.

## New local artifacts (not yet in this repo — see below)

- `anchor_v3/losses.py`, `tools/train_anchor_v3.py` — NaN fix (patched)
- `tools/monitor_training_gpu.sh` — GPU/liveness watchdog, polls every 15s,
  warns on low free GPU memory, logs an ALERT + last-known state if the
  training process disappears unexpectedly
- `tools/evaluate_anchor_v3.py` — test-split loss + accuracy evaluator
- `tools/breakdown_test_eval.py` — per-teacher-stream / per-action-class
  error breakdown
- `reports/train_run2.log`, `reports/train_run3.log` — full training logs
- `reports/anchor_v3_baseline_checkpoint.pt`, `reports/
  anchor_v3_baseline_normalizer.json` — epoch-2 checkpoint (best val_total)
- `reports/TEST_EVAL_baseline_epoch2.json`, `reports/
  TEST_EVAL_breakdown_epoch2.json` — raw evaluation output

Copies of the code changes and result JSONs are included under `code/` and
`artifacts/` in this investigation folder. The full `anchor_v3/` package
(`contract.py`, `dataset.py`, `model.py`, `tensorize.py`, `teacher.py`,
`oracle.py`, `normalization.py`) predates this session and is not re-published
here — only the two files actually changed this session.

## Next

Two candidate directions, not yet decided between:
1. Dig into the `keep`/`promote` confusion cases specifically (largest single
   error mode found).
2. Design blind-recovery / stop-gate-related offline metrics (deferred from
   this session — needs grounding in the actual runtime semantics first).

No runtime integration, EP scheduling, or existing NaVILA environment change
happened this session — same boundary as `HANDOFF.md`.
