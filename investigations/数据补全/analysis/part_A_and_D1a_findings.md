# Part A (A1-A9) + Part D1a 代码抄录报告

执行范围：只读代码抄录，全部来自 `/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/` 顶层文件（未使用任何 `backup_*` 快照目录）。运行时实际值来自对应 batch 的 `ep*_eval.log` 里 `Passing the following args to the base kit application` 这一行原始 argv。未做任何代码修改、未运行任何仿真。

**涉及运行目录**（本报告确认，供全文引用）：
- `oracle_hint` → `batch_logs/pure_oracle_hint_highsuccess100ep_20260811/`
- `oracle_hint_action` → `batch_logs/pure_oracle_hint_action_highsuccess100ep_20260812/`
- `oracle_hint_action_stop` → `batch_logs/pure_oracle_hint_action_stopgate_highsuccess100ep_20260813/`
- `language_only` → `batch_logs/pure_navila_baseline_100ep_20260810/`（**已核实**：该批次 argv 里完全没有 `--route_memory` 及任何相关 flag，是真正的"无外部记忆"纯 NaVILA 基线，见下方 A/D1a 部分引用）

---

## A1. 仲裁器冲突判据（条件2）

**状态：** FOUND

**判定逻辑：** 是清单选项中的"转向符号相反 + 角度差超阈值"的组合，不是"量化后不相等"这么简单：
- `vlm_kind` 是 `unknown` 或 `stop` → 直接判定冲突（**重要连带发现，见 A7**）
- hint 期望方向是 `forward`：VLM 动作是 `left`/`right` → 冲突
- hint 期望方向是 `left`：VLM 是 `right` → 冲突；VLM 是 `forward` 且 `|bearing_deg| >= forward_conflict_bearing_deg` → 冲突（否则一致）
- hint 期望方向是 `right`：对称

**阈值：** `forward_conflict_bearing_deg`，默认 30.0 度。`hint_action_arbiter.py:22`。运行时实际值：`pure_oracle_hint_action_highsuccess100ep_20260812` 的 argv 里只有裸 `--hint_action_arbiter`，没有任何 `--hint_arbiter_*` 子参数（见下方"运行时确认"），说明该批次用的就是这个默认值 30.0 度，未被覆盖。

**源码：** `hint_action_arbiter.py:240-253`（`_conflicts_with_hint`）。

```python
def _conflicts_with_hint(vlm_kind: str, desired_kind: str, bearing_deg: float, cfg: HintActionArbiterConfig) -> bool:
    if vlm_kind in ("unknown", "stop"):
        return True
    if desired_kind == "forward":
        return vlm_kind in ("left", "right")
    if desired_kind == "left":
        if vlm_kind == "right":
            return True
        return vlm_kind == "forward" and abs(bearing_deg) >= cfg.forward_conflict_bearing_deg
    if desired_kind == "right":
        if vlm_kind == "left":
            return True
        return vlm_kind == "forward" and abs(bearing_deg) >= cfg.forward_conflict_bearing_deg
    return False
```

**运行时确认**（`pure_oracle_hint_action_highsuccess100ep_20260812/ep1002_eval.log:229`）：
```
['--task=go2_matterport_vision', ..., '--route_memory', '--route_hint_mode=compact',
 '--route_hint_source=oracle', '--route_relocalization_backend=none',
 '--topdown_route_map', '--hint_action_arbiter']
```
没有任何 `--hint_arbiter_*` 参数出现，证明该批次仲裁器全部子参数都在用 `HintActionArbiterConfig` 的 dataclass 默认值（`hint_action_arbiter.py:19-121`），不是文档推测。

---

## A2. β_t 到离散动作的映射

**状态：** FOUND（VLM 侧解析）+ PARTIAL（hint 侧量化，见下）

**两套独立的映射，服务不同方向：**

**(a) hint→期望动作（仲裁器用来算"该往哪走"）**：`_desired_kind`，`hint_action_arbiter.py:198-201`
```python
def _desired_kind(bearing_deg: float, cfg: HintActionArbiterConfig) -> str:
    if abs(bearing_deg) <= cfg.forward_cone_deg:
        return "forward"
    return "left" if bearing_deg > 0.0 else "right"
```
- 三分箱：`forward`（|β_t| ≤ forward_cone_deg，默认 15.0 度，`hint_action_arbiter.py:21`）、`left`（β_t > 15°）、`right`（β_t ≤ -15°）。
- **符号约定**：正角=左转，负角=右转（0度=机器人正前方）。这与执行侧 `_turn_override_command`（`hint_action_arbiter.py:225-237`，`left`→`omega=+pi/6`，`right`→`omega=-pi/6`）的符号严格一致（右手系、z轴向上、逆时针为正）。

**(b) VLM文本→动作类别**（仲裁器用来判断"VLM实际想干嘛"）：`_vlm_action_kind`，`hint_action_arbiter.py:170-180`——按子串匹配 `"stop"`、`"turn left"`、`"turn right"`、`"move forward"`/`"move"`，其余归为 `unknown`。**这不是数值分箱，是文本模式匹配**，不涉及角度边界。

**(c) 完整离散动作集与实际执行的角度/距离分箱**：`get_vel_command`，`isaaclab_exts/omni.isaac.vlnce/omni/isaac/vlnce/utils/eval_utils.py:57-106`。这是每一步、每个 VLM 输出（不限 return 阶段）都会走的执行层解析函数：

| 动作类别 | 识别的角度/距离子串 | 输出 [vx,vy,omega] | 时长 |
|---|---|---|---|
| turn left | "45"/"30"/"15"/其他 | `[0,0,+pi/6]` | 1.5s/1.0s/0.5s/0.5s(默认) |
| turn right | "45"/"30"/"15"/其他 | `[0,0,-pi/6]` | 1.5s/1.0s/0.5s/0.5s(默认) |
| move forward | "75"/"50"/"25"/其他 | `[0.5,0,0]` | 1.5s/1.0s/0.5s/0.5s(默认) |
| stop | — | `[0,0,0]` | 0.0s |
| 无法识别 | — | `[0.5,0,0]`（等同 move forward 默认） | 0.5s |

注意角速度恒为 `pi/6 rad/s`（30°/s）不随声明角度变化，只有维持时长变化——所以"45度"转向实际是转 1.5s×30°/s=45°，数值上自洽。**该函数被显式标注 2026-08-15 曾短暂改成通用数字解析、又被回退**（同文件 :58-78 注释），原因是真实数据里 NaVILA 会产生 "move forward 0.06 cm." 这类幻觉/畸形距离，通用解析会静默算错——这条历史细节直接支撑 D1a 设计里"不能碰这个函数"的前提。

**NOT FOUND：** NaVILA 模型自身训练时定义的"完整离散动作词表"（如果论文想引用的是 VLA 模型输出层本身的动作空间定义，而非这个下游文本解析器）——已搜索 `round_trip_eval.py`、`hint_action_arbiter.py`、`eval_utils.py`，未找到模型侧的 action-head/tokenizer 定义（大概率在 `/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA/` 训练代码库里，本次未展开搜索，超出本报告的 scripts/ 范围）。

---

## A3. 最小距离阈值 d_min

**状态：** FOUND

**变量名：** `min_anchor_distance_m`
**数值：** 0.35 m（`hint_action_arbiter.py:25`，dataclass 默认值）
**来源：** `hint_action_arbiter.py:25`
**与 δ_a 的关系：** 独立常量，**没有任何 CLI flag 能覆盖它**——已逐行检查 `round_trip_eval.py:4011-4050` 里 `HintActionArbiterConfig(...)` 的完整构造调用，其中没有 `min_anchor_distance_m=getattr(...)` 这一行，说明这是全项目所有批次里唯一硬编码、无法从命令行调整的仲裁器参数。δ_a（`--route_anchor_spacing_m`，默认 1.0m，`round_trip_eval.py:192`）与它没有比例关系（0.35 是绝对值，不随 δ_a 变化）。
**触发时行为：** `hint_action_arbiter.py:389-390`，`if distance < self.cfg.min_anchor_distance_m: return HintActionDecision(override=False, reason="target_too_close", **base)`——完全跳过仲裁、沿用 VLM 原始动作。

---

## A4. 占据检查（条件3）

**状态：** FOUND

**表示形式与优先级**（`hint_action_arbiter.py:475-508` 的调用顺序 + `local_map.py:135-149` 的内部优先级）：
1. `local_map_clear_path`（`local_map.py:135`）优先，内部再分两层：
   a. **2D 占据栅格**（`local_map.py:86-132`，`_occupancy_grid_clear_path`）——若 descriptor 里有 `local_occupancy_grid`/`local_occupancy_meta` 就用这个
   b. **原始点云**（`local_map.py:41-83`，`_point_cloud_clear_path`）——否则退回到 body 系下的 Nx2/Nx3 点云（`local_map_points_body`/`lidar_points_body`/`scan_points_body`/`height_scan_points_body` 任一 key），按 z∈[-0.10, 1.50]m（`min_obstacle_height_m`/`max_obstacle_height_m`，`local_map.py:37-38`）做高度滤波
2. 若以上都不可用，退回 **topdown route map 图像**（`hint_action_arbiter.py:274-321`，`_topdown_clear_path`）——RGB 均值 < 100.0 判定为障碍像素（`hint_action_arbiter.py:300`）

**几何形状：** 都不是清单里的"扇区"，是**沿目标方向的直线走廊/管道（corridor）**——检查沿 (dx,dy) 方向的一条线段，横向半宽 = `robot_radius_m + clearance_margin_m`。不适用"扇区角半宽"这一项（本机制不是扇区设计）。

**检查半径 R_occ：** `max_clear_path_distance_m`，默认 1.0 m（`hint_action_arbiter.py:26`，实际检查长度 = `min(target_len, max_clear_path_distance_m)`）。

**走廊半宽：** `robot_radius_m`(默认0.30m) + `clearance_margin_m`(默认0.12m) = 0.42m（`hint_action_arbiter.py:27-28`，`local_map.py:34-35`）。

**"可通行"判定准则：** 是二值判定，**不是"自由栅格比例>阈值"**——沿路径采样点（步长 `sample_step_m`=0.05m，`hint_action_arbiter.py:29`）逐点检查，只要任意一个采样点周围 `robot_radius_m+clearance_margin_m` 范围内存在障碍点/栅格，立即判定不可通行（`local_map.py:81-82`：`if min_clearance < corridor_radius: return ...(True, False, ...)`）。

**占据信息来源：** 当前帧，不是累积地图。`round_trip_eval.py:4580-4581`：`route_descriptor = route_memory_descriptor_from_infos(infos, env)` 在**每一个 `env.step()` 之后**都重新计算，`current_route_descriptor` 随即被更新为这一步的新值——传给 `arbiter.check()` 的是上一步刚采集的即时传感器数据，不是累积的局部地图。

**判定函数源码：** 见上方 A1 引用的 `_conflicts_with_hint` 之外，核心判定是 `local_map.py:53-83`（`_point_cloud_clear_path`，最常用路径，因为大多数批次的 descriptor 里没有专门构造 `local_occupancy_grid`——本报告未逐一核实每个 descriptor 的实际内容，这点标注为**未完全验证**，如需确认请检查 `route_memory_descriptor_from_infos` 的实现）。

---

## A5. 覆盖动作 a^β_t 的构造

**状态：** FOUND

**选出方式：** 不是"离散集中最接近β_t的那个"（因为只有3个粗桶 forward/left/right，没有更细的离散集可挑），也不是"先转向再前进的复合动作"——**每次仲裁只输出单一动作**（forward 或 left 或 right 之一，跟 `_desired_kind` 返回值严格一一对应）：
- `forward`：固定步长前进，`forward_distance_cm`，默认 75cm（`hint_action_arbiter.py:24`）
- `left`/`right`：默认固定转 `turn_step_deg`=45度（`hint_action_arbiter.py:23`）；若 `turn_override_completes_full_angle=True`（本报告确认的三批 oracle 消融链均未开启此 flag，只在 08-15/08-16 的 line2 系列非本清单范围的批次里用到）则改为转真实的 β_t 角度

**若涉及前进，步长：** 75cm 固定（不随距离变化），`hint_action_arbiter.py:24,206`。

**构造函数源码：** `hint_action_arbiter.py:204-222`（`_replacement_output`）+ `225-237`（`_turn_override_command`，仅 full-angle 模式下用到）。

```python
def _replacement_output(kind: str, cfg: HintActionArbiterConfig, bearing_deg: Optional[float] = None) -> str:
    if kind == "forward":
        return f"The next action is move forward {int(cfg.forward_distance_cm)} cm."
    if kind in ("left", "right"):
        step_deg = cfg.turn_step_deg
        if cfg.turn_override_completes_full_angle and bearing_deg is not None:
            step_deg = abs(float(bearing_deg))
        word = "left" if kind == "left" else "right"
        return f"The next action is turn {word} {int(round(step_deg))} degree."
    return "The next action is stop."
```

---

## A6. 冷却 / 连续覆盖上限

**状态：** FOUND —— 三项全部为**无**

- **每 episode 覆盖次数上限：** 无。已检查 `hint_action_arbiter.py`（全文件，无任何计数器/上限字段）和 `round_trip_eval.py` 里 `hint_action_arbiter` 相关的全部调用点（`grep -n "hint_action_arbiter\|HintActionArbiter"` 命中的每一行），没有任何 episode 级别的覆盖计数或截断逻辑。
- **冷却机制：** 无。`grep -n "cooldown"` 在这两个文件里唯一命中的是 `--sequential_pair_closure_cooldown_attempts`（`round_trip_eval.py:294`），这是 `route_memory_agent.py` 里 quarantine/current-next 晋升机制的冷却参数，跟 `hint_action_arbiter` 完全无关，不要混用。
- **连续覆盖上限：** 无。`HintActionArbiter` 类（`hint_action_arbiter.py:324-537`）唯一携带的跨调用状态是 `_trend_history`（`hint_action_arbiter.py:331`，仅用于 `trend_confidence_enabled` 这个默认关闭的置信度平滑机制，且该机制本身 2026-08-16 已被硬性 disable，见 `hint_action_arbiter.py:333-357` 的 `_trend_confidence_trusts` 顶部 `return False` 和上方大段回退说明），没有连续覆盖次数的计数或强制放行逻辑。

**结论：** 仲裁器每次决策都是无状态独立判定（trend_confidence 是唯一的跨步状态，且已被停用），不存在任何形式的节流。

---

## A7. STOP 动作在仲裁器中的处理（最高优先级）

**状态：** FOUND —— 关键发现：**STOP 不被豁免，且默认配置下（`oracle_hint_action`）STOP 可以被覆盖为移动指令**

**完整回答：**

1. **是否进入仲裁器判定流程：** 是，无条件进入。`round_trip_eval.py:4199-4200`：`if hint_action_arbiter is not None and phase == "return": _last_hint_action_decision = hint_action_arbiter.check(...)`——这个调用不检查 `vlm_output` 是不是 stop，STOP 和其他任何动作走的是完全相同的入口。

2. **是否可能被判定为"与β_t冲突"并覆盖为移动动作：** **可以**。`_vlm_action_kind` 把 `"stop"` 识别为 `vlm_kind="stop"`（`hint_action_arbiter.py:172-173`），而 `_conflicts_with_hint` 的第一行就是 `if vlm_kind in ("unknown", "stop"): return True`（`hint_action_arbiter.py:241-242`）——**STOP 和"无法解析的输出"被同等对待，永远判定为冲突**，除非提前被 `target_too_close`（A3）或低置信度（`min_relocalization_confidence`，默认0.0，本批次未生效）拦下。冲突后走到 `_conflicts_with_hint` 判 True 的后续流程：清路检查通过 → `return HintActionDecision(override=True, reason="vlm_conflicts_with_clear_hint", ...)`，`replacement_output` 是 `_replacement_output("forward"/"left"/"right", ...)` 生成的移动指令文本。

3. **是否存在显式豁免：** 否。已通读 `hint_action_arbiter.py` 全文件和 `round_trip_eval.py` 里调用 `hint_action_arbiter.check()` 前后约80行（`round_trip_eval.py:4196-4256`），没有任何 `if vlm_kind == "stop": skip` 式的豁免分支。**唯一能保护 STOP 不被覆盖的路径是 `stop_veto_enabled`**（`hint_action_arbiter.py:57`，默认 `False`；CLI flag `--hint_action_arbiter_stop_veto`，`round_trip_eval.py:1485`）——但这是一个反向机制：它做的是"在低置信度时抑制一个可能错误的STOP"，不是保护"高置信度、正确的STOP"；而且默认关闭。

4. **在 `oracle_hint_action` 配置下（终止验证未启用）的完整处理路径：** 已用真实 argv 核实该批次只传了裸 `--hint_action_arbiter`（见 A1 "运行时确认"），`hint_action_arbiter_stop_veto` 未出现 → `stop_veto_enabled=False`（`round_trip_eval.py:4043` 的 `getattr(..., "hint_action_arbiter_stop_veto", False)` 落到默认值）。完整路径：
   ```
   VLM输出含"stop" → hint_action_arbiter.check() 被调用（无STOP豁免）
     → stop_veto_enabled=False，跳过 stop_veto 分支（hint_action_arbiter.py:401-415 整块不触发）
     → 计算 effective_confidence，若 >= min_relocalization_confidence(默认0.0，几乎总是通过)
     → desired = _desired_kind(bearing, cfg)  # forward/left/right 三选一
     → _conflicts_with_hint("stop", desired, bearing, cfg) 恒返回 True
     → 若 desired 是 left/right 且 turn_override_completes_full_angle=False（本批次是这样）：
         → 走 local_map / topdown 清路检查（A4）
         → 清路可用且通畅 → override=True, reason="vlm_conflicts_with_clear_hint"，
           replacement_output 是一条 "move forward"/"turn left/right 45 degree" 文本
         → 清路不可用或被挡 → override=False，reason="occupied_in_local_map_path" 等，
           VLM 原始 STOP 保留，回合可能在这一步真正终止
   ```
   即：**只要目标锚点方向存在清晰通路，VLM 主动提出的 STOP 就会被无条件替换成移动指令**——这是 B4（STOP 步在日志里的落点）可以直接拿来验证的具体断言。

---

## A8. 完整超参数清单

以下按清单小节逐项列出，能确认的给出 file:line，不能完全确认的标注 PARTIAL/NOT FOUND。

### 路由记忆构建
- **anchor 间距 δ_a：** `--route_anchor_spacing_m`，默认 **1.0 m**（`round_trip_eval.py:192`；`route_memory_agent.py:422,638` 类内默认同为1.0）。三批 oracle 消融链的 argv 里均未出现该 flag（已核实 A1/A7 引用的 argv 全文），确认实际运行值=默认值=1.0m。
- **LiDAR 裁剪半径 R_lidar：** NOT FOUND in scripts/ 顶层文件——`route_memory_agent.py`/`round_trip_eval.py` 里没有直接的传感器裁剪代码，LiDAR 原始点云的采集/裁剪大概率发生在 Isaac Lab 的传感器配置（`omni.isaac.lab.sensors`）或 `isaaclab_exts/` 下的环境 cfg 里，不在本报告搜索范围（scripts/ 顶层）内。已搜索：`route_memory_agent.py`, `round_trip_eval.py`, `local_map.py`, `relocalization.py` 全部 grep 过 `lidar`/`raycast`/`clip`/`crop` 关键词，未命中裁剪半径定义。
- **降采样/体素分辨率：** NOT FOUND，同上，未在 scripts/ 顶层文件中定位到体素滤波代码。
- **其他滤波参数：** PARTIAL——`local_map.py:37-38` 的 `min_obstacle_height_m=-0.10`/`max_obstacle_height_m=1.50` 是清路检查用的高度带通滤波（见A4），但这是"仲裁器读local map时"的滤波，不确定是否等同于"路由记忆构建"阶段本身的滤波——两者可能是同一份点云在不同环节复用，未逐行追踪确认，标注 PARTIAL。

### 返程定位
- **正常候选集大小：** PARTIAL——代码里明确区分 `current`/`next` 两个角色（历史investigation文档反复提到"current/next anchor"），但本报告未在 scripts/ 顶层逐行确认"是否恰好是current+next两个"还是更大窗口——`route_memory_agent.py` 4395行的规模超出本次抄录深度，建议后续针对 `_next_candidate_index`/promotion 相关函数单独复核。
- **recovery 候选集大小/范围：** NOT FOUND in this pass，同上原因（该文件规模大，本报告聚焦仲裁器/占据检查/ICP核心三块，未完整覆盖 route_memory_agent.py 的 quarantine/recovery 逻辑）。
- **多帧一致性窗口长度：** FOUND（针对 trend_confidence 机制）——`trend_confidence_window`，默认 **5**（`hint_action_arbiter.py:118`），但这是仲裁器自己的置信度平滑窗口，**该机制 2026-08-16 已被代码内部硬性 disable**（见A6引用的`_trend_confidence_trusts`顶部`return False`）——若论文问的是"返程定位"本身（ICP/relocalization 层面）的多帧一致性窗口，这不是同一个东西，NOT FOUND at that layer。
- **候选歧义度的判据与裕量、触发 recovery 模式的条件：** NOT FOUND in this pass，超出本报告覆盖的文件范围（需要深入 `route_memory_agent.py` 的 quarantine/ambiguity 相关约4000行代码，本次未展开）。

### 可靠性阈值
- **r^pose_t / r^bearing_t / r^distance_t 的阈值与计算方式：** NOT FOUND——本报告在 `route_memory_agent.py` 里检索到大量 "reliability"/"trust" 相关代码（如1052行起的 "Trust-aware belief guard"）但未逐一提取成阈值表，需要专项复核，本次受限于时间未完成。
- **三者是否共享中间量：** NOT FOUND，同上，未确认。

### ICP 设置
**状态：** 大部分 FOUND，来自 `relocalization.py`（不是 `route_memory_agent.py`——该实现在独立文件）。

- **算法实现：** **不是 Open3D**，是项目自实现的 2D ICP，`relocalization.py:1289`（`icp_rigid_transform_2d`）。支持 `point_to_point`（默认 `objective` 参数值）和 `point_to_line`/`point_to_line_2p5d` 两种目标函数；docstring 明确说明 `ndt_2d` "目前只是 point_to_line 增量求解的一个实验性别名，故意单独记录以便 A/B 测试，不代表这是完整的 NDT 地图实现"（`relocalization.py:1298-1301`，原话）。
- **最大迭代次数：** 函数自身默认 `max_iterations=24`（`relocalization.py:1294`），但**实际调用点大多显式传 `max_iterations=16`**（`relocalization.py:1773, 2016, 2240, 2452` 等多处）——即函数默认值 24 从未在生产路径里真正生效，运行时实际值是 16。
- **对应点距离上限：** `correspondence_threshold_m`，函数默认 **0.45 m**（`relocalization.py:1296`），`relocalization.py:2240` 处显式传参同为 0.45，两者一致。
- **收敛判据：** 内点中位残差变化 `< 1e-4` 则提前收敛退出，或达到 `max_iterations`，或内点数 `< 8` 直接判定失败返回 `None`（`relocalization.py:1316-1335`）。
- **fitness/inlier RMSE 阈值：** PARTIAL——函数本身只返回 `inlier_count`/`overlap_ratio`/`median_residual_m`/`mean_residual_m`（`relocalization.py:1340-1345`），不在这一层做接受/拒绝判定；下游 `route_memory_agent.py` 用这些数值做 match_class 分类（"trustworthy"等），具体分类阈值本报告未展开追踪，标注 PARTIAL，建议查 `route_memory_agent.py` 里 `_candidate_is_trustworthy` 附近代码。
- **初值来源：** 不是单一固定初值——`icp_rigid_transform_2d` 自身默认 `initial_theta=0.0` + 质心对齐平移（`relocalization.py:1308`），但实际调用大多经过 `icp_seed_sweep_2d`（`relocalization.py:839`，`max_iterations=16`，`relocalization.py:844`）做**多初始角度（多seed）扫描**，取最佳匹配——不是单一固定初值这么简单，实际是多假设并行求解后选优。

### 终止验证（stop_gate）
**状态：** FOUND，来自 `stop_gate.py`。**注意：本清单 A/B/C/D/E 的核心三批 oracle 消融链只有第三批（`oracle_hint_action_stop`）启用了 stop_gate，前两批未启用，这一节仅对第三批有意义。**

- **距离阈值：** `r_in`（内半径，默认 **3.0m**）、`r_out`（外半径，默认 **3.0m**）——两者相等，即 stop_gate 没有内外滞回区间，是同一个 3.0m 边界。`stop_gate.py:161-162`。**运行时实测确认**（`pure_oracle_hint_action_stopgate_highsuccess100ep_20260813` 的 eval_log grep 到 `stop_gate_r_in=3.0`, `stop_gate_r_out=3.0`）——与默认值一致。**这也回答了 A8 执行协议一项："成功半径是否为3.0m"——是，且 Outbound/Return 用的是同一个 r_in=r_out=3.0m 常量，未见到分别设置的证据。**
- **approach trend 窗口与判据：** PARTIAL——`stop_gate.py` 里有独立于 `hint_action_arbiter` 的自己的 trend_confidence 实现（模块 docstring 提到 "confidence dipped a hair below min_confidence"，`stop_gate.py:27`），但本报告未提取其窗口长度等具体数值，因为已确认 `hint_action_arbiter.trend_confidence` 是从 `stop_gate.py` "ported"过去的（`hint_action_arbiter.py:96-97` 注释原话），意味着 `stop_gate.py` 里应该有平行的 `trend_confidence_window`/`min_samples`/`min_high_conf_votes`/`max_distance_spread_m` 字段，本次未逐行核对是否数值相同，标注 PARTIAL。
- **defer 最大次数/延迟步数：** PARTIAL——`confirm_steps`默认3、`forced_stop_anchor_confirm_steps`默认2（`stop_gate.py:163,166`）是"确认"相关的计数，但清单问的"defer 最大次数"若指的是 DEFERRED 决策本身可以持续多少步未终止，本报告未找到显式上限（可能没有，DEFERRED只是"这一步不管，交给VLM"，理论上可以每步都deferred直到预算耗尽）——标注 PARTIAL，非高置信度的"无"。
- **veto/defer/execute 三分支完整判定逻辑：** FOUND（决策语义，非完整源码）——`stop_gate.py:8-12` 模块级 docstring 精确描述四种（不是三种）终态：
  ```
  ACCEPTED  VLM issued stop, high conf, d ≤ r_in  → execute stop
  VETOED    VLM issued stop, high conf, d > r_out  → suppress stop, inject movement
  DEFERRED  VLM issued stop, low conf OR r_in < d ≤ r_out → pass through
  FORCED    VLM did NOT issue stop, high conf, d ≤ r_in for ≥ confirm_steps → force stop
  ```
  完整实现源码本报告未贴出（`ReturnStopGate` 类主体，`stop_gate.py:128`起，篇幅较大，未在本次范围内完整摘录），建议如需要逐行贴代码单独追加。

### 执行协议
- **execution budget（最大步数）：** NOT FOUND in this pass——未在 `round_trip_eval.py` 中定位到 outbound/return 各自的 max_episode_steps 具体数值赋值行（该文件5134行，本报告受时间限制未完整搜索这一项，只搜索到 `if done or env.is_stop_called or (phase == "outbound" and num_steps > max_episode_steps):`，`round_trip_eval.py:4734`，说明变量名是 `max_episode_steps` 但未定位其赋值来源/默认值）。
- **成功半径：** 见上方 stop_gate 部分，3.0m，Outbound/Return 目前看到的是同一常量。但"成功判定"本身（是否算 round_trip_success）可能是另一套独立于 stop_gate 的距离比较逻辑（`round_trip_eval.py` 里应该有 `distance_to_start <= 3.0` 之类的最终判定），本报告未专门核实这两处"3.0m"是否指向同一行代码还是两个独立配置的常量——标注 PARTIAL。
- **Confirm 阶段 360° 扫描：** NOT FOUND in this pass，未搜索。

---

## A9. Hint 模板生成代码

**状态：** FOUND（compact 模式，即本清单三批全部使用的模式）

**生成函数：** `route_memory_agent.py:4330-4394`（`_make_anchor_hint`）。三批 oracle 消融链都用 `--route_hint_mode=compact`（已在A1"运行时确认"的argv里核实），对应分支是 `route_memory_agent.py:4390-4394`：

```python
return (
    "[System Hint: route anchor "
    f"A{progress.target_anchor_index} is {anchor_distance:.2f} m away, {anchor_direction}; "
    f"estimated remaining route via anchor is {remaining:.2f} m; "
    f"{vector_label} dx={progress.target_dx_m:.2f} m, dy={progress.target_dy_m:.2f} m.]"
)
```
这与论文给出的示例（`route anchor A10 is 0.58 m away, ahead; estimated remaining route via anchor is 10.66 m; next-anchor vector dx=0.58 m, dy=0.02 m.`）逐字匹配。

**方向词完整词表**（`route_memory_agent.py:4367-4374`）：
| 词 | 触发条件 |
|---|---|
| `at your current position` | `anchor_distance < 0.35` m |
| `ahead` | `abs(anchor_bearing) <= 10.0` 度 |
| `{X} deg to your left` | `anchor_bearing > 0.0` |
| `{X} deg to your right` | `anchor_bearing <= 0.0`（且 >10度） |

**与 A2 仲裁器分箱是否同一套：不是。** hint 模板的"ahead"阈值是 **10度**（`route_memory_agent.py:4369`），仲裁器 `_desired_kind` 的 forward 圆锥阈值是 **15度**（`hint_action_arbiter.py:21,199`）——两者数值不同，虽然左右符号约定一致（正=左）。这是一个此前未被记录的细节。

**"estimated remaining route"计算方式：** `route_memory_agent.py:4334-4337`：若 `anchor_route_remaining_m` 可用，`remaining = anchor_distance + anchor_route_remaining_m`（到当前目标锚点的距离 + 该锚点之后沿路线到终点的累计锚点间距）；否则退化为 `progress.distance_to_start_m`。**不是单纯累加剩余锚点间距，是"到锚点的实时距离"+"锚点之后的路线长度"两部分之和。**

**数值小数位数与单位：** 全部 `.2f`（2位小数），单位统一是 "m"（米），与示例一致。

**hint 拼接方式：** PARTIAL——已定位到 `route_agent.inject_hint(current_instruction_text, num_steps, progress_override=route_query_progress)`（`round_trip_eval.py:4170-4174`）会返回新的 `query_instruction_text`，但 `inject_hint`（`route_memory_agent.py:2758`起）内部具体是字符串拼接在指令后面还是作为独立字段，本报告未展开读取该函数体，标注 PARTIAL，建议补读 `route_memory_agent.py:2758-2820` 左右范围确认。

**oracle_hint 与 oracle_hint_action 模板是否逐字相同：** 未做逐字 diff（这需要读两个批次各自的原始 VLM query 记录，不是读代码就能确认）——但从代码角度看，两批的 `route_hint_mode`（均为 compact，已用argv核实）和 `_make_anchor_hint` 函数完全相同，唯一差异是 `oracle_hint_action` 多了 `--hint_action_arbiter`（只影响是否覆盖 VLM 动作，不影响 hint 文本生成本身）——**代码路径上没有理由产生不同模板**，但清单明确要求"实际diff确认"，本报告未执行该 diff，标注 PARTIAL，需要额外一步：从 `eval_results/.../measurements/*.json` 或 phase_events 里各抽一条 `route_memory_hint` 事件对比。

---

# Part D1a：Shadow arbiter log 实施设计（仅设计，未改代码/未跑仿真）

**GPU 状态：** 执行本报告期间 `nvidia-smi` 显示 23942/24564 MiB（约97%）被另一个正在运行的 100ep batch 占用，因此按清单 D1b 的指示未做任何仿真运行，也未做 D1a 要求的 2-3 episode 冒烟测试（冒烟测试本身需要短暂占用 GPU）。以下只是最小改动方案的设计。

## 关键前置发现：现有代码已经有一个高度相似的"影子"机制

`round_trip_eval.py:4129-4132` 已经存在一个 `route_shadow_progress`（"shadow_non_oracle"，见 `route_hint_event["shadow_progress"] = route_progress_to_record(route_shadow_progress, "shadow_non_oracle")`，`round_trip_eval.py:4177-4180`）——这是"用 oracle 覆盖了 hint 内容时，同时偷偷跑一遍 agent 自己的非oracle估计做对比记录"的既有基础设施，跟 D1 想要的"跑一遍但不生效"是同一个设计模式（计算+记录，不改变执行）。D1a 可以直接照抄这个模式，而不是从零发明。

## 最小改动方案

**需要修改的文件/函数：**

1. **新增一个 CLI flag**（如 `--hint_action_arbiter_shadow_only`，放在 `round_trip_eval.py` 里 `--hint_action_arbiter` 附近，约1438行），语义："照常构建 anchor 序列、照常算 β_t、照常实例化并调用 HintActionArbiter.check() 用于记录，但绝不让它的 override 生效、也绝不把 hint 文本注入 query_instruction_text"。

2. **`round_trip_eval.py:4114` 附近**（`query_instruction_text = current_instruction_text` 这一行之后，到 `4170-4174` 的 `route_agent.inject_hint(...)` 调用之间）：当 shadow_only 生效时，**跳过 `inject_hint` 调用**，让 `query_instruction_text` 保持等于 `current_instruction_text` 不变——但仍然执行 `4116-4169` 那一整块 progress 计算（`route_progress_override`/`route_agent.progress()`），因为这部分只是纯计算，不碰 `query_instruction_text`。

3. **`round_trip_eval.py:4199-4256`** 的 `hint_action_arbiter.check(...)` 调用本身**完全不用改**——它已经是一个纯函数调用，返回值是不是被消费（`if _last_hint_action_decision.override: stream_output = ...`）才是关键。只需要在 `4233` 的 `if _last_hint_action_decision.override:` 外面加一层 `and not shadow_only` 的条件，shadow_only 模式下这个 `if` 分支整体跳过，`stream_output`/`vlm_vel_commands`/`parse_vlm_command` 走原来 `language_only` 未受任何影响的路径。`phase_events.append(...)` 那部分（`4227-4232`）不用改，正常记录 `.as_log_dict()`，这就是要的日志。

**这样一来，实际驱动机器人的 `stream_output`/`vlm_vel_commands` 在 shadow_only 模式和纯 `language_only` 模式下逐字节相同**（因为 `query_instruction_text` 和 `stream_output`/`vlm_vel_commands` 两条链路完全没被 shadow_only 分支碰过），满足清单"验证同一 episode 改动前后轨迹完全一致"的要求，理论上不需要靠随机数对齐，是结构性保证。

## 一致性判据复用（清单要求"必须与A1完全相同"）

**直接满足，无需重构。** `_conflicts_with_hint`（A1，`hint_action_arbiter.py:240-253`）已经是模块级纯函数，`HintActionArbiter.check()` 内部就是调用它（`hint_action_arbiter.py:445`）。Shadow 模式下不需要重新实现或另外导入这个函数——**直接复用同一个 `HintActionArbiter` 实例、调用同一个 `.check()` 方法**，只是不消费它的 `.override`/`.replacement_output`/`.override_command`。清单担心的"是否需要重构才能复用"的问题不存在。

## anchor 序列/目标锚点顺序/β_t 计算方式与 oracle_hint_action 保持一致的保证

不需要额外验证工作——因为 shadow_only 模式下走的**是同一段 `4116-4169` 代码**（`route_progress_override` + `route_agent.progress()` + `_gate_vlm_progress = route_query_progress`），跟 `oracle_hint_action` 批次实际跑的完全是同一份代码路径，唯一的分支点在更下游（要不要 `inject_hint`、要不要消费 `.override`）。这是"结构上保证一致"而不是"事后核对数值碰巧一致"。

## 日志字段设计

清单要求的字段（episode id、step、模型动作、β_t、量化后的 hint 动作、是否一致、到目标 anchor 的距离、是否落在 d_min 内）**已经全部存在于 `HintActionDecision.as_log_dict()`**（`hint_action_arbiter.py:149-167`）：
- 模型动作 → `original_output`（原始VLM文本，可用 A2 的 `_vlm_action_kind` 二次分类）
- β_t → `desired_bearing_deg` + `desired_distance_m`
- 量化后的 hint 动作 → `desired_kind`
- 是否一致 → `reason == "vlm_action_consistent"` 就是"一致"；`reason == "target_too_close"` 就是清单要求剔除的"落在d_min内"那一类；`reason == "vlm_conflicts_with_clear_hint"`（或未来会新增的 "shadow_conflict_no_action_taken"）才是真正的"不一致"
- episode id / step → 已有的 `phase_events.append({"step": ..., "phase": ..., "event": "hint_action_arbiter", **decision.as_log_dict()})` 外层字典本身就带 step，episode id 是外层 result_suffix/RUN_TAG 级别的元信息，不需要改动日志结构

**唯一需要新增的字段**：一个明确的 `shadow_only: bool` 标记（写在 `as_log_dict()` 输出的外层，不改 `HintActionDecision` 本身），用来跟真实生效的 `oracle_hint_action` 日志区分开，防止后续分析脚本混淆两种运行的 `event: "hint_action_arbiter"` 记录。

## 冒烟测试预估（未执行，仅预估）

- 每 episode 时长：跟 `language_only`（`pure_navila_baseline_100ep_20260810`）几乎一致，因为执行路径未变，只是每步多算一次 `route_agent.progress()` 和一次 `arbiter.check()`（都是轻量 CPU 计算，不涉及额外 GPU 推理）——预计单 episode 增量 <1秒。
- 100 episode 预估运行时长：可参照 `pure_navila_baseline_100ep_20260810` 自身的历史总耗时做基线（本报告未去查该批次的起止时间戳，建议执行冒烟测试前先查一下作为参照）。
- 显存占用：不新增任何 GPU 侧计算（arbiter/route_memory 全是 CPU numpy 运算），预计与 `language_only` 基线几乎相同，不会比它更占显存。

---

# 未能完成的项目汇总

- A2：NaVILA 模型自身动作空间定义（需要进训练代码库 `NaVILA/`，超出 scripts/ 范围）
- A4：`local_occupancy_grid` 是否在实际 descriptor 中被真正使用过（vs 总是走点云分支）未逐一核实
- A8 路由记忆构建：LiDAR裁剪半径、降采样分辨率——NOT FOUND，可能在 Isaac Lab 环境 cfg（不在 scripts/ 顶层）
- A8 返程定位：候选集大小、recovery范围、歧义判据——NOT FOUND，需要专项深读 `route_memory_agent.py` 的 quarantine/promotion 逻辑（4395行大文件，本次未完整覆盖）
- A8 可靠性阈值：r^pose/r^bearing/r^distance 三个阈值——NOT FOUND，需要专项复核
- A8 ICP fitness/inlier接受阈值下游判定——PARTIAL，需要读 route_memory_agent.py 的 match_class 分类代码
- A8 stop_gate 的 approach trend 窗口具体数值、defer 最大延迟步数——PARTIAL
- A8 执行协议：execution budget 具体数值、Confirm阶段360°扫描实现——NOT FOUND
- A9：hint 拼接方式细节（`inject_hint`函数体未读）、oracle_hint vs oracle_hint_action 模板逐字diff——PARTIAL，需要读日志验证而非代码

以上均因单次报告的时间/篇幅限制未展开，不是代码里真的找不到（除非明确标注"已搜索X/Y/Z未命中"的项）。