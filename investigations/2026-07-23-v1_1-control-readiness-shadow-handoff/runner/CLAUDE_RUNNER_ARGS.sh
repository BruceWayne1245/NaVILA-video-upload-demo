#!/usr/bin/env bash

# Source this file from the Route-1 batch runner. It defines arguments only and
# never launches an episode or edits the live NaVILA source tree.

V11_RUNTIME_ROOT="/home/teambruce/navila-reliability-v1_1"
V11_PORTABLE_ARTIFACT="${V11_RUNTIME_ROOT}/artifacts/reliability_v1_1_portable_shadow.json"
V11_DECISION_POLICY="${V11_RUNTIME_ROOT}/configs/v11_decision_shadow_v1.json"
V11_CONTROL_READINESS_GATES="${V11_RUNTIME_ROOT}/configs/v11_control_readiness_gates_v1.json"

V11_DECISION_SHADOW_ARGS="--reliability_v11_online_shadow"
V11_DECISION_SHADOW_ARGS+=" --reliability_v11_runtime_root=${V11_RUNTIME_ROOT}"
V11_DECISION_SHADOW_ARGS+=" --reliability_v11_portable_artifact=${V11_PORTABLE_ARTIFACT}"
V11_DECISION_SHADOW_ARGS+=" --reliability_v11_decision_shadow"
V11_DECISION_SHADOW_ARGS+=" --reliability_v11_decision_policy=${V11_DECISION_POLICY}"

v11_decision_shadow_require_sha() {
  local path="$1"
  local expected="$2"
  local actual
  actual="$(sha256sum "${path}" | awk '{print $1}')"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "[v11-decision-shadow] FATAL hash mismatch: ${path}" >&2
    echo "[v11-decision-shadow] expected=${expected} actual=${actual}" >&2
    return 1
  fi
}

v11_decision_shadow_preflight() {
  v11_decision_shadow_require_sha \
    "${V11_RUNTIME_ROOT}/reliability/v11_runtime.py" \
    "cedd63bdf3ffb87e32e6e3ee22538656412b10f84edf738c9f438461c4fba05c" \
    || return 1
  v11_decision_shadow_require_sha \
    "${V11_RUNTIME_ROOT}/candidate/scripts/reliability_v11_portable_runtime.py" \
    "7b177ffeeac878ce4125c28f4113c425db4680b028edb81345f0919d87854285" \
    || return 1
  v11_decision_shadow_require_sha \
    "${V11_PORTABLE_ARTIFACT}" \
    "3fa7fe22cd5427fdabd19646361a88f0ef24942e64289280e0339268e6bf131a" \
    || return 1
  v11_decision_shadow_require_sha \
    "${V11_DECISION_POLICY}" \
    "f4199af4559e3ba70c1bdf23a4342129e2260c4b2785c6c4033acb8e4b08684b" \
    || return 1
  v11_decision_shadow_require_sha \
    "${V11_CONTROL_READINESS_GATES}" \
    "2cbd74ff099b1865b64091b3643c54fd4723cbb16da70cd3aa7e8130cea835bf" \
    || return 1
  v11_decision_shadow_require_sha \
    "${V11_RUNTIME_ROOT}/tools/validate_v11_shadow_jsonl.py" \
    "72d6b7776f9faf72b0503b7fc54a8ac411fc50c1076d1b724d05411b8fa42879" \
    || return 1
  v11_decision_shadow_require_sha \
    "${V11_RUNTIME_ROOT}/tools/score_v11_control_readiness.py" \
    "1d113f313d859706e07f662617c943a8a19c8864d7205b23486a0e93d7353687" \
    || return 1
  echo "[v11-decision-shadow] PASS: frozen runtime, artifact, policy, gates, and scorer"
  echo "[v11-decision-shadow] PASS: enforcement=False controller_effect=False identity_override=False"
}
