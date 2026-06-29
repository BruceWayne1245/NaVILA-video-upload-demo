# NaVILA Return 测试数据总结合集

日期：2026-06-29

范围：本文整理目前仓库 README、源码和已上传 per-step 轨迹中记录过的 round-trip / return 相关实验。重点不是只列成功率，而是按“每一批 episode 使用的代码环境是什么、轨迹里具体发生了什么、成功/失败大致说明了什么”来组织，方便后续总体判断这些数据到底支持什么结论，以及下一步应该优先改哪里。

主要代码和数据位置：

- 主评测入口：`code/round_trip_eval.py`
- route memory / hint 逻辑：`code/route_memory_agent.py`
- relocalization 后端：`code/relocalization.py`
- oracle-anchor batch：`artifacts/oracle_anchor_hard_batch_20260629/`
- direct oracle + yaw batch：`eval_results/...direct_oracle_align_yaw_hard_20260629_ep*/`
- stop-gate oracle batch：`artifacts/stop_gate_oracle_hard_batch_20260629/`
- no-hint baseline batch：`artifacts/no_hint_hard_batch_20260629/`
- LoFTR batch：`artifacts/loftr_depth_hard_batch_20260628/`
- route-memory 早期 batch：`results/route_memory_batch_10_20260626/`

注意：README 记录了 `ReturnStopGate`，stop-gate 轨迹里也有 `stop_gate` 字段，但当前私人仓库快照里没有对应的 `code/stop_gate.py` 源文件。因此本文对 stop-gate 的代码解释主要来自 README 和 per-step 轨迹字段，而不是直接源码审计。

## 1. 总体结论

目前所有数据放在一起看，最重要的结论有五个。

1. **NaVILA/VLM 本身已经有不弱的视觉 return 能力。**  
   最新 no-hint hard batch 在没有 route-memory hint、没有 oracle yaw align、没有 stop gate 的情况下，11 个 hard episode 里 round trip 成功 `4/11`。ep5、ep680、ep994、ep1040 都能靠纯视觉返回成功。

2. **oracle/hint 确实能影响 VLM 输出，但不能等价于 local planner。**  
   direct oracle 轨迹里能看到 `source="direct_oracle_route_anchor"`，动作分布也会随 hint 改变，说明 prompt 被模型使用了。但在狭窄室内环境里，几何上正确的 anchor bearing 经常不是局部可走方向；机器人会撞墙、原地卡住、左右震荡，或者为了对齐 anchor 放弃视觉上更可行的走法。

3. **stop gate 只能解决“该不该 stop”的问题，不能解决“怎么走回去”。**  
   ep368 和 ep1040 说明 gate 可以把已经接近起点但 VLM 没有正确 stop 的情况救回来。但 ep187、ep994 中 gate veto 了很多次 stop，机器人仍然没回到起点，甚至继续走远。

4. **非 oracle route memory 的核心瓶颈仍然是 relocalization 和 viewpoint overlap。**  
   ORB/SIFT 太弱；LoFTR+depth 在 ep994 单跑和修复版里能成功，但 hard batch 不稳定。后半程经常因为前向相机视角和 outbound anchor 视角相反而没有共视，走廊平面结构也会造成沿走廊方向的位姿退化。

5. **现在缺的是“全局 route progress”和“局部可行运动”之间的一层。**  
   route memory / oracle 应该提供“沿反向路线的进度和大致目标”，而不是直接让 VLM 把某个 anchor bearing 当成 steering 目标。下一步更应该补 local feasibility、stuck/contact 检测、局部 waypoint 或 corridor-following 策略。

## 2. 通用评测设定

后期大多数实验的共同设置：

- task：`go2_matterport_vision`
- policy run：`2024-09-25_23-22-02`
- round-trip mode：`phase_prompt`
- instruction provider：`cache_only`
- Isaac headless + camera
- 2026-06-26 修复后 return success 半径主要为 `3.0 m`
- outbound success 表示成功到达并停在 outbound goal 附近
- return success 只在 outbound 成功后才有解释意义
- round-trip success 要求 outbound 和 return 都成功

hard subset 主要 episode：

`4, 5, 134, 187, 367, 368, 408, 678, 680, 994, 1040`

这些 episode 大多来自早期 30 episode baseline 中“outbound 成功但 return 失败”的样本，因此更适合研究 return，而不是研究 outbound。

## 3. 按实验批次整理

### 3.1 episode 0 与早期 v4 baseline

目的：

- 验证 Isaac、VLM server、round-trip evaluator、phase prompt 跑通。
- 看自然 return pose 和更强 oracle reset 对 return 的影响。

代码/环境：

- 早期 `round_trip_eval.py` phase-prompt workflow。
- v4 reverse-path instruction 来自相邻 episode。
- 部分测试使用 `--oracle_return_pose` 强制 return 开始时恢复更准确的 pose。

结果和轨迹现象：

- episode 0 v4 baseline 多次接近阈值成功，final distance 大约 `1.995-2.000 m`。
- 但强 oracle reset 后也可能失败，final distance 可到 `13.295 m`。

说明：

- return 失败不只是 outbound 过程中 pose drift 累积造成的。
- 即使 simulator pose 重置准确，VLM 在 return 开始后的视觉状态和动作序列仍然可能把机器人带偏。

### 3.2 v4 random / 30-episode baseline

目的：

- 看 episode 0 的成功是否能泛化。
- 找出 outbound 成功但 return 失败的 hard cases。

代码/环境：

- `phase_prompt`
- `cache_only` reverse-path instruction
- 无 route memory、无 relocalization、无 stop gate
- README 中对应脚本：`scripts/run_v4_batch_10_20260618.sh`、`scripts/run_v4_batch_20_20260618.sh`

聚合结果：

| Batch | Runs | Outbound | Return | Round trip |
|---|---:|---:|---:|---:|
| Batch A | 10 | 3 | 2 | 0 |
| Batch B | 20 | 11 | 3 | 3 |
| Combined | 30 | 14 | 5 | 3 |

轨迹现象：

- 很多失败不是 outbound 没完成，而是 return 阶段转向/前进后没有接近起点。
- 一些 episode 里 VLM 会反复 forward 或 turn，但机器人净位移小。
- 成功样本经常也接近阈值，说明 baseline 成功比较脆弱。

说明：

- NaVILA 有一定视觉返回能力，但不是稳定能力。
- hard subset 的价值在于隔离 return failure。

### 3.3 早期 relative-odometry route memory batch（2026-06-26）

目的：

- 测试记录 outbound anchor 并在 return prompt 里注入 route-progress hint 是否有帮助。

代码/环境：

- 使用外部 `RouteMemoryAgent`。
- outbound anchor 来自动作积分/relative odometry。
- return 时构造反向 route template，并注入 compact route hint。
- 有保守 fallback/correction 逻辑。
- 数据：`results/route_memory_batch_10_20260626/`

聚合结果：

| Method | Outbound | Return | Round trip | Final distance improved |
|---|---:|---:|---:|---:|
| selected 10 baseline | 10/10 | 0/10 | 0/10 | - |
| relative-odometry route memory | 8/10 | 3/10 | 3/10 | 7/10 |

典型 episode：

| Episode | 结果 | 轨迹解释 |
|---:|---|---|
| 4 | return false, final `0.000 m` | 已经到起点附近但没有产生合法 VLM stop，暴露 terminal 判定问题。 |
| 5 | return false, final `8.859 m` | hint/fallback 没能形成有效局部进展。 |
| 187 | return false, final `8.820 m` | 多次 route-memory/fallback 仍然没回到起点。 |
| 367 | return true, final `1.765 m` | route-memory hint 在该布局中有效。 |
| 368 | return false, final `7.137 m` | route template 没解决局部路径选择。 |
| 678 | return true, final `2.691 m` | 成功但接近阈值。 |
| 680 | return true, final `1.925 m` | 成功。 |
| 994 | return false, final `4.742 m` | VLM 曾 stop 但在半径外，route progress 仍不准。 |

说明：

- route-memory hint 有帮助，但 action-integrated odometry 不够准。
- 失败同时来自 progress estimation drift、局部导航、stop 判断。

### 3.4 episode 368：action-integrated hint vs Isaac GT relative-start

目的：

- 判断 hint 形式本身是否可用。如果 relative pose 准确，VLM 是否能利用。

代码/环境：

- 同样的 relative-start hint 格式。
- 对比 action-integrated relative start 和 Isaac ground-truth relative start。
- 数据：`results/episode368_hint_source_comparison_20260626/`

结果：

| Episode | Hint source | Return | Final distance |
|---:|---|:---:|---:|
| 368 | action-integrated relative start | false | `7.840 m` |
| 368 | Isaac GT relative start | true | `2.195 m` |

轨迹解释：

- action-integrated 失败时，最终 hint 认为起点约 `2.20 m`，但 simulator 真值是 `7.84 m`。
- Isaac GT 版本中 hint distance 和真实距离一致，VLM 在半径内 stop。

说明：

- prompt/hint 形式是能被 VLM 利用的。
- 当时主要瓶颈是状态估计，而不是“给相对起点 hint”这个想法本身。

### 3.5 oracle-anchor 单 episode sanity check（2026-06-27）

目的：

- 用完美 anchor-relative relocalization 检查 route-memory 整条数据路径。

代码/环境：

- `--route_memory`
- `--route_relocalization_backend=oracle_anchor`
- episode 994 单跑

结果：

| Episode | Backend | Outbound | Return | Round trip | Final distance | Hint events |
|---:|---|:---:|:---:|:---:|---:|---:|
| 994 | `oracle_anchor` | true | true | true | `0.619 m` | 36 |

轨迹解释：

- VLM 能利用 anchor-relative metric hint。
- current frame -> anchor relative pose -> route hint -> VLM -> stop 的 plumbing 跑通。

后来的重要修正：

- 2026-06-29 审计发现，这不是“纯 oracle 直接给 VLM”的测试。oracle pose 先进入 route-memory / particle-filter pipeline，VLM 看到的 source 经常是 `arc_length_particle_filter`，不是 raw oracle truth。

说明：

- oracle-anchor pipeline 能工作，但这个实验没有干净隔离 oracle 本身的效果。

### 3.6 ORB/SIFT feature-depth relocalization

目的：

- 用真实 RGB-D feature matching 替代 Isaac oracle-anchor。

代码/环境：

- `code/relocalization.py`
- ORB 或 SIFT
- RGB + aligned depth
- 3D-3D RANSAC/Kabsch

结果和轨迹现象：

- strict ORB ep994：`0` 个 relocalization event，return 失败，final 约 `4.363 m`。
- relaxed ORB ep994：`12` 个 relocalization estimates，return 失败，final 约 `4.424 m`。
- 大部分 candidate 过不了 RANSAC；成功 estimate 也只有约 `6-11` 个 3D inliers。
- SIFT candidate 更多，但 consistency gate 会拒绝；未拒绝时 pose error 很大。

说明：

- 室内重复纹理、视角变化、深度噪声让手工特征不够稳。
- 需要更强的 learned matching 或序列一致性。

### 3.7 LoFTR 单跑 ep994 成功

目的：

- 用更强的 learned matcher 做 RGB-D relocalization。

代码/环境：

- `loftr_depth` backend
- Kornia LoFTR outdoor model
- RGB matches + depth + 3D-3D RANSAC
- 相关代码：`code/relocalization.py`、`code/round_trip_eval.py`

结果：

| Episode | Backend | Outbound | Return | Round trip | Final distance | Accepted relocalization |
|---:|---|:---:|:---:|:---:|---:|---:|
| 994 | `feature_depth_loftr_3d3d` | true | true | true | `1.072 m` | 503 records |

轨迹解释：

- 这是第一个 real non-oracle relocalization 支撑 return 成功的强证据。
- 但后续 batch/重复测试表明这个成功不稳定。

说明：

- LoFTR 有潜力，但单次成功不能证明鲁棒。

### 3.8 LoFTR hard subset batch（2026-06-28）

目的：

- 在 11 个 hard episode 上评估 LoFTR route memory。

代码/环境：

- `--route_memory`
- `--route_hint_mode=compact`
- `--route_relocalization_backend=loftr_depth`
- 数据：`artifacts/loftr_depth_hard_batch_20260628/`

聚合结果：

| Set | Episodes | Outbound | Return | Round trip |
|---|---:|---:|---:|---:|
| LoFTR hard subset | 11 | 8/11 | 3/11 | 3/11 |
| conditional on outbound success | 8 | 8/8 | 3/8 | 3/8 |

逐 episode：

| Episode | Outbound | Return | Final distance | 轨迹解释 |
|---:|:---:|:---:|---:|---|
| 4 | true | false | `7.577 m` | 没有 relocalization lines。 |
| 5 | true | false | `7.589 m` | 有 294 条 relocalization，但没有带来成功。 |
| 134 | false | false | `7.886 m` | 不是 clean return sample。 |
| 187 | true | false | `14.208 m` | relocalization 多但可能误导/不稳定。 |
| 367 | true | true | `1.606 m` | 成功，且有较多高置信 relocalization。 |
| 368 | true | false | `7.743 m` | relocalization 多但几何歧义仍导致失败。 |
| 408 | false | false | `2.125 m` | 不是 clean return sample。 |
| 678 | false | false | `5.824 m` | 不是 clean return sample。 |
| 680 | true | true | `1.656 m` | 成功，但 relocalization 很少。 |
| 994 | true | false | `4.265 m` | batch 中 0 个 accepted relocalization，和单跑成功相反。 |
| 1040 | true | true | `1.124 m` | 成功，可能主要靠 VLM 本身。 |

说明：

- accepted relocalization 数量和成功率不简单正相关。
- 有些成功可能主要来自 VLM 视觉导航，不是 hint。
- ep994 单跑成功但 batch 失败，说明随机性/初始化/服务状态影响很大。

### 3.9 ep994 LoFTR 修复系列

这组实验用 ep994 做显微镜，因为它既有 LoFTR 成功记录，也有 batch 失败记录。

#### 3.9.1 anchor-heading reliability fix

目的：

- 不再把 translation-only LoFTR estimate 伪装成可靠 heading。

结果：

- ep994 失败，final `4.363 m`。
- VLM 在半径外 stop。
- final route-memory distance 约 `2.947 m`，但真实 simulator distance 是 `4.363 m`。

说明：

- 去掉假 heading 是必要的，但 action-integration drift 被暴露出来。
- 需要真实 rotation，而不是只用 translation。

#### 3.9.2 3D-3D rotation / dtheta fix

目的：

- 保留 Kabsch/RANSAC rotation，并转换成 `anchor_dtheta_rad`。

结果：

| Episode | Backend | Outbound | Return | Round trip | Final distance | Successful estimates |
|---:|---|:---:|:---:|:---:|---:|---:|
| 994 | LoFTR 3D-3D rotation | true | true | true | `1.264 m` | 85 |

轨迹解释：

- return distance 从 `11.719 m` 降到 `1.264 m`。
- `anchor_dtheta_rad` 不再全是 0。

说明：

- 丢掉 rotation 是真实 bug。
- rotation 修复对 ep994 有明确帮助。

#### 3.9.3 monotonic anchor progress v2

目的：

- 防止 target anchor 反复倒退，经过 anchor 后继续沿反向路线前进。

结果：

| Episode | Outbound | Return | Round trip | Final distance | Monotonic violations |
|---:|:---:|:---:|:---:|---:|---:|
| 994 | true | true | true | `1.148 m` | 0 |

轨迹解释：

- target sequence 单调：`None -> 14 -> 13 -> 8 -> 7 -> 6 -> 5 -> 4 -> 3`。
- 但后期 scalar progress 仍偏保守：target A3 时 route memory 仍认为约 `7 m`，真实已经约 `1.15 m`。

说明：

- monotonic target selection 有帮助。
- 路径剩余距离应该基于 route projection / path progress，而不是简单 `distance_to_target_anchor + target_anchor.route_remaining`。

#### 3.9.4 SeqSLAM particle filter (`seqpf_sfix`)

目的：

- 用 sequence-consistent LoFTR observations 以概率方式跟踪 route arc length。

代码/环境：

- `ArcLengthParticleFilter` in `code/route_memory_agent.py`
- 256 particles over outbound route length

结果：

| Episode | Outbound | Return | Round trip | Final distance | Sequence observations |
|---:|:---:|:---:|:---:|---:|---:|
| 994 | true | true | true | `1.264 m` | 8 |

轨迹解释：

- filter 只在 return 前半段接受 observations，大约从 A14 到 A8。
- 后半段 LoFTR observations 消失。
- filter 后来过早 collapse 到 A0 / `0 m remaining`，但真实距离仍约 `4-5 m`。
- VLM 没有完全相信错误的“已到达” hint，而是继续走到真实约 `1.26 m`。

说明：

- 成功不完全来自准确 late-stage relocalization。
- VLM 本身的视觉导航承担了后半段。
- particle filter 需要起点附近的 observation coverage。

#### 3.9.5 hint gating

目的：

- 当 particle filter 不确定时，避免直接告诉 VLM “已经到了/该 stop”。

结果：

| Episode | Outbound | Return | Final distance | Gated hint events |
|---:|:---:|:---:|---:|---:|
| 994 | true | false | `4.403 m` | 21 |

轨迹解释：

- gating 大约在距离起点 `10.8 m` 时开始触发。
- 后续 VLM 收到更泛化的 “position uncertain” 类提示。
- 最终停在 `4.403 m`，半径外。

说明：

- gating 思路是对的，但 prompt 设计伤害了导航叙事。
- 应该只抑制 “arrived / stop now” 结论，而不是删掉方向和 route context。

### 3.10 GT co-visibility / rear camera / VIO bridge 诊断

目的：

- 解释 ep994 后半段为什么 LoFTR observation 消失。

诊断：

| 区域 | 范围 | 问题 |
|---|---|---|
| A | d2s < `6 m` | 几乎没有共视；return 前向相机朝 east/south，而 outbound anchor 朝 west/north。 |
| B | d2s `6-8 m` | 有一些共视，但走廊墙面几何退化，无法约束沿走廊方向 translation。 |

代码方向：

- outbound anchor 存 rear-facing camera descriptor。
- return 当前 front view 可以和 anchor rear view 匹配。
- VIO bridge：当 filter std 高且离 feature anchor 远时，抑制不可靠视觉 PF update。

当前状态：

- `code/round_trip_eval.py` 已有 rear-camera descriptor extraction path。
- `code/route_memory_agent.py` 已有 `vio_bridge_enabled` 和 feature-anchor logic。
- 还没有 documented final rear-camera batch result。

说明：

- 这是解释 LoFTR 第二阶段失败的最强证据之一。
- 多视角 anchor 或 viewpoint-compatible descriptor 应该优先验证。

### 3.11 oracle-anchor hard batch（2026-06-29）

目的：

- 把单 episode oracle-anchor sanity check 扩展到 11 个 hard episode。
- 每个 episode 使用 fresh VLM + fresh Isaac，避免跨 episode 记忆污染。

代码/环境：

- `--route_memory`
- `--route_relocalization_backend=oracle_anchor`
- 原始 oracle-anchor 模式使用 `--route_hint_source=integrated`
- fresh 8-bit VLM server per episode
- unique VLM port per episode
- 脚本：`code/run_oracle_anchor_hard_fresh_batch_20260629.sh`
- 数据：`artifacts/oracle_anchor_hard_batch_20260629/`

outbound-success episodes 结果：

| Episode | Return | Final distance | 轨迹解释 |
|---:|:---:|---:|---|
| 4 | true | `0.664 m` | hint pipeline 有帮助。 |
| 5 | false | `7.589 m` | 没能利用 oracle-anchor hint，疑似局部导航问题。 |
| 187 | false | `8.761 m` | oracle backend 仍未解决。 |
| 367 | false | `6.750 m` | return 退化。 |
| 368 | true | `2.086 m` | oracle-anchor hint 有效。 |
| 408 | false | `5.475 m` | oracle backend 仍失败。 |
| 680 | true | `1.230 m` | 成功。 |
| 994 | false | `4.398 m` | 与单跑 oracle-anchor 成功相反。 |
| 1040 | true | `1.146 m` | 成功。 |

聚合：

- outbound-success valid samples：9
- return success：`4/9`

重要发现：

- per-step 里 source 一直是 `arc_length_particle_filter`，不是 oracle raw truth。
- 也就是说，oracle 的完美 relative pose 先进入 particle filter，再被转成 VLM hint。
- 5 个失败里，很可能有些是 oracle 真值被 filter/gating 搞坏，而不是 oracle 本身无效。

说明：

- 这批证明 oracle-anchor pipeline 不足以解决 hard return。
- 但它不能回答“如果 VLM 直接拿到完美 oracle distance+bearing 会怎样”。

### 3.12 direct oracle route-anchor + confirm yaw alignment

目的：

- 绕过 particle filter 和 relocalization gate，直接给 VLM 注入 oracle distance+bearing。
- 避免早期 `bearing to start` 让机器人直指起点撞墙的问题，改为沿反向路径选择下一个 route anchor。
- 在 confirm->return 阶段先把朝向对齐到最近 reverse anchor segment。

代码/环境：

- `--route_hint_source=oracle`
- `--route_relocalization_backend=none`
- `--oracle_align_return_yaw_to_anchor_segment`
- `direct_oracle_route_anchor_progress()` in `code/round_trip_eval.py`
- `oracle_anchor_segment_return_yaw()` / `align_return_yaw_to_anchor_segment()`
- hint 格式来自 `RouteMemoryAgent._make_anchor_hint()`

核心逻辑：

- 把当前机器人位置投影到 outbound anchor polyline。
- 选择 `current_s - max(1.0, anchor_spacing_m)` 附近的上一个 route anchor 作为目标。
- 直接计算该 anchor 在机器人 body frame 下的 distance/bearing。
- per-step 记录 `source="direct_oracle_route_anchor"`，`filter_std_m=null`。

结果：

| Episode | Outbound | Return | Round trip | Final distance | 轨迹解释 |
|---:|:---:|:---:|:---:|---:|---|
| 4 | true | true | true | `0.378 m` | 相比 no-hint 大幅改善，target A9 -> A0。 |
| 5 | true | true | true | `2.253 m` | 成功，比 no-hint 略好。 |
| 134 | false | false | false | `7.886 m` | 不是 clean return sample。 |
| 187 | true | false | false | `7.649 m` | 走近一部分后在半径外 stop。 |
| 367 | true | false | false | `0.000 m` | bookkeeping anomaly：物理距离 0 但没有 terminal event。 |
| 368 | true | false | false | `4.447 m` | 最近到 `2.92 m`，之后又走远。 |
| 408 | true | false | false | `5.996 m` | A7/A6 附近左右震荡，净进展少。 |
| 678 | true | true | true | `2.824 m` | 成功。 |
| 680 | true | true | true | `1.253 m` | 成功，与 no-hint 接近。 |
| 994 | true | false | false | `4.410 m` | no-hint 成功，oracle+yaw 反而失败。 |
| 1040 | true | true | true | `1.264 m` | 成功。 |

聚合：

- outbound：`10/11`
- return on outbound-success：`5/10`
- round trip：`5/11`

和 no-hint 对比：

| Episode | No-hint final | Oracle+yaw final | 差异 |
|---:|---:|---:|---|
| 4 | `12.91 m` | `0.38 m` | oracle 明显救回。 |
| 5 | `2.81 m` | `2.25 m` | 都成功，oracle 略好。 |
| 187 | `11.87 m` | `7.65 m` | oracle 改善距离，但没成功。 |
| 368 | `6.95 m` | `4.45 m` | oracle 改善最小距离，但没收敛。 |
| 408 | `3.95 m` | `6.00 m` | oracle 变差，hint 诱发震荡。 |
| 680 | `1.00 m` | `1.25 m` | no-hint 略好。 |
| 994 | `1.20 m` | `4.41 m` | no-hint 成功；yaw/hint 破坏策略。 |
| 1040 | `2.27 m` | `1.26 m` | oracle 改善。 |

说明：

- direct oracle 不是没用，ep4/678/1040 等有效。
- 但净提升很小且不稳定。它能影响 VLM，却不能保证局部可行。
- confirm yaw alignment 可能破坏本来有用的视觉起始状态。ep994 no-hint return yaw 约 `-52 deg` 并成功，oracle+yaw 起始 yaw 约 `-1 deg` 并失败。

### 3.13 stop-gate oracle hard batch

目的：

- 把 “stop 判断错误” 和 “导航没回去” 分开。

代码/环境：

- README 描述 `ReturnStopGate`。
- per-step 轨迹里有 `stop_gate` 字段，常见状态包括 `pass`、`accepted`、`vetoed`、`forced`、`deferred`。
- 当前 repo 没有 stop-gate 源码文件，因此这里按 README + 轨迹解释。

结果：

| Episode | Return | Final distance | Gate events | 轨迹解释 |
|---:|:---:|---:|---|---|
| 4 | true | `0.496 m` | 1 accepted | 接近起点后接受 stop。 |
| 5 | false | `9.559 m` | none | 不是 stop 问题；机器人几乎没动。 |
| 134 | false | `7.494 m` | outbound fail | 不是 clean return sample。 |
| 187 | false | `7.567 m` | 33 vetoed | stop 有问题，但 veto 后导航仍失败。 |
| 367 | false | `0.000 m` | none | oracle distance / bookkeeping anomaly。 |
| 368 | true | `1.625 m` | 1 accepted | gate 把失败转成成功。 |
| 408 | false | `8.483 m` | none | 没有 stop 决策可修，导航变差。 |
| 678 | true | `1.292 m` | 1 accepted | 接近起点后正确接受。 |
| 680 | true | `2.553 m` | 70 vetoed | 多次 veto premature stop，仍成功但 final 变差。 |
| 994 | false | `4.329 m` | 79 vetoed | veto 很多次仍没回到起点。 |
| 1040 | true | `1.916 m` | 1 forced | VLM 没 stop，gate 强制 terminal。 |

关键 per-step 现象：

- ep994：`79` 次 query-level veto，path length 约 `26.9 m`，final `4.33 m`，说明瓶颈不是 stop，而是没走回去。
- ep187：最小距离约 `2.97 m`，最后 `7.57 m`，veto 后继续运动反而远离。
- ep5：return steps 中约 `91%` 速度 `<0.03 m/s`，尽管 VLM 反复给 forward，机器人被局部环境/碰撞卡住。

说明：

- stop gate 应保留为 terminal-condition 层。
- 但它不能替代 route recovery/local navigation。
- gate veto 后必须结合 progress check；如果 veto 后距离不下降，应该切换策略，而不是继续鼓励 forward。

### 3.14 pure VLM no-hint hard batch

目的：

- 在所有 oracle/route-memory 实验之后建立真正的 control baseline。

代码/环境：

- 无 route-memory hint。
- 无 stop gate。
- 无 confirm yaw alignment。
- 每个 episode fresh process isolation。
- 数据：`artifacts/no_hint_hard_batch_20260629/`

结果：

| Episode | Outbound | Return | Final distance | 轨迹解释 |
|---:|:---:|:---:|---:|---|
| 4 | true | false | `12.91 m` | 严重 no-hint return failure；oracle 对它有帮助。 |
| 5 | true | true | `2.81 m` | VLM 纯视觉能回去。 |
| 134 | false | false | outbound fail | 不是 clean return sample。 |
| 187 | true | false | `11.87 m` | 多次 forward 但净进展小。 |
| 367 | true | false | `5.40 m` | 有一定进展，但停在半径外。 |
| 368 | true | false | `6.95 m` | 后期 left-turn loop。 |
| 408 | true | false | `3.95 m` | 接近但半径外，可能是 turn/stop 判断问题。 |
| 678 | false | false | outbound fail | 不是 clean return sample。 |
| 680 | true | true | `1.00 m` | 强视觉 return 成功。 |
| 994 | true | true | `1.20 m` | 强视觉 return 成功；oracle+yaw 反而变差。 |
| 1040 | true | true | `2.27 m` | 成功但接近阈值。 |

聚合：

- outbound：`9/11`
- return on outbound-success：`4/9`
- round trip：`4/11`

说明：

- no-hint baseline 已经接近 oracle 变体。
- 所有后续方法必须和这个 baseline 对比，而不是只和早期弱 baseline 对比。

## 4. hard subset episode 级诊断

### Episode 4

- no-hint final `12.91 m`，多次 left turn，远离起点。
- direct oracle+yaw final `0.378 m`，target 从 A9 推进到 A0。
- stop-gate final `0.496 m`，基本只是接受近起点 stop。

诊断：这是 oracle/hint 最明确有效的样本。baseline 视觉策略选错了返回行为，anchor hint 给了有用方向结构。

### Episode 5

- no-hint 成功，final `2.81 m`。
- direct oracle+yaw 成功，final `2.25 m`。
- stop-gate 失败，final `9.56 m`，`91%` return steps speed `<0.03 m/s`，target 卡在 A10。

诊断：VLM 视觉本身能解决。stop-gate 失败不是 gate 决策造成，而是机器人实际几乎没有移动。此 episode 暴露了局部 contact/stuck 和 run-to-run 随机性。

### Episode 134

- 后期大多数 batch 都 outbound fail。

诊断：不适合作为 return 机制证据，只适合放在 aggregate 里衡量整体鲁棒性。

### Episode 187

- no-hint final `11.87 m`，约 `69%` low-speed steps。
- oracle+yaw final `7.65 m`，有改善但在半径外 stop。
- stop-gate veto `33` 次，最小距离约 `2.97 m`，最终 `7.57 m`。

诊断：混合失败。oracle 能改善早期 progress，但 stop 被 veto 后导航继续漂走。这里需要 local progress monitor，而不是只 veto stop。

### Episode 367

- no-hint final `5.40 m`。
- oracle+yaw 和 stop-gate final `0.000 m` 但 return false。
- README/轨迹显示 oracle distance 与 physical distance 存在矛盾。

诊断：优先当作 bookkeeping / reset / terminal recording anomaly。不要用它证明 oracle 或 gate 成败。需要单独审计 `start_pos`、reset、return terminal event。

### Episode 368

- no-hint final `6.95 m`，后期 left-turn loop。
- oracle+yaw 最小到 `2.92 m`，最后 `4.45 m`，接近后又远离。
- stop-gate 成功，final `1.63 m`。

诊断：oracle hint 帮助机器人进入起点附近，但 terminal 判断不稳；stop gate 在这里有真实价值。

### Episode 408

- no-hint final `3.95 m`，接近但半径外。
- oracle+yaw final `6.00 m`，A7/A6 附近左右震荡。
- stop-gate final `8.48 m`，没有有用 gate event。

诊断：这是 anchor bearing 作为 steering objective 的反例。VLM 在无 hint 时可能更依赖视觉局部线索，hint 反而诱发震荡。

### Episode 678

- no-hint 最新 baseline outbound fail。
- oracle+yaw 成功，final `2.82 m`。
- stop-gate 成功，final `1.29 m`。

诊断：oracle/hint 在该场景中提升明显，stop gate 接受 terminal 正确。

### Episode 680

- no-hint 成功，final `1.00 m`。
- oracle+yaw 成功，final `1.25 m`。
- stop-gate 成功，final `2.55 m`，但有 `70` 次 veto。

诊断：VLM 本身已经很强。gate 过度 veto 会增加路径长度并让 final distance 变差。

### Episode 994

- no-hint 成功，final `1.20 m`。
- oracle+yaw 失败，final `4.41 m`。
- stop-gate 失败，final `4.33 m`，`79` 次 veto。
- LoFTR 系列说明成功是可能的，但 late-stage localization 不稳定。

诊断：这是“oracle hint 不一定帮忙”的关键反例。confirm yaw alignment 改变了 return 起始视觉状态；no-hint 起始 yaw 约 `-52 deg` 时成功，oracle+yaw 起始 yaw 约 `-1 deg` 时失败。stop gate 无法解决，因为机器人没有回到足够近。

### Episode 1040

- no-hint 成功，final `2.27 m`。
- oracle+yaw 成功，final `1.26 m`。
- stop-gate 成功，final `1.92 m`，靠 forced terminal。

诊断：oracle 改善距离；stop gate 适合作为最终 terminal arbiter。这个 episode 适合测试更干净的 forced-stop 逻辑。

## 5. 各机制到底说明了什么

### 5.1 route-memory / oracle hint

支持证据：

- relative-odometry route memory 把 selected hard subset 从 `0/10` 提到 `3/10`。
- ep368 的 Isaac GT relative-start hint 成功，action-integrated hint 失败。
- direct oracle 明确救回 ep4，并帮助 ep678、ep1040。

限制：

- direct oracle 让 ep408、ep994 变差。
- hint 不能解决撞墙、卡住、局部不可行。
- 有些成功样本很可能主要靠 VLM 视觉，而不是 hint。

结论：hint 是有用的 soft context，但不能当作 control objective。prompt 需要避免让 VLM 强行对准一个局部不可达的几何 anchor。

### 5.2 confirm-stage yaw alignment

支持证据：

- 部分 episode 的 return 起始更整齐。
- ep5/direct oracle 类运行中没有明显伤害。

反证：

- ep994 no-hint natural yaw 成功，oracle-aligned yaw 失败。
- 当前 yaw align 只按几何最近 segment 选方向，不检查碰撞、free-space 或视觉可行性。

结论：yaw alignment 应该变成 conditional option。只有在转角小、前方可行、或短程 planner 验证过时才执行。

### 5.3 stop gate

支持证据：

- ep368 接近起点后 gate accepted，成功。
- ep1040 VLM 没 stop 时 gate forced，成功。

限制：

- ep187/ep994 veto 很多但没走回去。
- ep680 gate 让成功样本 final distance 变差。
- ep5 根本没进入有效 stop 区域。

结论：stop gate 应作为 terminal-condition module，而不是导航模块。veto 后必须监控 progress，否则会把错误运动延长。

### 5.4 LoFTR / visual relocalization

支持证据：

- ep994 单跑成功。
- rotation/dtheta fix 和 monotonic target v2 能解决 ep994。
- hard batch 中 ep367、ep680、ep1040 成功。

限制：

- batch ep994 可以 0 accepted relocalization 并失败。
- relocalization 数量不等于成功。
- 后半段共视消失，走廊几何退化。

结论：LoFTR 是可用组件，但不是完整解。需要 multi-view anchors、rear camera descriptors、feature-anchor selection、sequence/global constraints。

### 5.5 particle filter / hint gating

支持证据：

- SeqSLAM PF 能把早期 observations 组织成更单调的 progress。

限制：

- observations 消失后 PF 可过早 collapse 到 A0。
- hint gating 删除了太多导航叙事，ep994 反而失败。

结论：filter 应表达不确定性，但 prompt 不能只剩 generic uncertainty。应该保留大致方向/route context，同时禁止 “arrived/stop now” 类强声明。

## 6. 后续优先方向

### 6.1 先修 bookkeeping anomaly

优先检查 ep367：

- `start_pos` capture 是否正确。
- reset 后 raw simulator distance 和 authoritative stop distance 是否一致。
- 如果 `distance_to_start_m < 0.1` 持续多步但没有 terminal event，应显式记录 anomaly。

### 6.2 把全局 route progress 和局部 motion 分层

当前问题：

- anchor bearing 是全局信号，但 VLM 可能把它当成直接 steering 指令。

更合理结构：

- route memory 只决定 coarse route segment / next corridor waypoint。
- local feasibility/free-space/stuck detector 决定 immediate heading。
- prompt 应表达“沿反向路线继续通过走廊”，而不是只说 “anchor 在左/右多少度”。

### 6.3 yaw alignment 改成条件触发

建议 ablation：

- no yaw
- always yaw align
- small-turn-only yaw align
- yaw align + one-meter free-space check

重点 episode：ep5、ep408、ep994、ep1040。

### 6.4 stop gate 加 progress-aware fallback

建议：

- N 次 veto 后如果 authoritative distance 不下降，切换策略。
- 连续 forward 但 speed `<0.03 m/s` 时标记 stuck，要求 turn/search。
- 距离已在半径内但 VLM 不 stop 时，像 ep1040 一样 forced terminal。

### 6.5 uncertainty prompt 保留方向叙事

不要只说 “position uncertain”。更好的形式：

- 保留 likely route segment / approximate direction。
- 抑制 “you are at the start / stop now”。
- 例如：“route memory is uncertain; likely next route segment is ahead-left, continue visually along the reverse corridor; do not stop solely because memory says 0 m.”

### 6.6 继续 rear camera / multi-view relocalization

理由：

- ep994 共视分析强烈指向 front-only outbound anchors 在 return 后半段视角不匹配。

下一步测试：

- 单跑 ep994 rear-anchor matching。
- 比较 A8 之后 accepted observations。
- 再跑 11 hard subset fresh VLM batch。

### 6.7 随机性要用 repeated trials

建议对每个新机制至少做 3 次 fresh trial：

- ep5：检查 local stuck / contact。
- ep368：检查 stop gate 是否稳定救回。
- ep408：检查 oracle bearing 是否稳定伤害。
- ep994：检查 yaw/hint/LoFTR 是否破坏自然视觉返回。
- ep1040：检查 forced stop 是否稳定有效。

报告时除 success rate 外，还应标注 failure class：

- local stuck/contact
- wrong stop / no stop
- successful visual return
- oracle/hint regression
- relocalization lost
- bookkeeping anomaly

## 7. 当前最稳妥的研究表述

到目前为止，数据不支持“oracle hint、stop gate 或 confirm yaw alignment 单独就能解决 return navigation”。更稳妥的说法是：

> Metric route information can influence NaVILA and sometimes rescue hard returns, but the dominant remaining bottleneck is local visual navigation under indoor geometry, especially when a global anchor bearing conflicts with feasible corridor motion. Relocalization needs multi-view/sequence robustness, and the control stack needs a local progress/stuck layer between global route hints and VLM action execution.

对应中文解释：

metric route 信息确实能影响 NaVILA，并且能救回一部分 hard return；但现在剩下的主瓶颈是室内几何下的局部视觉导航。尤其当全局 anchor bearing 和真实可走走廊方向冲突时，VLM 会被 hint 拉向局部不可行行为。后续需要同时提升多视角/序列 relocalization，并在全局 route hint 和 VLM action 之间加入 local progress/stuck 层。
