# Reliability V1.1 prospective shadow handoff — 2026-07-22

## Status

This directory is a handoff package for the next Claude-owned 100-episode
controller run. It is **not currently chained or scheduled**. The previously
armed systemd chain was stopped and verified inactive on 2026-07-22 while the
existing fix-ON 100ep run continued normally.

The intended combined use of the next batch is:

1. Claude's finalized non-model changes remain the sole navigation controller.
2. The frozen Reliability V1.1 candidate observes the captured ICP data only.
3. V1.1 scoring is performed offline after the run; it has no online inference
   or enforcement authority.

This lets one batch provide a scale-up run for Claude's controller and a new
physical-episode prospective dataset for the model. It does **not** by itself
make a causal A/B claim for Claude's changes, because these 100 episodes have
not been run under the old controller.

## Contents

- `episodes.tsv`: the frozen 100 fresh physical CLI episode IDs and their
  deterministic reverse-path-neighbor metadata.
- `PROTOCOL.md`: the frozen model hypotheses, gates, integrity requirements,
  and analysis boundary.
- `run_batch_template.sh`: the complete runner template, including run tag,
  capture flag, provenance, preflight hashes, resume behavior, and the
  predeclared one-time retry for VLM startup `exit_code=98`.
- `CLAUDE_INTEGRATION_CHECKLIST.md`: exact steps for rebasing this template on
  Claude's finalized code/config without accidentally enabling the model.

The frozen V1.1 model source and artifact remain in
`../2026-07-21-icp-reliability-signal/model_versions/v1_1/`; they are not
duplicated here.

There is deliberately no V1.1 online runtime in this package. “Bring the
shadow” means preserving the exact replay capture and frozen experiment
contract so the archived sklearn artifact can score it offline. It must not be
silently replaced by the older V1 portable runtime.

## Frozen experiment identity

- Run tag:
  `reliability_v11_prospective_capture_shadow_100ep_20260722_accumulated`
- Episode-manifest SHA-256:
  `60d2adf33efeaeb985dc2b234a284a4698ff69160b2a284adfa0ed060b1c60c7`
- V1.1 development artifact SHA-256:
  `5f23aba46a45d564131dccd093b1e76160a513162910709503ac8c0a49cb35ce`
- Model mode: offline capture shadow; no online model inference; no model
  enforcement.
- Infrastructure retry: at most one retry after 120 seconds, and only when the
  episode row ends with VLM-server startup `exit_code=98`.

## What Claude must preserve

1. Keep `--capture_icp_replay_dataset` enabled and verify it still captures
   anchors once plus every return-phase environment step.
2. Keep the 100 episode IDs and manifest hash unchanged after results begin.
3. Keep the model artifact, feature contract, calibrators, thresholds, labels,
   exclusion rules, and prospective gates frozen.
4. Do not add a V1 or V1.1 online model path or any model enforcement flag.
5. Keep infrastructure failures and episodes with no return data in the
   operational denominator.
6. Record Claude's final controller flags and live source hashes before launch.

## What Claude is expected to change

The template currently records the exact controller flags and source hashes of
the fix-ON A+B+C batch running on 2026-07-22. Claude should merge his finalized
non-model changes into `COMMON_EXTRA`, then replace the pinned live source
hashes. If the shared batch driver's function boundary changes, he must adapt
the template rather than bypass its manifest, capture, provenance, or retry
contract.

The old hashes intentionally cause preflight to fail after live code changes.
That failure is a guardrail, not a reason to disable preflight.

## Interpretation boundary

The model's primary result is prospective bearing/distance/pose risk and
coverage on new physical episodes. Navigation success belongs to Claude's
controller and is secondary for the model. A model pass permits an online
shadow-runtime canary later; it does not authorize hint, stop, promotion,
quarantine, or current-anchor enforcement.
