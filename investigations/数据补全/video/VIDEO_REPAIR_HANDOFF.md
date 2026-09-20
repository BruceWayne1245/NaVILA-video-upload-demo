# Video repair handoff

更新时间：2026-09-20

这份文档用于在另一台电脑上继续修复并重新生成 supplementary video。目标是从原始视频和 CSV 数据重新渲染，不能在已有 MP4 上用颜色遮罩或像素涂抹修补。

## 第二次修订（2026-09-20）

最新视频：`investigations/数据补全/video/final_v2_source_render_fix_20260920_r2.mp4`。它从原始评估视频和 CSV 重新渲染，未在现有 MP4 上涂抹；第一次生成的 `final_v2_source_render_fix_20260920.mp4` 保留供对照。

- SHA-256：`a92ee2be6d80c467db9b7a934903c5be1b28bdb376d3feb31a29bd1c4e3ec467`。
- `ffprobe`：H.264、1920×1080、25 fps、176.36 秒、116,842,504 字节。
- 小地图下的蓝色配置标签关闭了偏移阴影。对四组代表性原始帧直接比较新旧 `draw_overlay()`，差异仅在标签的 y=254–267 像素行，其他文字与画面像素一致。
- 约 28 秒 / Segment 1 / step 2305：左侧只显示绿色向前箭头；右侧显示绿色向前箭头和红色右前方箭头。
- Segment 2 / step 2005（旧片约 1:26）的暂停、圆圈、箭头和字幕动画全部移除。该段原始分段帧数从 634 减少到 609，只保留 step 2480 的终止暂停。
- Segment 3 / step 2155（旧片约 1:52）：左侧只显示绿色右前方箭头；右侧显示绿色右前方箭头和红色向前箭头。
- 两处保留的 override 暂停都按同一语义绘制：原始方向为绿色，overridden 后的方向为红色。已抽帧核对新成片；没有改变其他暂停、状态文字、地图或转场的绘制规则。

对应的版本化渲染代码与复现说明在 [`code/repair_r2/`](code/repair_r2/README.md)。这次版本使用独立的中间目录和新成片文件名，旧视频与旧脚本均保留。下方首次修订的记录仅描述旧版 `final_v2_source_render_fix_20260920.mp4`。

## 完成记录（2026-09-20）

已在装有 `/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/` 的电脑上找到本片所需的 8 组原始评估视频，以及匹配的轨迹 JSONL、overlay CSV 和 5 组地图。已从这些原始输入重新渲染并合成：

`investigations/数据补全/video/final_v2_source_render_fix_20260920.mp4`

- SHA-256：`2dfaefb5eaa13f9e0a9b8e7fd2104ca783a17a382de62068f11959fea7798b82`
- `ffprobe`：H.264、1920×1080、25 fps、177.88 秒、116,765,521 字节。
- Segment 2 / ep33 的 step 1905 已无暂停；保留的暂停在 step 2005、2480。
- Segment 3 / ep1006 的 step 2155 暂停只在右侧显示绿色向前箭头；另一个暂停在 step 4130。
- 抽帧检查了原始 `vlm_action_raw` 文字、红色终止状态文字、移除的暂停和箭头。旧版 MP4 均未覆盖。

这次成片使用本机独立工作目录中的脚本副本。当前仓库的 `overlay_lib.py` 在 step 2155 的箭头逻辑与成片仍有差异：它会从左侧 baseline 的 `vlm_action_raw` 取方向，并在两侧绘制多余的箭头。要复现成片，应在该步隐藏左侧箭头，且仅用右侧 online 的 `vlm_action_raw` 绘制绿色向前箭头。此处记录差异，避免以后误以为仓库脚本能逐帧复现已上传视频。

## 当前仓库

- Repository: `BruceWayne1245/NaVILA-video-upload-demo`
- Video directory: `investigations/数据补全/video/`
- Existing final video: `final_v2.mp4`
- Existing later candidate: `final_v2_redtext_transition_fixed.mp4`
- Existing compatible playback copy: `final_v2_redtext_transition_fixed_compatible.mp4`
- These existing MP4 files must not be overwritten.

## User-requested corrections for the next render

1. The bottom-right `VLM:` text must show the model's original output, from the CSV field `vlm_action_raw`, rather than the compact/post-processed `vlm_action` label.
2. Red bold status text is still difficult to read. Render it with a lighter stroke, reduced size, anti-aliasing, and no excessive shadow/thickness. Red regular text and green regular text are already acceptable.
3. Remove the first pause in Segment 2, including its freeze, circle, caption, and arrows.
4. In the first pause of Segment 3, swap the red/green arrow semantics and remove the forward-pointing arrow from the left panel.

## Code changes already made locally

Modified files:

- `investigations/数据补全/video/code/overlay_lib.py`
- `investigations/数据补全/video/code/render_segments_v2.py`

Implementation details:

- `draw_overlay()` now displays `vlm_action_raw` with a `VLM:` prefix and dynamically fits the original text to the panel width.
- Terminal and distance text use a lighter stroke (`thickness=1`) and smaller bold scale; the distance circle also uses anti-aliased one-pixel rendering.
- Segment 2 / ep33 excludes event step `1905` through `exclude_steps=(1905,)`.
- Segment 3 / ep1006 uses an explicit source-render override at step `2155`:
  `{"force": True, "swap_colors": True, "hide_left": True}`.
- `render_pair_side_by_side()` supports per-step arrow overrides.

The modified Python files passed `py_compile` and AST syntax checks.

## Previous-machine blocker (resolved on the rendering computer above)

The local machine currently has no source inputs required by `render_segments_v2.py`:

- no `investigations/数据补全/video/_raw/` source clips;
- no `/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/` mount;
- no source clips such as `output_1005.mp4`, `output_1255.mp4`, `output_32.mp4`, `output_427.mp4`, or `output_1438.mp4`.

The GitHub repository was checked on both `main` and `codex/2026-07-29-daily-handoff`. It contains final/processed videos and overlay CSVs, but not the raw evaluation videos required for a genuine source-level re-render.

Do not use `segments_v2/*.mp4` as the input for this task: those files already contain rendered overlays and would cause a second-generation pixel edit.

## Required next steps on the other computer

1. Locate or mount the original evaluation result directory used by the scripts. It must contain the raw episode videos and trajectories.
2. Confirm that these paths exist, or update the `BENCH` and `REPO` constants in `render_segments_v2.py`:

   - `output_1005.mp4` for ep1006 baseline/online;
   - `output_1255.mp4` for ep1256 oracle-hint/action;
   - `output_32.mp4` for ep33 hint-action/stopgate;
   - `output_427.mp4` for ep428;
   - `output_1438.mp4` for ep1439;
   - matching `trajectories/output_*.jsonl` files;
   - map files under `topdown_maps/`.

3. Run the source render with the environment that provides OpenCV:

   ```bash
   cd /path/to/NaVILA-video-upload-demo
   python3 investigations/数据补全/video/code/render_segments_v2.py
   ```

4. Compose a new final video with `compose_final_v2.py`. Update its `REPO` constant if the checkout is not at the hard-coded path.
5. Use a new filename, for example:

   `investigations/数据补全/video/final_v2_source_render_fix_20260920.mp4`

   Never replace `final_v2.mp4` or any earlier candidate.

6. Verify with `ffprobe` and frame extraction around:

   - Segment 2 first pause: no freeze, circle, caption, or arrow;
   - Segment 3 first pause: only the intended right-side forward arrow remains, with corrected color;
   - all red terminal/distance text;
   - every right-side `VLM:` field, which must match `vlm_action_raw`;
   - all segment transitions and bottom status bars.

7. Upload only the new MP4 and this handoff/documentation change. Do not commit credentials or tokens.

## Authentication note

A GitHub personal access token was supplied in the chat during the previous work. It must not be written into this file, shell history, Git config, or the repository. Revoke that exposed token and use a newly generated credential on the other computer.
