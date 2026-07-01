# Oracle-shadow LoFTR aliasfix route maps

Date: 2026-07-01

Run tag:

```text
oracle_shadow_loftr_aliasfix_680_994_187_20260701
```

This artifact contains top-down route maps for the three-episode aliasfix check after enabling return-start progress prior, default VIO bridge, and unlimited relocalization candidate search.

Results:

| Episode | Round trip | Final distance to start | Route map | Occupancy map |
|---:|:---:|---:|---|---|
| 187 | True | 1.899 m | `route_maps/ep187_output_280_routes.png` | `route_maps/ep187_output_280_occupancy.png` |
| 680 | True | 1.457 m | `route_maps/ep680_output_1166_routes.png` | `route_maps/ep680_output_1166_occupancy.png` |
| 994 | True | 1.063 m | `route_maps/ep994_output_1699_routes.png` | `route_maps/ep994_output_1699_occupancy.png` |

Each episode also includes its `*_map_meta.json` file in `route_maps/`.
