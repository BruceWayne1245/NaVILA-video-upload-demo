# NaVILA Reliability V1

This directory is an isolated reliability-model experiment. It is not imported
by, copied over, or linked into the live NaVILA checkout automatically.

## Separation contract

- `upstream_snapshot/` is an immutable copy of the authoritative live files at
  the baseline recorded in `BASELINE.md`.
- `candidate/` is the only copy of the navigation scripts that may be edited.
- `reliability/` contains the model, feature schema, temporal policy, and replay
  code used by the candidate scripts.
- `data/processed/`, `artifacts/`, and `reports/` belong only to this experiment.
- No symbolic links are permitted. Run `python tools/verify_isolation.py` before
  training or testing.
- Nothing in this repository writes to the live source path.
- Isaac's configuration loader is path-coupled to the canonical Bench scripts
  directory. The smoke runner solves this with a process-local, read-only
  `bwrap` mount: the candidate scripts appear at the expected path only inside
  that namespace. The host files remain unchanged and hash-verified.

## Planned pipeline

1. `tools/build_dataset.py` reconstructs three labels and episode-balanced
   weights from the configured evaluation batches.
2. `tools/train_bundle.py` trains, calibrates, and evaluates the three-head model
   bundle with chronological batch separation.
3. `tools/replay_cases.py` performs counterfactual replay for pinned-current and
   stop-decision cases.
4. `tools/offline_audit.py` evaluates the frozen artifact with raw-label checks,
   episode/scene macro metrics, cluster-bootstrap confidence intervals,
   risk-coverage curves, and a scalar ICP baseline.
5. The candidate navigation scripts initially run the estimator in shadow mode.
   Enforcement is protected by separate, default-off consumer switches.

The live project remains the source of truth for runtime experiments. Promotion
of this candidate back to the live project must be a deliberate, reviewed copy
operation outside this repository.

## Reproduce the current result

```bash
cd /home/teambruce/navila-reliability-v1
python -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
python tools/verify_isolation.py
.venv/bin/python tools/build_dataset.py
.venv/bin/python tools/train_bundle.py
.venv/bin/python tools/replay_cases.py
.venv/bin/python tools/offline_audit.py
.venv/bin/python -m pytest -q tests candidate/tests/test_route_memory_agent.py \
  candidate/tests/test_stop_gate.py candidate/tests/test_geometry_pipeline.py
bash tools/run_shadow_pilot_ep20.sh
```

The candidate simulator can load the artifact with:

```text
--reliability_model_path /home/teambruce/navila-reliability-v1/artifacts/reliability_v1_portable.json
--reliability_mode shadow
```

There is intentionally no enforcement mode in this version. See
`reports/ACCEPTANCE_GATES.md` for the failed safety gates that must be cleared
by a prospective batch first.

The last command is a 20-second-return smoke test, not a benchmark. It uses a
full canonical outbound phase only to reach live sequential-pair inference,
then validates artifact loading, structured shadow records, enforcement locks,
and latency. See `reports/SHADOW_SMOKE_REPORT.md`.
