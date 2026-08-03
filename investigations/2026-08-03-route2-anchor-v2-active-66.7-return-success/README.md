# Route 2 — Anchor V2 full-active：66.7% 实际 return 成功率、问题复盘与修复

日期：2026-08-03
状态：本次 active cohort 已停止；运行时修复已完成，尚未以修复后的代码重跑。

## 本文的结论

本次是 Anchor V2 为唯一 active 变量的 prospective full-active cohort。
它暴露的首要问题不是 Anchor V2 选择了错误的绝对 anchor，而是 controller 把模型的
`hold`（以及一部分非 forward 类）错误地解释为 forward progress，导致 anchor 状态可
在机器人之前累计到 2--3 ahead。这样虽然拓扑上仍可接受，却会把后续 ICP 推入低重叠、
高拒绝率区间，造成 V1.1 路由/终端信息真空。

本次确认的工作顺序：

1. 先修 controller 的 action 语义和 Anchor-0 recovery fatal；不重训 V2，也不把
   可观测性特征立即加入模型。
2. 保持 V1.1 对实际 requested `next` anchor 的实时可信门控。
3. 用修复后的小规模 active/shadow 对照复测 ahead 分布、ICP 可用率、return 结果。
4. 只有在 controller 修复后，明确 `advance_one` 仍系统性造成有害 2--3 ahead 时，才
   考虑把跳后可观测性作为独立条件，而不是贸然加入 V2 模型特征。

## Cohort 与可用样本

- 批次：`anchor_v2_full_active_batch49_20260802`。
- 原计划 49 EP；实际在第 27 个有终态的运行记录后停止，因为 9 个相同的 topology
  fatal 达到既定停机规则。
- 17 个有正常 evaluator 终态：15 个进入 return，2 个 outbound 未成功而未进入 return。
- 9 个 fatal 没有形成可用 return 轨迹；另有 1 个独立 VLM startup failure。

9 个 fatal：`95, 310, 367, 484, 539, 646, 680, 961, 962`。它们不是 ICP 或模型推理
失败，见“修复 2”。

## Return 成功率：两种必须同时保留的口径

`success_requires_stop=True` 的 evaluator 原始口径要求 stop gate 接受的终端 stop：

- canonical return success：**7 / 15 = 46.7%**。

从任务语义看，机器人主动回到成功半径内、再由安全状态机主动结束，即使缺少可信终端
ICP 而标记 `safe_fail`，也应计为实际 return 成功；但必须保留为终端验证问题样本：

- 几何成功但 terminal safe-fail：`87, 88, 1040`。
- 它们的最终真实距起点分别为 `2.89m, 2.58m, 2.42m`，均在 `3.0m` success radius 内。
- **实际 return success（后续汇报主口径）= 10 / 15 = 66.7%**。

后续报告必须并列这两个数：前者诊断终端验证，后者反映是否完成了返回任务。分析
return 失败原因时，三个 near-home safe-fail 仍须保留为失败样本，标签为
`navigation/geometric success + terminal-verification failure`。

## Anchor V2 地面真值审计

用户确认的正确性标准：机器人位于相邻 anchor 之间时，`next` 在其前方 1--3 个
anchor 内均可接受，因为系统需要跳过坏 anchor；明显落后或提前超过 3 个才算错。

以机器人真值投影到 anchor 路线序列：

- 189 次实际 promotion 中，181 次严格满足该窗口。
- 2 次仅落后不足 `0.33` 个 anchor，按“明显落后才算错”计为可接受。
- 5 次明确提前 4 个 anchor；1 次由于路线投影残差 `1.87m` 无法可靠判定。
- 可可靠判定的 188 次中：**183 正确、5 错误，97.3%**。

因此 V2 的绝对 target 选择本身不是当前的主要失败源。

## 关键问题：action/controller 语义错位导致累计 ahead

模型只有一个五分类 softmax：

`advance_one / hold / skip_or_rebase / rollback / rebase`

旧 controller 却把 `advance_one + hold + skip_or_rebase` 的概率质量相加为
`progress_probability`。于是 argmax 为 `hold`，甚至个别 argmax 为 `rollback` 的输出，
仍可被执行为 promotion。

实证：

- 2--3 ahead 的 130 次实际 promotion 中：`hold` 85 次、`rollback` 6 次、
  `skip_or_rebase` 8 次、明确 `advance_one` 仅 31 次。
- 3 ahead 的 33 次中：29 次 `hold`、4 次 `rollback`、0 次 `advance_one`。
- 181/189 个 promotion 是单步拓扑推进；仅 8 个是两步、没有三步直接跳。因此多数
  2--3 ahead 是连续误推进累积的状态漂移，不是模型一次选择远 anchor。
- 在 2 ahead 时，当前 anchor ICP 不可信仅 3/97；在 3 ahead 时为 0/33。这也说明
  后续前推通常不是“必须逃离坏 current anchor”。

## ICP：距离退化与 anchor 固有质量必须分开

对实际执行且被 V1.1 放行的 promotion，requested next anchor 的 ICP 仍较好：

| next 前方距离 | 样本 | distance trusted | bearing trusted | ICP 距离误差中位数 | P90 |
|---|---:|---:|---:|---:|---:|
| 1 anchor | 52 | 98.1% | 98.1% | 0.035m | 0.118m |
| 2 anchors | 97 | 95.9% | 100.0% | 0.052m | 0.308m |
| 3 anchors | 33 | 90.9% | 100.0% | 0.058m | 0.258m |

这不是“任意好 anchor 在远处仍可靠”的证明，而是 V1.1 门控筛留下来的样本。为隔离
anchor 固有质量，比较同一 EP 的同一物理 anchor 在不同相对路线距离下的所有读数：

| 同一 anchor | pose trusted | p_pose_bad | ICP 距离误差 | residual | overlap | inlier |
|---|---:|---:|---:|---:|---:|---:|
| 1 ahead -> 2 ahead | 81.3% -> 44.1% | 0.112 -> 0.534 | 0.098m -> 0.427m | 0.079 -> 0.129m | 0.863 -> 0.696 | 395 -> 314 |
| 1 ahead -> 3 ahead | 80.8% -> 16.9% | 0.119 -> 0.791 | 0.098m -> 0.687m | 0.077 -> 0.155m | 0.864 -> 0.605 | 392 -> 270 |

这证明距离/视角带来的 ICP 退化是真实问题，不只是坏 anchor 本身造成的。因此 1--3
ahead 容忍窗口有效，但只能在 V1.1 对实际 requested target 的实时质量门控下使用。

## Return 失败与 ICP 信息真空

进入 return 后 canonical 失败的 EP：`5, 87, 88, 89, 187, 276, 351, 1040`。

### 直接的 terminal-verification 信息真空

`87, 88, 1040` 都已在 3m success radius 内，却因
`blind_probe_budget_exhausted_without_terminal_evidence` 进入 `safe_fail`。这是主动的
安全终止，不是总步数/时间耗尽：gate 完成最多 8 次 bounded VLM-only probe 后，主动
置零速度并调用环境 stop，同时记录 evaluator failure。

它们应计入 66.7% 实际成功率，同时继续作为 ICP/stopgate 问题样本。

### 很可能由 route-hint 信息稀缺显著贡献的导航失败

| EP | 最终距起点 | route_hint 因 V1.1 bearing 拒绝 |
|---|---:|---:|
| 89 | 6.08m | 31 / 50 |
| 187 | 7.26m | 12 / 15 |
| 276 | 7.96m | 18 / 22 |
| 351 | 8.40m | 14 / 27 |

失败组 route hint 拒绝率为 `128/212 = 60.4%`，成功组为 `64/182 = 35.2%`。这支持
“V1.1 拒绝坏 ICP 后没有替代路由证据，动作层发生信息真空”的诊断；但 EP351 仍不能
排除 VLM/路线行为的独立影响。`hint_action_override` 请求很少，不能把本批问题主要
归因于它未能接管动作。

EP5 最终仍距起点 15.42m，且 route-hint 拒绝仅 7/20；现有证据不足以将它归因于 ICP
信息真空。它的 terminal safe-fail 是正确的保守拒停，而非本可成功的终端失败。

## 已完成的运行时修改

这些修改位于实际 runtime：`/home/teambruce/navila-route2-v11-core-20260801`，尚未重跑
新的 active EP。

### 修复 1：controller action 语义

文件：`anchor_transition_runtime/full_active_controller.py`

- 仅高置信的明确 `advance_one` 可以执行正常 promotion。
- `hold` 只 hold，不再被合并成 forward progress。
- `rollback/rebase/skip_or_rebase` 仅可走 bounded recovery/probe，不能自动 promotion。
- V1.1 对 requested next anchor 的 `pose_trusted` 门控保持不变。

回放本批 EP87 的典型错误输出（`hold=50.0%`、`rollback=37.9%`、
`advance=7.0%`、`skip=4.7%`）：旧 controller 会 promotion；修复后为
`model_abstain`，不 promotion、不 recovery。

### 修复 2：Anchor-0 recovery fatal

文件：`runtime_candidate/scripts/route_memory_agent.py`

旧代理将 recovery support pair 强制为“严格递减”，与 full-active controller 的局部双向
拓扑和 anchor-0 合法同位 pair `(0,0)` 不兼容。连续 12 次无确认 hold 后，controller
会正确地产生 `(0,0)` 加 probe `(1,2)`；旧断言却将其作为 fatal。

修复后：

- 接受与当前局部路线方向一致的 support pair；
- 接受边界合法的同位 `(0,0)` hold/probe；
- 继续拒绝未知 anchor 或真实反向的 recovery pair。

### 验证

- full-active controller 11 个直接回归测试通过；新增了 `hold` 不得 promotion、
  `skip_or_rebase` 只能 recovery、anchor-0 `(0,0)` safe hold/probe 的覆盖。
- evaluator wiring 的 6 个直接测试通过。
- 两个修改文件均通过 Python 语法编译。
- 当前环境未安装 `pytest`，故包含 pytest 依赖的旧 guard 测试没有在本机执行。

## 下一步

先以修复后的 controller 做小规模 active/shadow 对照，重点报告：

1. 0/1/2/3-ahead 分布及连续 promotion 链；
2. requested next ICP 的 V1.1 接受率、distance/bearing trusted 率；
3. canonical return success 与实际 return success（66.7% 新口径）；
4. near-home terminal safe-fail 数量；
5. Anchor-0 recovery 是否能完整结束并释放后续 EP。
