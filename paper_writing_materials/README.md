# Paper-writing materials

This folder is a curated, copy-only evidence package for drafting the NaVILA
project paper. The original repository files are unchanged; paths inside this
folder preserve their original repository-relative locations so that claims can
be traced back to the source.

## Contents

- `00_project_overview/`: root README, project-plan/advisor materials, and the
  original progress-report documents.
- `01_problem_and_method/`: the July 6–20 investigations covering anchor
  selection, ICP aliasing, bearing error, belief fusion, promotion, stop-gate
  behavior, and failed alternatives.
- `02_reliability_and_evaluation/`: the July 21–24 reliability work, shadow
  handoff, prospective evaluation protocol, and the 63% baseline evidence.
- `03_route2_models_and_current_status/`: the July 25–August 2 model,
  controller, Route 2, runtime-forensics, and current-plan documents.
- `04_key_data_and_reports/`: selected tables, manifests, JSON summaries,
  calibration evidence, and model-training reports that directly support
  quantitative claims.
- `05_source_index/`: the broader narrative-document index copied from the
  top level of `investigations/`; use it to locate secondary context that was
  not placed in the main evidence sequence.

## Reading order

1. Read `PROJECT_CONTEXT_FOR_WEB_MODEL.txt` at the repository root.
2. Read `00_project_overview/README.md`.
3. Read the dated documents in `01_problem_and_method/` chronologically.
4. Read the reliability/evaluation package in `02_reliability_and_evaluation/`.
5. Read the latest Route 2 documents in `03_route2_models_and_current_status/`,
   especially the August 2 full-active plan and live-run handoff.
6. Use `04_key_data_and_reports/` to verify numbers before putting them in the
   paper.

## Evidence conventions

The repository contains historical snapshots, shadow runs, active runs,
infrastructure failures, and superseded proposals. Do not pool metrics across
different controller snapshots or cohorts. Treat time-stamped live-status
files as snapshots rather than current host-state claims. The August 1 Core
correction supersedes the earlier V1.1-off Route 2 findings where explicitly
stated. Locked-validation cohorts are evaluation-only and must not be used for
training, feature selection, or threshold tuning.

This package intentionally excludes most implementation code, raw point-cloud
captures, full trajectory logs, large per-attempt JSON dumps, model binaries,
and credentials. Those files remain in the original repository/workspaces.
