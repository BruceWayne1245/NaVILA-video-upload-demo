# Code and provenance

## GitHub source of truth

- Model-development baseline: `c1d40e079a53dfb3efca895e19d17db991f0ffb6`.
- Private-repository `main` refreshed before this archive update:
  `f2a61a9b5cc94624e1126ccbcf674d58139ef59d`.
- The newest GitHub README and code always override any local snapshot.

The source baseline is recorded rather than rewritten: V1/V1.1 results must
remain attributable to the code on which they were built. A future runtime
integration must start from the newest GitHub commit, port the selected model
deliberately, and rerun parity tests.

## V1 frozen provenance

| Item | Value |
|---|---|
| Isolated commit | `a9be230a2b38dd52dd308648e899911041ad91d4` |
| Tag | `reliability-v1-offline-audit-8f2097ec` |
| Dataset rows | 91,003 |
| Dataset SHA-256 | `8f2097ec50287d6c4b4bca71adba9563275483fee020e608e65f0d8ac6028b78` |
| sklearn artifact SHA-256 | `3fc7c2ebc6f2732ab787c137c31d1e54b2883c658858daafb5a82a78eef0eab2` |
| portable JSON SHA-256 | `b6bdd0cda5a414a61fbcad27912d6edab8790846d73c5cb84f3a1433ff40d9c2` |

Earlier isolated milestones were `fb5cb9d` (baseline), `1bf20b0` (shadow
integration), and `5567af6` (portable runtime). The final audit commit is the
only V1 snapshot to use.

V1 archive layout:

- [`model_versions/v1/reliability/`](model_versions/v1/reliability/) — schema,
  labels, vectorizer, training, calibration, replay, policy, portable export,
  and audit code;
- [`model_versions/v1/tools/`](model_versions/v1/tools/) — build, train, replay,
  audit, isolation, and smoke entry points;
- [`model_versions/v1/tests/`](model_versions/v1/tests/) — model/audit/runtime
  locks;
- [`model_versions/v1/candidate_runtime/`](model_versions/v1/candidate_runtime/)
  — the exact relevant candidate integration files, kept outside live code;
- [`model_versions/v1/reports/`](model_versions/v1/reports/) — full machine and
  human reports;
- [`model_versions/v1/artifacts/`](model_versions/v1/artifacts/) — frozen
  sklearn and dependency-free artifacts.

## V1.1 frozen provenance

| Item | Value |
|---|---|
| Parent V1 commit | `a9be230a2b38dd52dd308648e899911041ad91d4` |
| Isolated commit | `bb457488653e386b284bef8e1bcb6f45094d8868` |
| Tag | `reliability-v1.1-development-f5dd5ed8` |
| Dataset rows/features | 91,003 / 249 |
| Dataset SHA-256 | `f5dd5ed86e776f9c3ae8efc6e8a2e9f8f1bcce8b0f793dc16115dc7d80494133` |
| Development artifact SHA-256 | `5f23aba46a45d564131dccd093b1e76160a513162910709503ac8c0a49cb35ce` |
| Artifact flags | `development_only=true`, `prospective_validation_passed=false` |

V1.1 archive layout mirrors V1 so it can be inspected independently. The
V1.1-specific implementation is concentrated in:

- [`diagnostics.py`](model_versions/v1_1/reliability/diagnostics.py);
- [`v11_dataset.py`](model_versions/v1_1/reliability/v11_dataset.py);
- [`v11_training.py`](model_versions/v1_1/reliability/v11_training.py);
- [`v11_validation.py`](model_versions/v1_1/reliability/v11_validation.py);
- the matching `build_v11_dataset.py`, `diagnose_v1_shift.py`,
  `train_v11_nested.py`, and `validate_v11_artifact.py` tools;
- the four `test_v11_*`/diagnostic tests and all V1.1 reports.

`model_versions/v1_1/candidate_runtime/` is intentionally the inherited V1
runtime snapshot. V1.1 runtime feature-state construction and portable export
have **not** been implemented. Its presence documents the parent boundary; it
must not be described as a V1.1 online integration.

## Derived datasets not committed

| Dataset | Local size | SHA-256 | Rebuild entry point |
|---|---:|---|---|
| `reliability_v1.csv` | 55,706,151 bytes | `8f2097ec50287d6c4b4bca71adba9563275483fee020e608e65f0d8ac6028b78` | `model_versions/v1/tools/build_dataset.py` |
| `reliability_v1_1.npz` | 62,267,080 bytes | `f5dd5ed86e776f9c3ae8efc6e8a2e9f8f1bcce8b0f793dc16115dc7d80494133` | `model_versions/v1_1/tools/build_v11_dataset.py` |

The full dataset manifests are committed. Rebuilding requires the original
evaluation-log paths recorded in those manifests.

## Reproduction notes

Use a fresh environment for each archived version. Never point the archived
candidate runtime at enforcement switches.

V1:

```bash
cd model_versions/v1
python -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python tools/build_dataset.py
.venv/bin/python tools/train_bundle.py
.venv/bin/python tools/replay_cases.py
.venv/bin/python tools/offline_audit.py
.venv/bin/python -m pytest -q tests
```

V1.1, after first rebuilding/copying the V1 CSV into its expected processed
data path:

```bash
cd model_versions/v1_1
python -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python tools/diagnose_v1_shift.py
.venv/bin/python tools/build_v11_dataset.py
.venv/bin/python tools/train_v11_nested.py
.venv/bin/python tools/validate_v11_artifact.py
.venv/bin/python -m pytest -q tests
```

The copied V1.1 repository README still contains inherited V1 paths in its
example command block. It is retained as a provenance snapshot; the corrected
archive-relative commands above are authoritative for this GitHub archive.
