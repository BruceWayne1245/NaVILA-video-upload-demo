# 2026-07-26：50ep Active V2 失败分析与下一步架构计划

## 结论摘要

这次分析只统计 **outbound 已成功** 的 episode；outbound 失败不进入 round-trip 成功率分母。

截至冻结分析点（ep687）：

- 有效 capture：34
- outbound 失败：4（从后续分析中剔除）
- outbound 成功：30
- 严格 round-trip 成功：18/30 = **60.0%**
- near miss：2（ep93：3.418 m；ep680：3.470 m）
- 含 near miss：20/30 = **66.7%**

Route1 已公布的最好结果是 12/19 = 63.2%，含 near miss 为 13/19 = 68.4%。两个实验不是同一 cohort，样本都很小；当前差异没有统计意义，不能据此断言 Active V2 比 Route1 更差或更好。

真正清晰的信号是失败结构：

- 12 个严格失败中，9 个是目标半径外的 VLM 提前停止；
- 2 个是物理卡住并耗尽恢复预算；
- 1 个是物理 termination/reset 污染了测量。

因此当前的主要架构问题不是“V2 整体准确率不够”，而是：

> V2 作为 Route1 全部过滤逻辑之后的末端否决器，只能拒绝证据，却不能修复 anchor 状态；同时，它还会撤销 Route1 的 stop veto。结果是长期 route-hint 空窗和一次漏拦即失败的 stop 风险叠加。

## 代码与证据边界

本分析以 GitHub `main` 的最新 README 和 investigations 为权威背景，并使用本次 50ep 隔离运行目录中的实际 runtime provenance 与日志进行数据分析。

本次 Active V2 运行使用隔离目录：

`/home/teambruce/navila-reliability-v1_1-policy-v2-active50-20260725`

关键 runtime hash：

- `round_trip_eval.py`：`437f35851d93e369b5573ce62140fac09ca93d2581b32d5fbde25dae43943551`
- `route_memory_agent.py`：`7120438c2bb44b3a3784a079e1c0f372af0dca265d1bcb3912a196e1c54cbc02`
- V2 policy：`73acb4740d2c8baba2128dcb612d0ab8fc601f4db5fea70c6818b695cf35f1bc`

需要注意一个 provenance 差异：GitHub 当前文档只记录到 V2 shadow/readiness；本次 active enforcement 的批准与运行配置仍只存在于本地实验产物中。因此，本文件记录的是对该本地 active run 的后续调查，不应把它误读为 GitHub 中已经完成 active handoff 的证据。

## 失败分解

### 1. 九个目标半径外的提前停止

| Episode | 最终距离 | 最小距离 | 终止前 hint 状态 |
|---:|---:|---:|---|
| 93 | 3.418 m | 3.418 m | suppressed |
| 95 | 4.205 m | 4.205 m | suppressed |
| 205 | 5.495 m | 2.448 m | suppressed |
| 264 | 4.198 m | 4.198 m | suppressed |
| 276 | 12.094 m | 12.094 m | 无可用 hint |
| 366 | 5.319 m | 5.319 m | suppressed |
| 367 | 5.771 m | 5.771 m | suppressed |
| 646 | 9.648 m | 9.648 m | 无可用 hint |
| 680 | 3.470 m | 3.470 m | suppressed |

九个 episode 的共同点：

- terminal hint arbiter 均为 `low_relocalization_confidence`；
- 没有 hint override；
- 最终记录的 stop gate 决策均为 `deferred`；
- 7/9 的最后 route hint 被明确 suppress，另外 2/9 没有可用 hint；
- 8/9 的 authority distance 大于 3 m；ep367 虽小于 3 m，但 authority confidence 仅 0.2。

在 ep93、205、366、680 中，Route1 原本给出 `vlm_stop_veto`，V2 以“不信任该 anchor”为由取消 veto，并将结果改为 `deferred`。其余五个 episode 在基线中也因低置信度或低可靠性而没有形成 veto。

这构成当前最危险的组合：

1. hint 被压制，VLM 缺少持续的路线约束；
2. VLM 可以反复提出 stop；
3. stop gate 必须每一步都拦住；
4. V2 只要在某一步取消 veto，episode 就会终止失败。

### 2. 两个物理卡住

- ep5：54.1% 的 forward frame 速度低于 0.05；三次恢复尝试耗尽；最终 8.872 m，最小 8.862 m。
- ep491：46.5% 的 forward frame 速度低于 0.05；恢复尝试耗尽；最终 6.700 m，最小 3.458 m。

它们是明确的 locomotion/recovery 失败，但 route state 的长期错误或空窗会使系统更容易持续向障碍施加同一动作，所以不能完全与 anchor 架构割裂。

### 3. 一个 termination/reset 测量污染

ep19 在物理 termination 后发生约 5.758 m 的零速度 reset jump。原始测量误报为 0 m；剔除 reset frame 后，真实最终距离约 5.744 m，最小约 4.004 m。

## Route-hint 为什么被拒绝得如此多

在 30 个 outbound-success episode 中：

- route hint 提案：892
- 被 block：575
- block 率：**64.5%**

成功 episode 的 block 率为 62.6%，失败 episode 为 67.0%。差异不大，说明“拒绝次数多”本身还不是充分的失败判据；关键是拒绝是否造成长时间、关键路段的 hint starvation。

### ep5

用 world pose 对目标 anchor 的 bearing/distance 做离线 truth check，定义：

- bearing error ≤ 30°
- distance error ≤ 0.5 m

则：

- 73 次提案；
- allow 8 次，8 次都正确；
- reject 65 次，其中 **29 次其实可用**，36 次确实错误；
- allow precision = 100%；
- usable-hint recall = 8/37 = **21.6%**。

29 个 false reject 中：

- anchor11：7 次；
- anchor6：22 次。

更重要的是，29 个“最终 route-memory hint 正确但被 V2 拒绝”的样本里，只有 7 个对应的 latest raw candidate 本身也正确；另外 22 个样本中，raw candidate 是错的，但 Route1 经过滤波、积分和状态稳定后输出的 route-memory hint 是对的。

这说明目前存在明确的 **语义/时间层错位**：

> V2 判断的是最新 raw candidate，却用这个判断去封禁已经经过 Route1 时序处理的 stateful hint。

### ep491

- 73 次提案；
- allow 4 次，4 次都正确；
- reject 69 次，69 次都错误；
- 被拒提示的 bearing error 中位数为 128.6°；
- distance error 中位数为 6.01 m。

这里 V2 的拒绝是正确的。问题是系统停在错误的 next anchor 上太久：

- current11/next10；
- 随后 current10，next 依次尝试 9、7、6、5；
- next5 持续 61 次 query，所有 hint 都错误。

ep5/ep491 的推进序列与现有 `reliability_quarantine_max_chain=4` 预算耗尽高度一致，但日志没有直接记录 quarantine set，因此这里只能记为“高度一致的待验证假设”，不能当作已证事实。

## V2 当前处在错误的架构层

当前 Route1 已经先完成：

- current/next 交叉验证；
- promotion vote；
- current/next 可靠性启发式判断；
- quarantine 与有限跳过；
- trend budget 与 relaxation。

V2 的 promotion guard 则位于投票完成之后、commit 之前：

```python
if promote and next_est is not None:
    promote = self._v11_consumer_allows("anchor_promotion", next_idx)
```

这意味着：

1. Route1 可以反复积累足够的 promotion yes vote；
2. V2 在最后一刻反复拒绝 commit；
3. 但拒绝不会作为可信证据回写 anchor 状态机；
4. next anchor 不会因此快速隔离并换到下一个候选；
5. 相同错误状态持续产生 route-hint 空窗；
6. 连续 30 次 veto 后还存在 fail-open。

当前运行中出现过五次/五组 promotion veto fail-open 事件，涉及 ep87、489、491、669、671。部分 episode 在重试后通过，但它证明“末端 guard + 原有投票状态”存在结构冲突。

另一个冲突发生在 stop gate。V2 用同一个“不信任 anchor”的判断取消 `vlm_stop_veto`。在本次八次取消中：

- 目标半径内并最终成功：ep88、310、658、687；
- 目标半径外并最终失败：ep93、205、366、680。

即该 consumer class 上是 4/4，无法区分“应该取消的误 veto”和“必须保留的真 veto”。不可信 anchor 可以证明“不能据此强制停止”，却不能证明“应该允许停止”。

## 方案 1：把 V2 嵌入现有双锚点状态机

这是优先实施方案。保留 Route1 已验证的双锚点、单调推进和恢复框架，但把 V2 从末端否决器改为状态机中的证据质量模块。

### 设计原则

1. **V2 判断必须发生在 promotion vote 入账之前。**
   不可信的 next evidence 不得先污染 vote history，再在 commit 时被否决。

2. **current 和 next 分开建模。**
   “current 不可信”与“next 不可信”代表不同状态，不能压成一个全局 bool。

3. **不可信证据不应拥有对称权力。**
   它可以阻止“由该证据触发的动作”，但不能自动撤销独立安全机制。

4. **暂时隔离而不是永久黑名单。**
   使用 hysteresis、TTL、连续证据和 re-entry，避免一次误判造成不可逆跳过。

5. **V2 必须评价与 consumer 同一语义层的对象。**
   raw candidate 的可靠性不能直接等价为 post-filter route-memory state 的可靠性。

6. **没有可信 anchor 时进入有界恢复，而不是无限 hint blackout。**
   可执行 active scan、短步继续、重定位或候选扩展，但不得输出伪精确 hint。

### current/next 状态表

| current | next | 处理 |
|---|---|---|
| trusted | trusted | 沿用 Route1 正常 vote/promotion |
| trusted | untrusted | next 的正票不入账；累积风险；达到阈值后临时 quarantine 并尝试 next+1 |
| untrusted | trusted | current 的 mismatch 不得否决 next；允许 next 以独立可信证据晋升 |
| untrusted | untrusted | 不晋升、不输出精确到达 hint；进入有界搜索/active scan，扩大候选 |

### Stop 语义

- 不可信 anchor 可以阻止基于该 anchor 的 `forced_stop`；
- 不能仅因 anchor 不可信就取消 `vlm_stop_veto`；
- 取消 veto 必须有独立的正向 near-home 证据，例如可信的 home probability、稳定视觉到达证据或与 anchor 无关的距离证据；
- 在独立证据尚未实现前，保守策略是保留原 veto。

### 分阶段实施

#### Stage 1：接入 promotion 状态，不改变线上行为

- 暴露 per-anchor V2 assessment，而不是只返回 consumer allow/deny；
- 在 `_record_promotion_vote` 之前计算 current/next trust；
- 记录“基线 vote、调整后 vote、current/next trust、reason、候选 anchor”；
- 在 integrated shadow mode 下运行离线 replay；
- 保留现有线上路径，先证明不会破坏已成功 episode。

#### Stage 2：让 V2 管理 evidence admission

- next 不可信时，不记 promotion yes vote；
- current 不可信且 next 可信时，解除 current 对 next 的错误否决；
- integrated mode 下移除末端 `anchor_promotion` 二次 guard，避免同一证据被过滤两次；
- 引入独立的 V2 quarantine evidence 计数，但仍保留 Route1 的最大跳过边界。

#### Stage 3：有界 quarantine、next+1 与恢复

- 使用连续多帧证据触发临时 quarantine；
- 对 quarantine 设置 TTL/re-entry；
- 两个 anchor 都不可信时触发 active scan/候选扩展；
- 记录 quarantine set、chain budget、选择原因，消除当前观测盲区。

#### Stage 4：修正 route-hint 与 stop consumer

- route hint 的 guard 改为评价 post-filter state 的 confidence、age、source；
- 不再用 latest raw candidate 直接封禁已经稳定的 route-memory hint；
- 删除“V2 不信任 anchor即可取消 stop veto”的路径；
- 只有独立的 near-home positive evidence 才能放行被 Route1 veto 的 stop。

### 方案 1 的验收指标

离线 replay 首先关注：

- promotion vote 被错误污染的次数；
- 末端 promotion veto 次数是否归零；
- false-rejected usable hint，特别是 ep5 的 29 次，能否显著下降；
- ep491 是否能更早离开长期错误的 next5；
- hint starvation 的最长连续步数；
- 九个 premature-stop episode 中，stop veto 是否保持；
- 已成功 episode 是否发生 stop 或 anchor 推进回归；
- fail-open 是否不再被触发。

通过 replay 后才允许 isolated canary；不得直接替换仍在运行的 50ep 或 Route1 主代码。

## 方案 2：围绕 V2 重建简化的双锚点架构

这个方案保留“双锚点”和路线单调性，但移除 Route1 之上的大部分启发式交叉验证与票制，让 V2 成为 belief update 的核心。

### 建议结构

1. 同时给 current、next、必要时 next+1 或多个 basin 打分；
2. 用单调状态模型维护当前位置的 posterior：
   - stay；
   - advance；
   - bounded skip；
3. V2 的概率输出作为 emission，而不是一次性 bool；
4. 从稳定 posterior/MAP state 生成 hint；
5. posterior 熵高时执行 active sensing/recovery，而不是输出精确到达提示；
6. 独立的 `P(home)` 控制 stop，不复用 anchor trust。

### 优点

- 删除多层重复过滤；
- 状态与置信度语义统一；
- current/next 冲突可通过 posterior 解释；
- 更容易对 hint starvation、跳过和 stop 做形式化约束。

### 关键风险

现有调查已经表明：

- 当前 scalar reliability model 的 AUC ceiling 约为 0.84；
- 在部分 confidently-wrong 样本中，正确 transform 根本不在 top-4 candidate 内；
- V1.1/V2 是在 Route1 当前数据分布下训练和校准的。

因此，直接删除 Route1 过滤会改变输入分布；而当正确候选未被生成时，V2 再准确也无法恢复。方案 2 需要同时研究：

- 更宽的 candidate generation；
- 多视角/时间上下文；
- 视觉语义辅助；
- 新分布上的重新训练与校准；
- 独立 stop/home 模型。

结论：方案 2 值得作为并行离线研究方向，但不适合现在直接替换线上 Route1。

## 执行决定

先实施方案 1。

第一步只在新的隔离候选目录中完成 **Stage 1：per-anchor assessment 接口、promotion vote 前的 integrated shadow decision 和完整日志**。不修改正在运行的 Active50 目录，不修改 Route1 主代码，不改变当前 stop 行为。

完成单元测试和目标 episode replay 后，再依据证据决定是否进入 Stage 2。

## Stage 1 实施状态（2026-07-26）

已在新的隔离候选目录中开始实施：

`/home/teambruce/navila-reliability-v1_1-v2-integrated-20260726`

基线来自本次 Active50 的实际候选代码；没有修改仍在运行的 Active50 目录，也没有修改 Route1 主代码。

当前完成内容：

- V2 增加只读的 per-anchor assessment 接口；
- 增加 `IntegratedPromotionDecision`，分别记录 current/next 的 assessment availability 与 `jointly_trusted`；
- 在 closure veto 之后、`_record_promotion_vote` 之前增加 integrated evidence hook；
- 同时记录 `pre_closure_vote`、Route1 `baseline_vote` 和 V2 `counterfactual_vote`；
- next 不可信时，counterfactual 不让正票进入 history；
- current 不可信、next 可信时，counterfactual 可忽略 current 引发的 closure veto，但仍保留 next 自身的 gate；
- 增加明确的 CLI 模式 `--reliability_v11_integrated_promotion_mode=shadow`；
- Stage 1 只允许 `off`/`shadow`，没有 active 选项；
- 即使旧 consumer guard 使用 active artifact，integrated Stage 1 的 `executed_vote` 也始终等于 Route1 baseline；
- 事件写入已有的 `reliability_v11_consumer_v2.jsonl`，类型为 `v11_integrated_promotion_shadow_decision`。

新候选关键 hash：

- `reliability/v11_consumer_policy_v2.py`：`f0f28207c1e68d470147ed20460b48a0e8c70bbd60aa5792f8eaaeb2b7d6ed3d`
- `policy_v2_live_candidate/scripts/route_memory_agent.py`：`c54ff7875caaad41a9d130ec1221278ee710ab3ffe775fff7a50c669d0769ee5`
- `policy_v2_live_candidate/scripts/round_trip_eval.py`：`fc2ae47fe692801fe4953a4ee4038788c211567daa8bea0a0934957a106c76de`

验证结果：

- 三个修改后的 runtime 文件均通过 `py_compile`；
- 新增/相关测试：16/16 通过；
- 全候选测试：40 passed，3 failed；
- 未修改 Active50 基线在同一 Python 3.10 环境：36 passed，3 failed；
- 两边相同的 3 个失败均来自该环境缺少 `scikit-learn`，不是本次改动造成。

历史 Active50 日志能提供每次 current/next 的 V2 assessment，也记录了最终发生的 promotion guard，但没有记录每次 `_record_promotion_vote` 前的 `pre_closure_vote` 与 `baseline_vote`。因此它不足以完整重建“current 不可信时释放 closure veto”的 counterfactual vote history。Stage 1 新日志正是为补齐这个观测缺口；在获得带新事件的 shadow 数据前，不宣称已经完成 episode-level replay。

## 与同日 camera-yaw 调查的关系

同日新增的 `2026-07-26-camera-yaw-fix-and-residual-confidence-gate` 已验证 `camera_rotation_to_body_yaw()` 存在轴选择错误，并找到视觉 RANSAC residual gate；但该调查明确记录修复尚未进入 `relocalization.py`。

这不推翻本文件的架构结论：camera-yaw 修复改善的是一个视觉交叉检查信号，方案 1 Stage 1 修正的是 V2 与 Route1 promotion state machine 的接入层，两者是不同问题。当前隔离候选不擅自合并 camera-yaw 改动，避免在同一 canary 中同时改变信号生成和状态消费。后续可把修正后的视觉 yaw/residual 作为独立证据源评估，但必须单独验证分布变化和 near-zero-parallax 失败模式。
