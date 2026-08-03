# 设计方案:① 卡死倒车恢复(stuck-recovery) ② 多视角一致性(multi-view)
2026-07-22。两者独立、默认关闭、candidate 先行。证据见本 session 的 ep5/ep653(倒车)与 ep134/813/669(多视角)分析。

---

## ① 卡死倒车恢复(stuck-recovery)

### 动机(已证实)
ep5:anchor 对、hint 准(误差1–6°)、VLM 听话,机器人走到 (1.1,3.5) 后**命令0.50m/s、实际0.026m/s** 楔死,之后再准的 hint 也 0mm。ep653:tracker 超前1、hint 偏~25° 把它带偏到12m,终点同样物理楔死(命令0.5/实际~0.05)。**共同点:一旦楔死,hint 正确与否都无关,唯一出路是主动倒出来。**

### 检测(以 VLM 查询为单位,无需真值)—— 2026-07-22 修正
不再限制"命令前进"(楔在墙角时 VLM 可能发转向;且要顺带救 ep491 转圈)。改为**按 VLM 查询计数**:
- 把 return 轨迹按 VLM 查询切段(用 `last_vlm_step` 变化分段,每段 = 执行一条 VLM 指令的那 ~50 步)。
- 每段:`net_disp = |pos_段末 − pos_段初|`(该指令带来的净位移,指令类型不限)。
- 维护连续计数:`stuck_queries` = 连续多少段 `net_disp < MOVE_MIN`。**当 `stuck_queries ≥ N_QUERIES` 触发。**
- **N_QUERIES 就是防误伤阀**:正常的短暂转身重定向 1–2 段内就恢复前进(计数清零);楔死(ep5/653)、转圈(ep491)会一直累积到 N。
- 覆盖三类:前进楔死、墙角转向楔死、原地转圈。

参数(建议初值,离线校准):`stuck_move_min_m=0.15`(单条指令净位移下限)、`N_QUERIES=4`(连续几条无净位移)。

**可选二级护栏**(进一步防误伤长转身):同时要求"未朝目标收敛"——若 `stuck_queries` 段内 `|bearing_to_next|` 一直没变小,才算真卡;正常长转身会看到 bearing 单调收敛。默认可先不开,视离线假阳性率决定。

### 恢复动作序列(脚本化,完全接管 VLM)
状态机 `NORMAL → WEDGED → RECOVERING → NORMAL`:
1. **转身面向 current**:用 `route_memory.bearing_to_current_deg` 原地旋转到 |bearing_to_current|≈0(上限 `recover_max_turn_steps`)。若 `relocalization_confidence < conf_floor`,跳过定向、直接第2步做直线倒车(负 vx)。
2. **退向 current**:面向 current 后前进(=相对楔死方向倒退)`recover_back_m`(建议0.6m)或直到 `actual` 位移恢复(说明已脱困)。
3. **重新面向 next**:旋转到 |bearing_to_next|≈0。
4. **交还控制**:回 NORMAL,清空检测窗口。

### 防回归护栏
- `recover_max_steps`(单次恢复上限,如120步)+ `recover_max_attempts_per_episode`(如5),超限则放弃(避免恢复死循环)。
- 若倒车本身也不动(退向 current 时 actual 仍≈0)→ 升级:换方向转45°再试;仍失败则放弃本次、回 NORMAL 让 VLM 继续(不无限卡在恢复里)。
- current 定向只在 relocalization 置信足够时用;否则退化为"直线倒车 + 小角度扫动"这种不依赖定位的盲脱困。
- 与 stop_gate/arbiter 协调:RECOVERING 期间**抑制 stop_gate 判停**、**arbiter 让位**(恢复优先级最高)。

### 集成点
- 新模块 `scripts/stuck_recovery.py`(类 `StuckRecovery`,镜像 `stop_gate.ReturnStopGate` 的结构)。
- `round_trip_eval.py` return 控制环:每步喂 (cmd, actual_pos, route_memory);RECOVERING 时用它返回的脚本动作**覆盖** VLM 动作。
- flag:`--stuck_recovery`(默认关)+ 上述参数。

### 验证
- **可离线**:把**检测器**跑遍 20 个 ep 的真实轨迹(clean 用 fix-ON,崩溃用 batch2)→ 确认在 ep5/ep653 楔死处触发,在 9 个成功 ep **不误触发**(零假阳性)。这一步 GPU-free,先做。
- **需 live**:恢复动作改变轨迹,离线模拟不了 → ep5/ep653 各一集 live smoke,看是否脱困并完成 return。

---

## ② 多视角一致性(multi-view,针对自信地错)

### 动机(已证实)
自信地错 = scalar 特征干净 + pose 错(多为旋转混叠),A/B/C/closure-放松 全瞎(0.84天花板),单帧 basin 也救不了(错答案单帧干净胜出)。**但错误的旋转锁是视点相关的**:ep134 anchor14 贴近读1°/远处121°;ep813 next5 分歧随靠近收敛。→ 同一 anchor 从多个机器人位置读,真值 anchor 的**隐含世界位姿应一致**,自信地错的会在**旋转**上发散。这是唯一与 scalar-U 正交、且不需视觉的信号。

### 复用+改造现有 `short_baseline_disambiguation`
现状问题:只**标记**不**行动**;且**触发率仅0.1%**(晋升总在攒够位移前提交)。改造:
1. **与晋升时机解耦、后台连续跑**:维护每个 anchor 的"读数 buffer",每条读数记 `(return_frame_robot_pose, dx, dy, dtheta)`。
2. **隐含 anchor 位姿**:`anchor_pose_i = robot_return_pose_i ⊕ (dx_i, dy_i, dtheta_i)`。相邻读数同在 return 帧,短基线(0.3–1m)内 return 帧漂移可忽略,用两读数间的**相对运动**把隐含位姿归一到公共帧再比。
3. **一致性度量**:对来自 ≥`min_baseline` 分离的 ≥`min_views` 条读数,算隐含 anchor **yaw 的散布**(和位置散布)。散布大 = 视角间不一致 = 自信地错。谓词 `_anchor_multiview_inconsistent(idx)`。

### 行动(把 flag 接到三处,分别对应三个失败集)
- **next 不一致** → withhold 晋升(abstain+stall 阀,遵循"弃权不封杀"),或纳入共享 max_chain quarantine。
- **current 不一致** → **扩展 Injection B**:B 的触发从"current scalar-U 高"扩为"**或 current 多视角不一致**"→ 豁免 current 对 next 的否决。**这正是 ep813 的修法**(current6 自信地错、U 检测不到,但多视角能抓)。
- **喂给 stop_gate 的读数不一致** → **扩展 Injection C**:标 `distance_authority_low_reliability` → defer。**这正是 ep669 的修法**(anchor3 骗停车,U 低但多视角不一致)。

参数(建议初值):`multiview_min_baseline_m=0.3`、`multiview_min_views=3`、`multiview_yaw_spread_thresh_deg=30`、`multiview_window=8`。

### 诚实的局限
只抓**视点相关**的自信地错。真正对称走廊(两位置点云几乎全同)→ 错锁跨视角也一致 → 多视角同样被骗 → **这半残差只能靠视觉**。故多视角是便宜的部分解,不是全解。

### 防回归
- 用 `min_baseline`/`min_views` 要求"足够分离的足够多视角"才判定,避免单条噪声误伤。
- 对 next 用"弃权不封杀 + stall 阀",对 current 只"豁免否决"不驱逐,对 stop 只"defer 不强停" → 三处都是保守放松,不制造新的错误动作。

### 验证
- **可离线且必须先做(feasibility)**:对 15 个 clean ep 的每个 anchor,算隐含-anchor-yaw 散布,用真值(自信地错 = bearing 错 + U 低)打标签,量化**散布能否把"自信地错"从"真好"里分出来**(AUC 式),重点测 ep134/813/669 + 之前那 245 个 carve-out 坏样例。**若散布对这些样例有区分力 → 值得做;若没有 → 说明这些是对称走廊那半,直接转视觉。** GPU-free,先做,作为 go/no-go。
- **需 live**:接入三处后的真实回程率,放进下一轮 fix-OFF vs fix-ON A/B。

---

---

## 离线 GO/NO-GO 结果(2026-07-22 已测)

### ① 卡死检测器 —— ✅ 通过
判据:连续 `N_QUERIES≥6` 条 VLM 指令、每条净位移 `<MOVE_MIN=0.15m`,**且** `belief 离家 > 5.0m`。
20 ep 离线:**9 个成功集零假阳性;4 个目标(ep5/491/653/994)全命中**。ep88(成功、28 次无进展但离家 3.4m)、ep1038(4.8m)被离家门槛正确排除。
建议参数:`N_QUERIES=8`(留裕量)、`MOVE_MIN=0.15m`、`belief_far_min=5.0m`。
**新增 guard**:VLM 近期在发 stop 指令则不触发倒车(防 ep813 类"自信地错 tracker 以为离家远、实则已到家"的误触发)。
→ **值得做。** 检测器纯离线可验证;恢复动作需 ep5/653 live smoke。

### ② 多视角一致性 —— ❌ 不做(否定)
用隐含-位置跨视点分歧(局部窗、基线≥0.3m):AUC 仅 **0.737**,和 scalar U(0.80)同档。
- 漏:T=0.3m 召回63%/误伤29%,T=0.5m 52%/21% —— 做硬门控会回归(同 closure carve-out 量级)。
- **在失败主体(对称走廊 anchor)上失效甚至反转**:ep134 a15(0.19 vs 0.10)、ep669 a3(0.25 **<** 1.74)、ep813 a6(0.71 **<** 1.56)—— 错锁跨视角一致 → 低分歧 → 看着像好的。
- 只能抓视点相关那半(非失败主体)。
→ **不值得做成门控。** 自信地错的主体是 LiDAR 物理不可解的对称走廊,**只能靠视觉**。多视角搁置。

---

## 落地顺序(建议,按 go/no-go 更新)
1. 先做两个**离线 go/no-go**:倒车检测器的零假阳性验证 + 多视角散布的区分力 AUC。都不占 GPU。
2. 通过后,在 candidate 落代码(默认关 flag + 单测),live smoke(倒车:ep5/ep653;多视角:ep134/813/669)。
3. 连同已完成的 trend 共享 max_chain,一起进下一轮 100ep A/B。
4. 视觉融合仍是独立大决策,按 A/B 的真实增量再定。
