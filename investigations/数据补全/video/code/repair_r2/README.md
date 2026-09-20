# Reproduce repair r2

These scripts generate `final_v2_source_render_fix_20260920_r2.mp4` from the original evaluation videos and CSV data. They are the rendering code used for this revision. The repository's older scripts and videos remain available for comparison.

Required input: the eight evaluation video and trajectory pairs named in `render_segments_v2.py` under its `BENCH` directory, plus `video/overlay_data/`, `video/topdown_maps/`, and `video/figures_raster/`. Original evaluation clips are not stored in this GitHub repository. Change `BENCH` if the source directory is mounted elsewhere.

From the repository root:

```bash
python3 investigations/数据补全/video/code/repair_r2/render_segments_v2.py
python3 investigations/数据补全/video/code/repair_r2/compose_final_v2.py
```

OpenCV and FFmpeg are required. Intermediate files go to `_raw_repair_r2/` and `segments_repair_r2/`. The composer refuses to overwrite the final MP4. This published copy differs from the local rendering copy only in the location of the script, intermediate directory names, and the overwrite guard.

Arrow semantics are explicit at the two retained override pauses: green is the original direction and red is the overridden direction. The left view shows only the original direction. Segment 2 retains only its terminal pause.
