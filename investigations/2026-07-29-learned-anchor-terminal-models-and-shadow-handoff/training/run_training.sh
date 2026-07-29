#!/usr/bin/env bash
set -euo pipefail

# Train with the same scikit-learn build used by the Isaac/VLN-CE runtime.
# Joblib estimators are not guaranteed to be portable across sklearn versions.
PYTHON="/mnt/SSD4T/teambruce/conda_envs/vlnce-isaac/bin/python"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

exec "${PYTHON}" "${ROOT}/training/train_models.py" "$@"
