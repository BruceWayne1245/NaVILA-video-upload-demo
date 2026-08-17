# 论文补数清单 —— 执行报告

对应 `thesis_data_collection_checklist.md`（2026-08-17 上传）。本报告为 A/B/C/D1a/E 全部条目的合并交付版；各部分的完整分析脚本与更细节的中间产出见 `analysis/` 目录下的独立文件（`part_A_and_D1a_findings.md`、`part_B_findings.md`、`part_C_findings.md`、`part_E_findings.md`）。全程只读，未修改任何代码或日志文件。

---

## 0. 开头三项（按清单"输出格式要求"）

### 0.1 运行目录（已核实，用清单里给出的数字逐一核对过）

| 清单逻辑名 | 实际目录 | outbound_success | return_success | round_trip_success |
|---|---|---|---|---|
| `oracle_hint` | `NaVILA-Bench/batch_logs/pure_oracle_hint_highsuccess100ep_20260811/` | 86 | 32 | 32 |
| `oracle_hint_action` | `NaVILA-Bench/batch_logs/pure_oracle_hint_action_highsuccess100ep_20260812/` | 86（**实为87，见B3，JSON写入损坏导致1例静默丢失**） | 52（实为53） | 52（实为53） |
| `oracle_hint_action_stop` | `NaVILA-Bench/batch_logs/pure_oracle_hint_action_stopgate_highsuccess100ep_20260813/` | 87 | 73 | 71 |
| `language_only` | `NaVILA-Bench/batch_logs/pure_navila_baseline_100ep_20260810/` | — | — | — |
| canonical-100 交叉验证批（B8） | `NaVILA-Bench/batch_logs/pure_oracle_hint_action_100ep_20260812/` | 37/98（未跑满，手动停止） | — | — |
| B9 "4.3%"历史来源·hard-11 | `NaVILA-Bench/batch_logs/stop_gate_r3_hint_arbiter_hard11_20260630/` | — | — | — |
| B9 "4.3%"历史来源·30ep | `NaVILA-Bench/batch_logs/oracle_shadow_loftr_v4_30_return_anchor_fix_20260701/` | — | — | — |

`language_only` 已核实（`ep1035_eval.log` argv）：完全没有 `--route_memory`/`--route_hint_source`/`--hint_action_arbiter` 任何一个 flag，是真正无外部记忆的纯 NaVILA 基线。

### 0.2 日志格式与可用字段

- **`batch_logs/<run>/summary.tsv`**：每 episode 一行，字段为 `episode_idx, episode_id, scene, neighbor_idx, neighbor_episode_id, matched_waypoints, mean_distance, baseline_distance_to_start, vlm_port, start_time, end_time, exit_code, result_suffix, vlm_log, eval_log, measurement_file, outbound_success, return_success, round_trip_success, distance_to_start, outbound_stop_distance_to_goal, trajectory_record_count`。这是 B2/B3/B6/B8 等大部分统计的主字段来源。
- **`batch_logs/<run>/ep<N>_eval.log`**：每 episode 完整 stdout，含启动时 "Passing the following args to the base kit application:" 的完整 argv dump（A/C 部分配置核实的主要来源），以及运行中的仲裁器决策日志行 `[hint_arbiter] step=... override=... reason=...`（B4/B7/B9 的数据源）。
- **`eval_results/.../measurements/<idx>.json`**：单集完整测量结果（`outbound_success`/`return_success`/`round_trip_success`/`distance_to_start` 等字段的权威来源，summary.tsv 里同名字段是从这里摘录的）。**已发现该文件存在偶发写入损坏（B3）**，摘录时需要容错。
- **per-step trajectory jsonl**（在 measurements 同级或相邻目录，B2 用于计算 `d_min_e`）：含 `phase`、`distance_to_start_m` 等逐步字段。

### 0.3 本次任务中未能完成的项及原因

汇总列表见每个部分末尾的"未能完成"小节；此处只列**高优先级/影响论文数字**的缺口：

- **A8 大部分子项 NOT FOUND/PARTIAL**：LiDAR裁剪半径、降采样分辨率、返程定位候选集大小/recovery范围/歧义判据、可靠性阈值 r^pose/r^bearing/r^distance——都需要深入 `route_memory_agent.py`（4395行）尚未覆盖的部分，本次受时间限制未展开。
- **B1"264候选"数字**：NOT FOUND，已排除是另一件事（历史高成功率选集统计，非配对候选池）。
- **B3的87修正**：只做了单集（ep367）的原因定位和文本抠取验证，未做全项目范围的同类损坏扫描；B6 的百分比表仍按未修正的86分母展示。
- **C部分**：git 历史基本不可用（两个核心文件从未提交、两个文件唯一一次提交停在06-29），"参数是否冻结"无法给出干净的之前/之后判断，只能证明"已知的、带日期注释的改动"都晚于三批实验且默认关闭。
- **D1b（完整100ep shadow log 运行）**：**因 GPU 当前被另一 100ep 批次占用（23942/24564 MiB，约97%），按清单指示未执行**，只完成了 D1a 的设计方案。
- **E 成功判据数值**：NaVILA 论文原文未显式复述成功半径与是否要求主动STOP，只能推断（非直接引用）。

---

## A 部分：代码与配置提取

> 全部来自 `NaVILA-Bench/scripts/` 顶层文件（未使用任何 `backup_*` 快照目录）。运行时实际值均以对应 batch 的 `ep*_eval.log` 里的原始 argv 核实。完整版（含更多源码片段）见 `analysis/part_A_and_D1a_findings.md`。

### A1. 仲裁器冲突判据（条件2）

**状态：FOUND**

判定逻辑是"转向符号相反 + 角度差超阈值"的组合，且有一个连带的关键发现：`vlm_kind` 为 `unknown` 或 **`stop`** 时无条件判定冲突（直接导致 A7 的核心结论）。

**阈值**：`forward_conflict_bearing_deg`，默认 **30.0°**（`hint_action_arbiter.py:22`）。三批 oracle 消融链 argv 均未覆盖此参数，实际运行值=默认值。

**源码**（`hint_action_arbiter.py:240-253`，`_conflicts_with_hint`）：
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

### A2. β_t 到离散动作的映射

**状态：FOUND（VLM侧解析）+ PARTIAL（模型原生动作空间未找到）**

- **hint→期望动作**三分箱（`_desired_kind`，`hint_action_arbiter.py:198-201`）：`forward`（|β_t|≤`forward_cone_deg`=15.0°，`hint_action_arbiter.py:21`）、`left`（β_t>15°）、`right`（β_t≤-15°）。**符号约定：正角=左转，0°=机器人正前方**。
- **VLM文本→动作类别**（`_vlm_action_kind`，`hint_action_arbiter.py:170-180`）：子串匹配，不是数值分箱。
- **执行层完整动作集**（`get_vel_command`，`isaaclab_exts/omni.isaac.vlnce/omni/isaac/vlnce/utils/eval_utils.py:57-106`）：

| 动作类别 | 识别子串 | 输出 [vx,vy,ω] | 时长 |
|---|---|---|---|
| turn left/right | "45"/"30"/"15"/其他 | `[0,0,±π/6]` | 1.5/1.0/0.5/0.5s |
| move forward | "75"/"50"/"25"/其他 | `[0.5,0,0]` | 1.5/1.0/0.5/0.5s |
| stop | — | `[0,0,0]` | 0.0s |
| 无法识别 | — | `[0.5,0,0]` | 0.5s |

角速度恒为 π/6 rad/s，只有维持时长随声明角度变化。**该函数 2026-08-15 曾短暂改为通用数字解析又被回退**（真实数据里出现过"move forward 0.06 cm"这类幻觉距离，通用解析会静默算错）——这是 D1a 设计"不能碰这个函数"的直接依据。

**NOT FOUND**：NaVILA 模型自身训练时的原生动作空间/动作头定义——已搜索 `round_trip_eval.py`/`hint_action_arbiter.py`/`eval_utils.py`，未命中；大概率在训练代码库 `navila-isaac/NaVILA/`，超出本次 `scripts/` 范围。

### A3. 最小距离阈值 d_min

**状态：FOUND**

**变量名**：`min_anchor_distance_m` ｜ **数值**：0.35m（默认值，**无任何CLI flag可覆盖**，已逐行核对 `round_trip_eval.py` 里 `HintActionArbiterConfig(...)` 构造调用确认）｜ **来源**：`hint_action_arbiter.py:25`
**与 δ_a 的关系**：独立常量，不随 `--route_anchor_spacing_m`（默认1.0m）变化。
**触发行为**：`hint_action_arbiter.py:389-390`，直接返回 `override=False, reason="target_too_close"`，完全跳过仲裁、沿用 VLM 原始动作。

**B5 用日志反查交叉验证**：165条 `target_too_close` 记录里 distance_to_anchor 最大值 = 0.35820m，与代码阈值0.35基本一致（3条微超，差值<0.01m，判定时刻与记录position间的极小执行延迟可解释，不构成矛盾）。

### A4. 占据检查（条件3）

**状态：FOUND**

**表示形式**（`hint_action_arbiter.py:475-508` + `local_map.py:135-149`）：优先用 2D 占据栅格（`local_map.py:86-132`）→ 否则退回原始点云（`local_map.py:41-83`，高度滤波 z∈[-0.10,1.50]m）→ 都不可用则退回 topdown route map 图像（RGB均值<100.0判定障碍，`hint_action_arbiter.py:300`）。

**几何形状**：**不是扇区**，是沿目标方向的直线走廊（corridor），横向半宽 = `robot_radius_m`(0.30m) + `clearance_margin_m`(0.12m) = **0.42m**。

**检查半径 R_occ**：`max_clear_path_distance_m`，默认 **1.0m**（`hint_action_arbiter.py:26`）。

**判定准则**：二值判定，**不是**"自由栅格比例>阈值"——沿路径按 0.05m 步长采样，任一采样点周围走廊半宽内存在障碍即判不可通行（`local_map.py:81-82`）。

**信息来源**：当前帧，非累积地图——`round_trip_eval.py:4580-4581` 每个 `env.step()` 后重新计算。

### A5. 覆盖动作 a^β_t 的构造

**状态：FOUND**

不是"离散集中最接近β_t的那个"，也不是复合动作——**单一动作**，与 `_desired_kind` 三分箱一一对应：
- `forward`：固定步长 **75cm**（`forward_distance_cm`，`hint_action_arbiter.py:24`，不随距离变化）
- `left`/`right`：默认固定转 **45°**（`turn_step_deg`，`hint_action_arbiter.py:23`）；仅当 `turn_override_completes_full_angle=True`（三批oracle链均未启用）才转真实β_t角度

```python
def _replacement_output(kind, cfg, bearing_deg=None):
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
（`hint_action_arbiter.py:204-222`）

### A6. 冷却/连续覆盖上限

**状态：FOUND —— 三项全部为"无"**

- 每episode覆盖次数上限：**无**（全文件无计数器/上限字段）
- 冷却机制：**无**（唯一命中的 "cooldown" 是 `route_memory_agent.py` 的 quarantine 机制参数，与仲裁器无关，不要混用）
- 连续覆盖上限：**无**（唯一跨调用状态 `_trend_history` 仅服务于默认关闭、且已被2026-08-16硬编码禁用的 `trend_confidence` 机制）

**结论**：仲裁器每次决策都是无状态独立判定，不存在任何节流。

### A7. STOP 动作在仲裁器中的处理（最高优先级）

**状态：FOUND —— 关键发现：STOP 不被豁免，且在 `oracle_hint_action` 默认配置下可以被覆盖为移动指令**

1. **是否进入判定流程**：是，无条件进入（`round_trip_eval.py:4199-4200`，调用不检查 vlm_output 是否为 stop）。
2. **是否可能被判为冲突并覆盖**：**可以**。`_vlm_action_kind` 把 "stop" 识别为 `vlm_kind="stop"`，`_conflicts_with_hint` 第一行 `if vlm_kind in ("unknown","stop"): return True` —— STOP 与"无法解析输出"被同等对待，永远判冲突，除非被 `target_too_close`(A3) 或置信度门槛拦下。
3. **是否有显式豁免**：**否**。唯一能保护 STOP 的路径是 `stop_veto_enabled`（默认 `False`，CLI flag `--hint_action_arbiter_stop_veto`），但这是"低置信度时抑制可能错误的STOP"，不是"保护高置信度正确STOP"，且三批链路均未启用。
4. **`oracle_hint_action` 下的完整处理路径**（已用真实argv核实 `stop_veto_enabled=False`）：
   ```
   VLM输出含"stop" → arbiter.check()（无STOP豁免）
     → stop_veto 分支不触发（默认关闭）
     → _conflicts_with_hint("stop", desired, ...) 恒 True
     → 清路检查（A4）通过 → override=True，STOP 被替换成 "move forward"/"turn left/right 45 degree"
     → 清路检查未通过 → override=False，STOP 保留，回合可能在此步真正终止
   ```

**B4 用真实日志做的交叉验证**（重要）：`oracle_hint_action` 全批67次 return阶段 STOP 输出，**100%** 同步产生仲裁记录，但 reason 分布是 `target_too_close`26次 + `occupied_in_local_map_path`41次，**0次**落在override类reason，**0次**"提出STOP但实际执行了别的动作"。即：**代码层面STOP确实可以被覆盖，但在这两批实测数据里从未真正发生**（每次都恰好被 A3 的距离门槛或 A4 的清路检查挡住了覆盖路径）——这是一个重要的、需要在论文里如实说明的"理论风险 vs 实测未观测到"的区别，不能只写代码逻辑而不提日志验证结果，也不能只写日志结果而暗示代码里有豁免。

### A8. 完整超参数清单

**路由记忆构建**：δ_a=1.0m（`--route_anchor_spacing_m`，`round_trip_eval.py:192`，三批均用默认值）。LiDAR裁剪半径/降采样分辨率：**NOT FOUND**（不在 `scripts/` 顶层，可能在 Isaac Lab 传感器cfg）。

**返程定位**：多帧一致性窗口（仲裁器侧trend_confidence）=5（`hint_action_arbiter.py:118`，但该机制已被禁用，且是仲裁器自己的平滑窗口非relocalization层面）。正常候选集大小/recovery候选集/歧义判据：**NOT FOUND**，需专项深读 `route_memory_agent.py`（4395行，超出本次覆盖）。

**可靠性阈值** r^pose/r^bearing/r^distance：**NOT FOUND**，`route_memory_agent.py` 里有大量 "Trust-aware belief guard" 相关代码但未提取成阈值表。

**ICP设置**（`relocalization.py`，非Open3D，自实现2D ICP，`icp_rigid_transform_2d`，`relocalization.py:1289`）：
- 目标函数：`point_to_point`(默认) / `point_to_line` / `point_to_line_2p5d`；`ndt_2d` 是 point_to_line 的实验性别名（docstring明确非完整NDT实现）
- 最大迭代次数：函数默认24（`:1294`），**实际调用点全部显式传16**（`:1773,2016,2240,2452`等）——函数默认值从未在生产路径生效
- 对应点距离上限：`correspondence_threshold_m`=**0.45m**（`:1296`，调用点一致）
- 收敛判据：内点中位残差变化<1e-4提前退出，或达max_iterations，或内点数<8直接失败（`:1316-1335`）
- fitness/inlier阈值：**PARTIAL**——函数本身只返回原始统计量，接受/拒绝判定在下游 `route_memory_agent.py` 的 match_class 分类，本次未展开
- 初值来源：非单一固定值——`icp_seed_sweep_2d`（`:839`）做多初始角度扫描取最佳匹配

**终止验证**（`stop_gate.py`，**注意：三批链路里只有第三批 `oracle_hint_action_stop` 启用**）：
- 距离阈值：r_in=r_out=**3.0m**（`stop_gate.py:161-162`，运行时实测一致）——即无内外滞回区间，同一个边界。这也回答了"成功半径是否3.0m、Outbound/Return是否一致"：是3.0m，且看到的是同一常量。
- 四种终态（`stop_gate.py:8-12`，非清单猜测的三分支）：
  ```
  ACCEPTED  VLM发出stop，高置信度，d≤r_in           → 执行stop
  VETOED    VLM发出stop，高置信度，d>r_out          → 抑制stop，注入移动
  DEFERRED  VLM发出stop，低置信度 或 r_in<d≤r_out   → 放行不管
  FORCED    VLM未发出stop，高置信度，d≤r_in持续≥confirm_steps → 强制停止
  ```
- approach trend窗口、defer最大延迟步数：**PARTIAL**，未逐项提取具体数值

**执行协议**：execution budget、Confirm阶段360°扫描：**NOT FOUND**（`round_trip_eval.py`5134行规模，本次搜索到变量名 `max_episode_steps` 但未定位赋值来源）。

### A9. Hint 模板生成代码

**状态：FOUND**

**生成函数**：`route_memory_agent.py:4330-4394`（`_make_anchor_hint`，compact模式，三批均用此模式）：
```python
return (
    "[System Hint: route anchor "
    f"A{progress.target_anchor_index} is {anchor_distance:.2f} m away, {anchor_direction}; "
    f"estimated remaining route via anchor is {remaining:.2f} m; "
    f"{vector_label} dx={progress.target_dx_m:.2f} m, dy={progress.target_dy_m:.2f} m.]"
)
```
与论文示例逐字匹配。

**方向词表**（`route_memory_agent.py:4367-4374`）：`at your current position`(距离<0.35m) / `ahead`(|bearing|≤**10.0°**) / `{X} deg to your left`(bearing>0) / `{X} deg to your right`(bearing≤0)。

**⚠️ 重要发现，此前未被记录**：**hint模板的"ahead"阈值是10°，仲裁器`_desired_kind`的forward圆锥阈值是15°**——两套分箱**不是同一套**，数值不同（左右符号约定一致）。论文若声称二者共用同一套分箱需要更正。

**"estimated remaining route"**：`anchor_distance + anchor_route_remaining_m`（到当前锚点距离 + 该锚点之后沿路线到终点的累计间距），非单纯累加剩余锚点间距。

**hint拼接方式**：PARTIAL，`inject_hint`函数体内部细节未完全读取。
**oracle_hint vs oracle_hint_action模板是否逐字相同**：PARTIAL，代码路径上无理由不同（唯一差异`--hint_action_arbiter`只影响是否覆盖动作，不影响模板生成本身），但未做要求的实际日志diff。

---

## B 部分：日志统计

> 完整脚本见 `analysis/b1_pairing_tolerance.py`、`b2_failure_magnitude.py`、`b4_stop_step_arbiter.py`、`b5_dmin_reverse_check.py`、`b6_b7_b8_b9.py`；输出CSV `b1_pairing_distances.csv`、`b2_failure_magnitude.csv`。方法论：全部基于原始日志/measurement JSON 重新计算，不采信既有文档数字（含本项目自己的README/memory），仅交叉引用。

### B1. 配对容差统计（最高优先级）

**数据源**：`vln_ce_isaac_v1.json.gz`（1077 episodes）+ `high_outbound_success_100ep_selection.tsv`（100对）

| 量 | mean | std | median | min | **max** |
|---|---|---|---|---|---|
| d_start | 1.7695m | 1.4334m | 1.8226m | 0.0000m | **5.5222m** |
| d_goal | 1.7198m | 1.5928m | 1.5182m | 0.0000m | **7.0231m** |

- d_start>1.0m：**70/100** ｜ d_start>2.0m：**43/100**
- 最大5对：episode_id=494(idx304) 5.522m；314(idx205) 4.796m；868(idx498) 4.764m；286(idx189) 4.198m；500(idx310) 4.070m
- 直方图分箱（0-0.25/0.25-0.5/0.5-0.75/0.75-1.0/1.0-1.5/1.5-2.0/2.0-3.0/3.0-5.0/5.0+）：25/5/0/0/15/12/21/21/1

**⚠️ 需要论文正面处理**：43%的配对残余偏移>2.0m（3.0m成功半径的2/3），最大值5.52m甚至**超过成功半径本身**。这不是可以轻描淡写带过的噪声下限，需要明确讨论或对pair集做筛选。

**配对生成代码**（`instruction_rewriter.py:289-376`，`_ordered_path_match`+`_find_reverse_path_neighbor`）：
- τ_pair：`tolerance_m`/`neighbor_tolerance_m`，默认**2.0m**（`:332,398`）
- 判据：**不是**Hausdorff距离，是**有序贪心最近邻逐点匹配**——每个candidate点在target路径里从上次匹配位置往后找最近点，距离≤tolerance_m计入匹配并单调推进游标；额外要求 `matched≥max(2,min(len)-1)` 且 `coverage=matched/min(len)≥0.8`（`:356-358`）
- 候选池"264"：**NOT FOUND**，已排除是README第6节的"264"（那是另一件事——历史成功率候选池，非本函数的配对候选池）

### B2. 失败幅度证据（oracle_hint，54例return失败）

**d_e（终点到起点距离）**：median=5.687m，Q1=3.917m，Q3=7.742m，min=0.000m，max=16.527m
- d_e>5m：**35/54=64.8%** ｜ d_e>10m：**7/54=13.0%**
- 最大5例：ep738(id1264)16.527m；ep463(id785)14.882m；ep86(id126)13.040m；ep733(id1256)12.768m；ep479(id810)11.401m

**d_min_e（return全程到起点最小距离）**：median=3.838m，Q1=2.541m，Q3=6.041m，min=0.000m，max=13.691m
- d_min_e≤3.0m（曾进入成功区又离开）：**17/54**（episode_id: 129,314,128,512,1644,1643,1154,1439,1517,1368,361,494,718,720,978,1256,719）
- d_min_e>3.0m（全程未接近）：**37/54**
- 曾进入组 d_e中位数3.873m ｜ 从未接近组 d_e中位数6.248m（分化明显）

**"终止于成功区内但仍判失败"**：**清单预期2例，实测为3例**（ep844/id1439 1.981m、ep304/id494 0.000m、ep427/id719 2.636m），三例原因一致：几何上进入成功半径，但return阶段从未发出STOP文本（`success_requires_stop=True`时判失败）。**这个数字差异（2 vs 3）需要在手稿里核实更正。**

### B3. 分母口径核对（87 vs 86）—— 根因已定位，是真实数据完整性bug

差集为 **episode_idx=367**：产生了仲裁日志，但 `summary.tsv` 该行的 `outbound_success`等字段全部为空（exit_code=0，正常退出）。`ep367_eval.log`确认测量文件已写入，但 `measurements/601.json` 用 `json.load` 报 `JSONDecodeError`（两段JSON片段错误拼接，疑似写入竞态）。用纯文本grep绕过JSON解析，直接抠出 `"outbound_success": true`/`"return_success": true`/`"round_trip_success": true`——**该episode实际round_trip_success=true**。

**结论**：不是"outbound失败但仍产生仲裁记录"，也不是重复计数，是**批次驱动脚本因JSON写入损坏静默留空**。**修正后 oracle_hint_action 的 outbound_success 应为87（非86），round_trip_success应为53（非52）**，连带影响B6所有基于"86"的百分比。

**⚠️ 潜在系统性问题**：同样的 `JSONDecodeError: Expecting ',' delimiter` 模式在完全不同的一次运行（08-16 `tiered_v4_quarantinefix` 离线回放，ep889/ep1040）中也出现过——暗示这可能是measurement JSON写入路径上一个尚未根因排查、跨批次重现的bug，建议开独立investigation。

### B4. STOP步在仲裁器日志中的落点

**结果（oracle_hint_action，87个episode）**：
- Return阶段 `a_VLM==STOP` 总步数：**67**
- 67条**全部**同时出现在同一step的arbiter decision记录里（100%覆盖）
- reason分布：`target_too_close`26次，`occupied_in_local_map_path`41次；**0次**落在override类reason
- "提出STOP但最终执行别的动作"：**0例**

**结论**：日志实测强烈支持STOP从未被真正覆盖为移动动作——但这只是"输出侧"证据，需配合A7的代码层面豁免缺失分析一起呈现（"理论上可以覆盖，实测中从未发生"）。

### B5. 用日志反查 d_min

165条`target_too_close`记录反查distance_to_anchor：max=**0.35820m**，min=0.00626m。与A3代码阈值0.35基本一致（3条微超<0.01m，可用执行延迟解释）。

### B6. 精确化百分比

| 配置 | outbound_success | arrival(d_min≤3.0m或d_e≤3.0m) | success | termination deficit |
|---|---|---|---|---|
| oracle_hint | 86 | 49 (56.98%) | 32 (37.21%) | 17 (19.77pt) |
| oracle_hint_action | 86*（应为87，B3已修正但本表未重算） | 64 (74.42%) | 52 (60.47%) | 12 (13.95pt) |
| oracle_hint_action_stop | **87**（属实，与前两者不同） | 74 (85.06%) | 71 (81.61%) | 3 (3.45pt) |

stop相对action：success +19（52→71），arrival +10（64→74），deficit -9pt（13.95→3.45）。**oracle_hint_action_stop的87与另两批86不同的原因已查清：并非隐藏差异，就是B3的同一个JSON损坏bug**——action批次本该也是87。**待办**：把ep367完整字段人工补全后重算本表。

### B7. 仲裁器覆盖率统计复核（oracle_hint_action）

- 产生决策记录episode数：**87** ｜ 总决策数：**3094** ｜ 总override数：**503** ｜ 总体override率：**16.26%**
- reason分布：`vlm_action_consistent`1699(54.91%)，`occupied_in_local_map_path`727(23.50%)，`vlm_conflicts_with_clear_hint`503(16.26%)，`target_too_close`165(5.33%)
- 每episode覆盖率：median=0.1333，mean=0.1710 ｜ 至少覆盖一次：**70/87** ｜ 平均决策步数：35.56
- **按return成功分组**：成功组(n=52) median=0.1333/mean=0.1544；失败组(n=34) median=0.0859/**mean=0.1996**——**失败组均值覆盖率反而更高**（更难的episode纠正次数多但仍失败）。**论文若用覆盖率论证arbiter有效性需注意不要选择性忽略这一点。**

### B8. 交叉验证运行（canonical-100版）

- 未跑满98/100，outbound_success=37/98
- 产生决策记录episode数：**54**（>37，与B3同类模式，暗示canonical-100批次可能也有个别JSON损坏，本次未逐一排查）
- 总决策数：**2480**，总override数：**433**，override率：**17.46%**（与既有memory数字完全一致，交叉验证通过）
- episode_idx重叠：与high-success-100 **30/100**重合（仅数字索引重合，未做episode_id级别的严格核实）

### B9. "4.3%"历史来源 —— 重要更正，与项目既有README/memory不一致

| 批次 | eval.log文件数 | 决策数 | override数 | override率 |
|---|---|---|---|---|
| `stop_gate_r3_hint_arbiter_hard11_20260630`(hard-11) | 9 | **348** | **15** | **4.31%** |
| `oracle_shadow_loftr_v4_30_return_anchor_fix_20260701`(30ep) | 28 | **435** | **79** | **18.16%** |

**348/15≈4.3%这个精确数字实际来自hard-11单独一批，不是30ep批次，也不是两者相加**——项目README第2节与08-13的memory都写"30ep那批...348次决策...15次替换"，**这个归属是错的**，30ep批次真实数字是435/79，跟348/15完全对不上。

**⚠️⚠️ 需要用户决定**：论文若引用"4.3%"，精确来源应改写为"hard-11批次（9集，348次决策）单独的数字"；若想用两批合计，正确数字是 (15+79)/(348+435)=94/783≈**12.0%**，不是4.3%。这两个数字该用哪个，取决于论文原句的确切语境（单独描述hard-11 vs 描述"整体历史批次"）。

hard-11批次本应11集，实际只找到9个eval.log，另2集缺失原因未深挖。

---

## C 部分：方法冻结时间线核查

> 完整版见 `analysis/part_C_findings.md`。

**仓库定位**：`NaVILA-Bench`本身是git仓库；`hint_action_arbiter.py`/`stop_gate.py`**从未被git追踪**；`route_memory_agent.py`/`round_trip_eval.py`唯一一次提交停在**2026-06-29**（`3bfdd135`），之后6971行修改全部只存在工作区，从未commit。

**结论：git历史对本次审计基本不可用**，无法给出严格的"冻结前/后"判断。改用argv配置快照+文件mtime+代码内日期注释做替代核查：

- 三批实验实际起始时间（`batch.log`首行）：oracle_hint 08-11 23:22 ｜ oracle_hint_action 08-12 14:33 ｜ oracle_hint_action_stop 08-13 09:10
- 四个核心文件当前mtime全部晚于三批实验（最晚一批08-13 09:10）——从纯mtime看，参数集是实验**之后**才最后修改的
- 但逐一核实：`hint_action_arbiter.py`里可归因到具体日期的改动全部标注**08-15/08-16**（晚于三批实验），且全部是**新增、默认关闭**的开关（`stop_veto_enabled`08-03、`turn_override_completes_full_angle`08-15、`trend_confidence_enabled`08-15且08-16已被硬编码禁用）——不会追溯性影响已跑完的三批
- **NOT FOUND**：**未标注日期的既有常量**（如`forward_cone_deg=15.0`、stop_gate四个子阈值）是否在08-11~08-16间被静默改过——没有版本历史可查，无法排除

**配置快照对比（三批argv完整diff）**：三批间**没有任何非计划内差异**，每步新增flag精确对应消融链设计意图，无意外参数漂移。

**独立dev/tuning子集检查**：**FOUND（否定结果）**——未找到独立于High-success-100之外的调参子集。但发现08-15新代码的冒烟测试（`ONLY_EPISODES=264 646 484`）用的正是High-success-100 manifest内的episode。**⚠️ 需要论文如实说明**：这意味着08-15起的三处新修复是直接观察该测试集本身的失败案例（如ep646、ep889）设计和验证的——不过这些新机制默认关闭，不影响本报告审计的三批oracle系列实验本身的数据完整性。

---

## D 部分：Shadow arbiter log

### D1a：实施设计（已完成，仅设计，未改代码/未跑仿真）

**GPU状态**：撰写本报告时 `nvidia-smi` 显示 23942/24564 MiB（约97%）被另一在跑的100ep批次占用。**按清单指示，未做任何仿真运行**，也未做2-3 episode冒烟测试（冒烟测试本身需要短暂占用GPU）。

**关键前置发现**：`round_trip_eval.py:4129-4180` 已存在一个 `route_shadow_progress`（"shadow_non_oracle"）机制——"用oracle覆盖hint内容时，同时偷偷跑一遍agent自己的非oracle估计做对比记录"，与D1要的"跑一遍但不生效"是同一设计模式，可以直接复用这个模式而非从零发明。

**最小改动方案**：
1. 新增CLI flag `--hint_action_arbiter_shadow_only`（放在`round_trip_eval.py`约1438行`--hint_action_arbiter`附近）
2. `round_trip_eval.py:4114`附近：shadow_only生效时跳过`inject_hint`调用，`query_instruction_text`保持不变，但仍执行progress计算（纯计算不碰指令文本）
3. `round_trip_eval.py:4233`的`if _last_hint_action_decision.override:`外面加`and not shadow_only`条件——`hint_action_arbiter.check()`调用本身完全不用改，只是不消费其override结果

这样实际驱动机器人的`stream_output`/`vlm_vel_commands`在shadow_only模式和纯`language_only`模式下**逐字节相同**（结构性保证，不靠事后核对），满足清单"同一episode改动前后轨迹完全一致"的要求。

**一致性判据复用**：直接满足，无需重构——`HintActionArbiter.check()`内部就是调用`_conflicts_with_hint`（A1），shadow模式直接复用同一实例同一方法，只是不消费其输出。

**日志字段**：清单要求的字段已全部存在于`HintActionDecision.as_log_dict()`（`hint_action_arbiter.py:149-167`），唯一需要新增的是外层`shadow_only: bool`标记，防止后续分析脚本混淆两种运行记录。

**冒烟测试预估（未执行）**：单episode增量预计<1秒（仲裁器/route_memory全是CPU numpy运算，无额外GPU推理）；显存占用预计与`language_only`基线几乎相同。

### D1b：完整运行

**未执行**——GPU当前不空闲。待后台100ep批次（`policy_v2_active50_replay_on_highsuccess100ep_20260816`）结束或用户明确指示后再启动。

---

## E 部分：文献核实

> 完整版见 `analysis/part_E_findings.md`。

**50.2%的确切出处**：NaVILA论文（arXiv:2412.04453）**Table 4**，行标签`NaVILA-Go2-Vision`，列`SR`，**Val-Unseen** split。表格列头顺序：`Low-level Observation | Proprio. | LiDAR | Height Scan | NE↓ | OS↑ | SR↑ | SPL↑`。

**确认**：该50.2%确实对应 **Go2 + vision** 设定（非GT depth、非H1平台）。

**成功判据数值：NOT FOUND（本文未显式复述）**——论文正文仅写"沿用先前工作相同度量"，未在文中重新给出成功半径数值或是否要求主动STOP。可从`OS`（Oracle Success）与`SR`并列的表结构**推断**`SR`大概率要求主动STOP（否则`OS`列无独立存在意义），但**这是推断，非论文原文直接证据**，请勿作为确定引用值写入论文。建议下一步查该论文引用的先前工作原文（通常是Krantz et al. ECCV 2020）坐实数值。

---

## 需要用户决定的事项汇总

1. **B9："4.3%"的正确归属**——是单独引用hard-11批次的4.31%，还是改用两批合计的12.0%？取决于论文原句语境。
2. **B3/B6：ep367 JSON损坏bug是否要修正后重算**——oracle_hint_action的outbound应为87、round_trip应为53，当前B6表仍按86展示。
3. **A9：hint模板"ahead"阈值(10°) vs 仲裁器forward圆锥阈值(15°) 不是同一套**——若论文声称二者共用同一分箱需要更正。
4. **B2：清单预期的"2例终止于成功区内仍失败"实测为3例**——需要核实手稿数字。
5. **B1：43%的episode配对存在>2.0m的残余偏移，最大5.52m超过成功半径本身**——需要论文正面讨论或对pair集做筛选，不能作为可忽略的噪声下限带过。
6. **C：08-15新代码的冒烟测试复用了High-success-100内部的episode**——不影响本报告审计的三批数据本身，但若论文要报告新机制效果，需要如实说明"同一测试集上诊断+修复"的方法论关系。
7. **D1b完整仿真运行**——需等GPU空闲（当前被`policy_v2_active50_replay_on_highsuccess100ep_20260816`批次占用，预计还需数小时）或用户明确指示抢占。
8. **B3附带发现的JSON写入损坏，疑似跨批次重现的系统性bug**（另在08-16的`tiered_v4_quarantinefix`回放中也出现）——建议是否要开一个独立investigation专门排查根因。

## 脚本清单

- `analysis/b1_pairing_tolerance.py` → `analysis/b1_pairing_distances.csv`
- `analysis/b2_failure_magnitude.py` → `analysis/b2_failure_magnitude.csv`
- `analysis/b4_stop_step_arbiter.py`
- `analysis/b5_dmin_reverse_check.py`
- `analysis/b6_b7_b8_b9.py`
- （B3的JSON损坏调查是交互式grep/python单行命令完成，过程记录在`part_B_findings.md`的B3节，未单独存成脚本）

## 各部分完整版文件

- `analysis/part_A_and_D1a_findings.md`（A1-A9代码抄录 + D1a设计方案完整版，含更多源码片段与NOT FOUND清单）
- `analysis/part_B_findings.md`（B1-B9完整版，含运行目录映射核实过程）
- `analysis/part_C_findings.md`（时间线核查完整版，含git log原始输出）
- `analysis/part_E_findings.md`（文献核实完整版）
