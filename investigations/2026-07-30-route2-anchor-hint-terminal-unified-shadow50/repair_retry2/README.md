# Unified Shadow50 retry2 repair

Date: 2026-07-30

## Defects repaired

### 1. Python package collision

Retry1 imported `reliability.anchor_transition_online` after the evaluator had
already imported the established V1.1 `reliability` package from a different
root.  Inserting another root into `sys.path` cannot extend an already-loaded
regular package, so the Anchor module was invisible.

The Anchor runtime now lives under the unique
`anchor_transition_runtime` package.  Its promotion-guard logic is unchanged,
and the frozen model/feature/threshold behavior is verified by the existing
exact-parity test.

### 2. False evaluator exit code 0

Isaac/Kit shutdown can terminate a process as status 0 after the evaluator has
already printed a fatal Python traceback.  The driver now:

- treats `[fatal_evaluator_exit]` in the evaluator log as failure;
- requires a valid `capture_completion.json`;
- verifies episode identity, complete flag, measurement presence and SHA-256,
  trajectory presence, and positive trajectory row count;
- records distinct nonzero infrastructure codes instead of a false success;
- runs the canary fail-fast;
- lets fresh49 continue auditing later episodes, but marks the overall service
  failed and writes `NEEDS_INFRA_RETRY` if any episode lacks a valid capture.

### 3. Queue race across renamed Route 1 services

Route 1's first unseen30 service was stopped and replaced by the corrected
`unseen30v2` service.  Waiting on the old systemd unit alone could therefore
start Route 2 during a between-episode GPU gap.

The queue wrapper now waits until all known Route 1 units, matching master
drivers, and matching evaluator processes have ended.  It then additionally
requires at least 12,000 MiB free GPU memory before starting retry2.

## Frozen experiment inputs

No experiment member, learned model, threshold, decision gate, or consumer
authority changed:

- manifest:
  `4019465c954882b2190fe7ae01d9368c767e402cd75100053418b01a3cafbbfa`;
- Anchor V1:
  `4d37f9bcb341f093d4cdc87e92c041db7d582a912acdb629963039cf7b27dc55`;
- Hint v3:
  `21035c66e2748e3bc54f34ee849c6020ab113bf86906a8ce4460d51d41ef26f5`;
- Terminal robust v2:
  `f033696bf632134c48edf3ce1734850833c98a93bfdadc7173780ef5ebef6bbb`;
- Anchor mode remains `shadow`;
- all V1.1 learned consumers remain off;
- Hint and Terminal remain post-episode read-only;
- `control_effect=none`.

Retry2 uses new result tags and never overwrites either failed attempt:

- canary: `unified_shadow50_ep670_replication_retry2_20260730`;
- fresh batch: `unified_shadow50_fresh49_retry2_20260730`.

## Verification

- 50 focused tests passed.
- Python sources compiled.
- all shell scripts passed `bash -n`;
- static frozen-cohort preflight passed;
- a real import test preloaded the established V1.1 `reliability` package and
  then successfully imported `anchor_transition_runtime`;
- the loaded Anchor model SHA-256 matched the frozen value.

## Repair artifact hashes

| Artifact | SHA-256 |
|---|---|
| Anchor package init | `2d29bbcd68605f1e04b211295ba99d2147a017b69ce328bc4c133d4818f1cd77` |
| Anchor online runtime | `ac70bf4b5da95d27f48a109522a9ad3a390e371dc380d234387b2b215d59cd49` |
| Promotion guard | `8afa155ace32aac3c0971e297bdef22835a11c05e697e369b0ea49dce89f86d1` |
| Evaluator candidate | `5e6ba9413c59087403078ad578bc9e75a6eaec144ad3f2c3100e471be803a70c` |
| Capture validator | `aaebc0f1f86bc468750d34e4a20ee90f309b424d8cbed78d61be76f0f41976af` |
| Manifest driver | `8a11cd8385abb2aa53e34798e7f18114ae6fcd87c8926c7dffd54b31dc73fb54` |
| Retry2 runner | `f939cdecceeba6611f7cec3bf7076b1d92de3d13fdf9f3bfabca1c23f37cb2ea` |
| Route1 wait wrapper | `5c53d08952b7373764da7ef415d1a898d56a26d4ae6ad5da0f711882bce9f0e2` |

Exact source and tests are archived under this directory.
