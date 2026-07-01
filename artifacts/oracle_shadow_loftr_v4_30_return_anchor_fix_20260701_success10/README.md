# Oracle-shadow LoFTR v4-30 return-anchor-fix success10

Date: 2026-07-01

This artifact contains the 10 successful round-trip trajectories from the 30-episode v4 baseline set run with oracle hints and non-oracle LoFTR shadow telemetry.

Run tag:

```text
oracle_shadow_loftr_v4_30_return_anchor_fix_20260701
```

Included files:

```text
summary.tsv      Full 30-episode batch summary.
per_step/        Per-step trajectory JSONL for the 10 round-trip successes.
measurements/    Measurement JSON for the same 10 episodes.
route_maps/      Route map metadata JSON plus route/occupancy PNGs for the same 10 episodes.
```

Successful round-trip episodes:

| Episode | Per-step JSONL | Records | Final distance to start |
|---:|---|---:|---:|
| 4 | `per_step/ep4_output_7.jsonl` | 2727 | 1.118 m |
| 368 | `per_step/ep368_output_602.jsonl` | 3552 | 1.335 m |
| 993 | `per_step/ep993_output_1698.jsonl` | 4452 | 1.392 m |
| 187 | `per_step/ep187_output_280.jsonl` | 5402 | 1.832 m |
| 678 | `per_step/ep678_output_1164.jsonl` | 4227 | 1.529 m |
| 679 | `per_step/ep679_output_1165.jsonl` | 4027 | 1.772 m |
| 680 | `per_step/ep680_output_1166.jsonl` | 4877 | 1.552 m |
| 994 | `per_step/ep994_output_1699.jsonl` | 4352 | 1.164 m |
| 1038 | `per_step/ep1038_output_1758.jsonl` | 3352 | 2.265 m |
| 1040 | `per_step/ep1040_output_1760.jsonl` | 3727 | 2.326 m |

Total per-step records: 40695.

Each successful episode has two trajectory images under `route_maps/`:

- `*_routes.png`: top-down route overlay.
- `*_occupancy.png`: top-down occupancy map.
