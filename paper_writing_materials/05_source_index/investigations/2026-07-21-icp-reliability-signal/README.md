# ICP reliability investigation archive

This directory is the canonical GitHub archive for the 2026-07-21 ICP
reliability work. It combines the original scalar-signal feasibility study with
the independently isolated Reliability V1 and V1.1 model experiments.

## Current decision

- A reliability model belongs **after each sequential-pair ICP estimate and
  before tracker promotion/quarantine, hint arbitration, and stop authority**.
- It predicts three per-reading risks: bearing error greater than 30 degrees,
  anchor-distance error greater than 0.5 m, and either error (pose risk).
- V1 retains useful ranking power but fails every trusted-set risk gate and
  remains shadow-only.
- V1.1 is substantially stronger on historical nested out-of-fold evaluation,
  but all historical runs are now development data. It is also shadow-only and
  has not yet been prospectively validated.
- Neither version is authorized to change navigation, stopping, anchor
  identity, promotion, or quarantine.

## Read in this order

1. [`FINDINGS.md`](FINDINGS.md) — original signal feasibility study and the
   scalar-feature ceiling found before V1/V1.1.
2. [`MODEL_WORK_SUMMARY.md`](MODEL_WORK_SUMMARY.md) — all model work, metrics,
   limitations, and the fair V1/V1.1 comparison.
3. [`CODE_AND_PROVENANCE.md`](CODE_AND_PROVENANCE.md) — exact source, artifact,
   dataset, commit, and archive boundaries.
4. [`NEXT_STEPS.md`](NEXT_STEPS.md) — work that is frozen, running elsewhere,
   or still waiting to start.
5. [`PUBLICATION_VALIDATION.md`](PUBLICATION_VALIDATION.md) — archive integrity,
   test, isolation, and artifact checks performed before publication.
6. [`MODIFICATION_PLAN.md`](MODIFICATION_PLAN.md) — the parallel heuristic-gate
   plan. This is not the same as enabling either learned model.

## Version snapshots

| Version | Snapshot | State | Runtime status |
|---|---|---|---|
| V1 | [`model_versions/v1/`](model_versions/v1/) | Frozen at isolated commit `a9be230` | Portable shadow smoke passed; enforcement locked |
| V1.1 | [`model_versions/v1_1/`](model_versions/v1_1/) | Frozen development candidate at `bb45748` | Offline artifact validated; V1.1 runtime integration not yet implemented |

The two snapshots are deliberately duplicated and self-contained. They must
not be overlaid on each other or copied wholesale into live navigation. Any
future integration must select one frozen version, rebase it deliberately onto
the then-current authoritative GitHub code, and repeat parity tests.

## Authoritative-code boundary

V1 and V1.1 were developed from the GitHub baseline
`c1d40e079a53dfb3efca895e19d17db991f0ffb6`. Before publishing this archive,
the authoritative private-repository `main` and README were refreshed at
`f2a61a9b5cc94624e1126ccbcf674d58139ef59d`.

The later commits contain a separate gating diagnosis, Injection-A candidate,
and capture subsystem under
[`../2026-07-21-gating-diagnosis-fix-and-capture/`](../2026-07-21-gating-diagnosis-fix-and-capture/).
Those changes are **not silently merged into either model snapshot**. This
boundary is intentional: GitHub's newest README/code remains authoritative,
and future runtime work must reconcile the model with that newer capture and
navigation state explicitly.

## Data and artifact policy

The frozen model artifacts, source, tests, reports, plots, and dataset manifests
are committed here. The 54 MiB V1 CSV and 60 MiB V1.1 NPZ are deterministic
derived datasets and are not duplicated in GitHub; their builders and exact
SHA-256 values are included. Raw evaluation logs remain in the project data
store and are not copied into this investigation.
