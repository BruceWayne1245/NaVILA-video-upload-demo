# Isolated live shadow smoke report

- Date: 2026-07-21
- Episode index / ID: 20 / 33
- Mode: shadow, enforcement locked
- Model: `reliability-v1-8f2097ec5028`
- Artifact: `artifacts/reliability_v1_portable.json`
- Runtime isolation: process-local read-only `bwrap` overlay; canonical host
  source hashes unchanged after the run
- Scope: full outbound plus deliberately shortened 20-second simulated return;
  this is a plumbing/latency smoke test, not an outcome benchmark

## Result

The run completed with exit code 0 and generated a measurement containing 201
inference calls and 402 candidate records. All records had `status=trusted`.
No `enforced_*` field was true. Recommendations were emitted but did not alter
navigation: 219 hint blocks, 280 stop-authority deferrals, 41 promotion blocks,
and 20 current-eviction recommendations.

Portable runtime latency was 457.977 ms total, 2.278 ms mean per call, 1.139 ms
mean per candidate, and 2.480 ms maximum per call.

The navigation outcome was outbound success and return failure after the
shortened cap (`distance_to_start=5.942 m`). It must not be compared with the
canonical 100-second return benchmark.

Measurement:

`/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_reliability_v1_shadow_smoke_ep20_overlay_20260721_ep20/measurements/32.json`
