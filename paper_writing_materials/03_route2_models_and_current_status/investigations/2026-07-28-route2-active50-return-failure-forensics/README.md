截至 2026-07-28 10:19 BST，ep491 新增为 return failure，ep500 正在运行。当前严格有效 completion 为 25 个，其中 outbound 成功 23 个、round-trip 成功 8 个、return 失败 15 个，转换率暂为 8/23 = 34.8%。

下面分析基于 GitHub 最新 `main`：`76544b2d9f3d4e7e047c00c22d8863aab1b16427`，并用本轮 trajectory 真值重建了每次 current/next anchor 的实际正确性。分析脚本在 [route2_active50_failure_forensics.py](/home/teambruce/route2_active50_failure_forensics.py)。

# 一、15 个失败的主因分类

这是按“首要失败链路”做的互斥分类；很多 episode 仍有次要交叉原因。

| 主分类 | Episodes | 数量 |
|---|---|---:|
| A. Stop arbitration 导致提前终止 | 19、95、196、205、264、310 | 6 |
| B. 已经回家但 stop 被持续否决 | 89、490 | 2 |
| C. Anchor 状态恢复失败，长期 hint starvation | 268、366、367、491 | 4 |
| D. 物理卡滞/recovery 为主，状态失能放大问题 | 5、276、344 | 3 |

此外，`deferred≈pass` 横跨 A 类中的 ep19、95、196、264、310，以及 D 类的 ep276。

---

# 二、A 类：Stop arbitration 导致提前终止

## ep19：状态先失效，hint 消失，最后一次低可信 STOP 穿透

完整链路：

1. 回程开始时机器人距起点约 4.01m，pair=8/7，和真实 pair 完全一致。
2. 初期 current A8 坏、next A7 好，系统本来仍有可用 next。
3. 到 attempt 24，两侧都进入 untrusted，selector 正确提出 `request_active_scan`。
4. Active v0 因 scan 没有 executor，立即 `disable_on_unimplemented_active_scan`；后面 59 次只是 `hold_disabled`。
5. 8 次 route hint 中 7 次被挡住，机器人由 4.01m 逐渐走远到 5.40m。
6. VLM 第一次要求 STOP 时，gate 以 10.83m authority 正确 veto。
7. 10 步后 VLM 再次 STOP，confidence 降到 0.2，gate 返回 `deferred`。
8. caller 把 `deferred` 当成可继续执行 STOP，episode 在 5.40m 结束。

没发挥作用的机制：

- Active scan 有正确触发，但没有执行能力。
- Route2 已正确判断 current/next 都坏，却没有恢复身份。
- `deferred` 没有进入安全确认状态，而是直接把最终决定交给 VLM。

## ep95：current 正确，坏 next 被连续跳到 A0，stop gate 看错了 anchor 角色

链路：

1. 从 A17/A16 开始，前半程绝大部分 pair 推进正常。
2. 到 current=A5 时，A5 仍然是正确且模型可信的 current。
3. next 读数连续坏，legacy Route1 依次把 next 从 A4 跳到 A3、A2、A1、A0。
4. 最终 progress 使用的是 A0 的 hop-5 geometry reconstruction。
5. Route2 正确拒绝这种多跳 hint，但没有新的导航信息补上。
6. VLM 在 4.20m 要求 STOP。
7. stop gate 看到的 target 是 A0，`anchor_route_remaining=0`；它没有看到仍然正确的 current A5 自身约 5.03m 的 route distance。
8. ICP confidence 0.476，gate 返回 `deferred`，STOP 穿透。

这里用户提出的思路部分成立：**A5 current 确实足以说明“还不能停”**。但现有 gate 读到的是 reported target A0，不是 current A5。

## ep196：pair 在 A9/A8 冻结，模型知道两者都坏，但没有身份恢复

链路：

1. A13/A12 → A12/A11 → A11/A10 的早期推进基本正常。
2. 到 A9/A8 后 identity 停住；机器人继续移动，最终真实 pair 已约为 A4/A3。
3. terminal 时：

   - current A9：`p_pose_bad=0.968`，真值也是 bad；
   - next A8：`p_pose_bad=0.962`，真值也是 bad。

4. Route2 正确识别两边都不可信，但 scan 在 attempt 29 就已导致 controller 被禁用。
5. 期间还有 5 个 one-hop derived hint 的 bearing 实际错误超过 30°，说明 one-hop recovery 也不是绝对安全。
6. 机器人最接近 4.09m，随后到 4.52m。
7. 第一次 STOP 被 veto，第二次 confidence 变成 0.2 后 `deferred` 穿透。

根因不是单独一个坏 STOP，而是：

`identity freeze → bad candidates detected but unrecoverable → hint/state degraded → repeated STOP → deferred pass-through`

## ep205：模型明确知道 A0 错，但 accepted STOP 路径完全绕过 Route2

链路：

1. 早期 pair 基本正确，但坏 next 导致多次跳过：

   `A10/A9 → A10/A8 → ... → A10/A5`

2. 后续恢复到较低 anchor，机器人进入过 3m 半径，最小距离 2.746m。
3. 系统没有及时停止，机器人随后离开成功半径。
4. terminal pair 为 current=A2、next=A0；真实应该约为 A2/A1。
5. 最终 A0 raw ICP 报：

   - 估计距 A0：0.464m
   - scalar confidence：0.654
   - 真值距 A0：3.873m

6. Route2 模型其实正确判断：

   - A0 `p_pose_bad=0.967`
   - A2 `p_pose_bad=0.959`
   - 两者均 `jointly_trusted=false`

7. 但 stop gate 先根据 scalar confidence 和 0.464m 返回 `accepted`。
8. 当前代码只在 `forced_stop` 和 `vlm_stop_veto` 上调用 V2 consumer；`accepted` 不经过 Route2。
9. 所以模型已经给出正确报警，却没有权限拦住错误接受。

这是最明确的控制接线漏洞之一。

## ep264：大部分路线正常，末段 current 正确、next 被跳到 A1

链路：

1. 从 A15/A14 一路推进，next exact rate 56.7%，整体是失败集中最好的一批。
2. 到终段 current=A4，模型和真值都确认 A4 ICP 正确。
3. A3 之后的 next 持续不可信，被依次跳到 A2、A1。
4. 最终是 current=A4、next=A1，而真实 pair=A4/A3。
5. A1 hop-3 derived hint 被 Route2 正确拒绝。
6. 第一次 STOP 在 4.78m 被 veto；第二次在 3.55m 仍被 veto；第三次 confidence 降为0.2，变成 `deferred`。
7. 最终停在 3.542m。

和 ep95 一样，**current anchor 明显比 reported next 更有结构性价值**。现有 gate 却只拿到 A1。

## ep310：机器人已经回家，但 identity 停在 A9/A8；离开半径后才发生 STOP

链路：

1. 起始 A12/A11 正确。
2. 到 step 2049 后 pair 长期停在 A9/A8。
3. Route2 后续正确判断 A9/A8 都坏，但 scan/controller 已关闭。
4. 36 次 route hint 中 29 次被挡住。
5. 机器人主要依靠 VLM 视觉继续走，实际进入 3m 半径并持续 838 个 trajectory 记录，最近到 0.465m。
6. 这段期间没有形成有效 terminal latch。
7. 机器人又漂出成功半径；在 3.045m 第一次 STOP 被 veto，3.050m 第二次因低可信变为 `deferred`。
8. episode 以仅超出阈值 5cm 结束。

这里最终 `deferred` 只是最后一击。更早的根因是“进入成功区后没有进入不可逆的 terminal-confirmation 状态”。

---

# 三、B 类：已经回家，但 stop 被持续否决

## ep89：60 次正确 STOP 被 veto，随后 recovery 把“停住”误判成“卡住”

链路：

1. 回程开始 pair=A5/A4，真实 pair 也为 A5/A4。
2. 机器人很快进入 3m，并连续 4833 个记录点留在半径内，最终 1.322m。
3. Anchor state 没有跟上物理进度，长期停在 A5/A4，后来只把 next 跳到 A3/A2；真实 pair 已是 A1/A0。
4. RouteMemory 仍报约 5.13m。
5. VLM 连续请求 STOP，gate 总共 veto 60 次。
6. Route2 模型已判断 A5/A4 不可信，但 `vlm_stop_veto` 策略规定保留独立 Route1 veto，因此无法取消。
7. 机器人因为持续想停、位置变化很小，又被 stuck detector 判成 wedge。
8. recovery 先后触发 3 次，反而与正确的停止意图对抗，最终耗尽 return budget。

这是一个完整的级联失败：

`anchor stale → false far distance → correct VLM STOP 被 veto → 静止被误判为 wedge → recovery 对抗终止 → budget exhausted`

## ep490：过期 3552 steps 的 hop-4 证据持续 veto 148 次 STOP

链路：

1. 早期从 A11/A10 正常推进到 current=A4。
2. A3 不可信后，next 被连续跳到 A2、A1、A0。
3. 最后一次 Route2 assessment 约在 step 3544；当时 A4 仍是正确 current。
4. 此后没有新的可靠更新，却一直复用 A4→A0 的 hop-4 reconstruction。
5. 当机器人实际回到起点后：

   - 最小真实距离：0.048m
   - 最终真实距离：0.231m
   - RouteMemory authority：3.833m
   - evidence age：约 3552 steps

6. VLM 共请求 STOP 148 次，全部被 veto。
7. 当前 consumer 对 derived evidence 的 hint 有 hop/freshness 限制，但对 `vlm_stop_veto` 明确保留，因此这个过期 hop-4 距离可以无限否决正确 STOP。
8. 最终耗尽预算。

这是“旧证据拥有无限负向停止权限”的问题。

---

# 四、C 类：Anchor 状态恢复失败，长期 hint starvation

这四集共同的链路是：

`初始 pair 正常 → ICP 质量恶化 → Route2 正确检测坏 candidate → request_active_scan → Active v0 自我禁用 → legacy Route1 继续冻结/跳 anchor → hint 长期消失 → VLM 无路线约束地走远`

## ep268

- 初始 A15/A14 正确。
- attempt 76 请求 scan，controller 随即关闭。
- 后续 next 从 A13 连续跳到 A9。
- 84 次 hint 中 82 次被挡。
- 其中有 48 次被挡 hint 的 bearing 真值其实仍在 30° 内，说明 raw candidate 判定与最终 stateful hint 存在时间/语义错位。
- recovery 触发 4 次。
- 最终 9.28m，最近也只有 8.50m。

## ep366

- 初始 A14/A13 正确。
- attempt 26 即进入 scan dead-end。
- pair 最终变成 A14/A9，真实约 A12/A11。
- 70 次 hint 中 68 次被挡。
- recovery 2 次后仍从 5.25m 走远到 7.61m。

## ep367

- 初始 A12/A11 正确。
- next 连续被跳过到 A6。
- 69 次 hint 中 62 次被挡。
- 最终 A11/A6，真实约 A12/A11，next 超前约 5 个 anchor。
- recovery 3 次，最终 7.52m。

## ep491

- 新完成的失败。
- 回程开始距起点约 3.51m，A11/A10 完全正确。
- A10 后续持续变坏：真值 bad 914/1001 次，模型将其判 untrusted 963/1001 次——模型信号是有效的。
- attempt 104 请求 scan，之后 897 次 `hold_active_scan_request`，controller 始终 disabled。
- pair A11/A10 整整保持 1001 attempts，最终真实 pair 已约 A8/A7。
- 69 次 hint 中 64 次被挡。
- forward 低速比例只有 3.7%，所以它不是物理楔死；机器人确实在移动，只是沿错误方向从 3.51m 走到 6.56m。

---

# 五、D 类：物理卡滞/recovery 为主

## ep5

1. 初始 A12/A11 正确。
2. attempt 104 两侧不可信并请求 scan，controller 关闭。
3. forward 段约 80% 近乎无位移，出现真实接触/楔死。
4. 在机器人几乎不移动时，Route1 仍把 next 从 A8 连续跳到 A4，identity 与物理位置逐渐分离。
5. 71 次 hint 中 62 次被挡。
6. recovery 触发 3 次，每次短暂改变动作但没有脱困。
7. 最终 9.69m。

Route2 不能单独解决物理接触，但状态层不应在机器人不动时继续跨 anchor 跳跃。

## ep276

1. 初始 A12/A11、A10/A9 基本正确。
2. 机器人最近只到 7.93m，约一半 forward 段低速无效。
3. recovery 两次耗尽。
4. 晚期 current/next 失去 joint trust，scan 仍不可执行。
5. VLM 在 9.42m 请求 STOP，gate 因低可靠性返回 `deferred`，直接结束。

这是“物理卡滞为主、terminal pass-through 收尾”的混合失败。

## ep344

1. pair=A13/A12 全程 1001 attempts 不变。
2. A12 的真值 1001/1001 都是 bad，模型也 1001/1001 判 next untrusted。
3. attempt 136 请求 scan，随后 controller disabled。
4. 71 次 hint 中 55 次被挡。
5. forward 低速比例约 46%，recovery 3 次。
6. 最终 7.98m。

这里模型准确发现了问题，但既没有 scan，也没有身份替代路径。

---

# 六、关于 next anchor 是否“基本正确”

结论是：**开始时基本正确，但到了失败关键阶段并不正确，因此不能无条件用 next anchor 编号否决 STOP。**

## 历史调查结果

你提到的记录位于 GitHub：

`investigations/2026-07-19-closure-check-and-stopgate-fixes/FINDINGS.md`

当时 8 个 outbound-success episode 中：

- A2 在 8/8 集都位于真实 3m 半径内；
- A3 在 7/8 集位于 3m 内；
- 但成功集的 anchor pair pooled 只有 40.6% exact，约 45% 差一个 anchor。

## 本轮结果

本轮 23 个 outbound-success episode 的所有可对齐 attempts：

- next exact：20.9%
- 差一个：25.1%
- 差两个及以上：54.0%

只看当前 15 个失败：

- next exact：16.9%
- 差一个：21.8%
- 差两个及以上：61.3%

不过，15/15 个失败 episode 的初始 pair 几乎都是正确的。错误是在以下链路中逐渐形成的：

- pair 长时间不 promotion，机器人已通过该位置；
- 坏 next 被连续 quarantine/skip；
- scan request 无法执行；
- current identity 在机器人继续移动后变 stale。

当前 15 集的真实 anchor 位置也验证：

- A0、A1、A2、A3 在全部 15 集都位于真实 3m 半径内；
- ep205 的 A4 也在 3m 内。

因此“小编号通常近家”成立，但“运行时 next 始终正确”不成立。

---

# 七、deferred 现在到底有没有使用 anchor

答案是：**代码名义上有使用，但实际不是你说的那个 current anchor，而且部分路径完全绕过 anchor。**

相关代码：

- [stop_gate.py](/home/teambruce/navila-reliability-v1_1-v2-recovery-20260727/policy_v2_live_candidate/scripts/stop_gate.py)
- [route_memory_agent.py](/home/teambruce/navila-reliability-v1_1-v2-recovery-20260727/policy_v2_live_candidate/scripts/route_memory_agent.py)

实际链路：

1. `stop_gate.check()` 读取 `progress.anchor_route_remaining_m`。
2. 注释称它是“currently tracked current anchor”。
3. 但 `_anchor_progress()` 在 `sequential_pair_report_next_anchor=True` 时优先使用 `_latest_next_candidate_relocalization`。
4. 所以传入 gate 的其实通常是 reported next/target anchor，不是 confirmed current。
5. 更关键的是，如果 `distance_authority_low_reliability=True`，代码会在 anchor-corroboration 之前直接：

   `return GateDecision("deferred", ...)`

具体后果：

| EP | terminal current/next | 真实 pair | current route | next/target route | 结果 |
|---:|---|---|---:|---:|---|
| 19 | 8/7 | 6/5 | 7.25m | 7.05m | target 明显远，但 low-reliability 提前 deferred |
| 95 | 5/0 | 5/4 | 5.03m | 0m | 正确 current 说远，target A0 说近 |
| 196 | 9/8 | 4/3 | 9.07m | 8.06m | 明显远，但提前 deferred |
| 264 | 4/1 | 4/3 | 4.02m | 1.00m | 正确 current 说远，target A1 说近 |
| 276 | 10/9 | 12/11 | 10.08m | 9.07m | 明显远，但提前 deferred |
| 310 | 9/8 | 已回到起点附近 | 9.07m | 8.06m | identity 严重 stale |

所以你提出的 current-anchor veto 可以直接补住 ep95、ep264；但如果无条件使用，会在 ep89、ep490、甚至成功的 ep88 中产生大量错误 veto，因为 current 也可能长期 stale。

在本轮全部 VLM STOP 查询中：

- 如果无条件用 `current_route_remaining > 3m` veto，会错误 veto 217 次真实已在 3m 内的 STOP；
- 用 reported next/target 也会错误 veto 65–66 次。

这些次数高度集中在 ep89、ep490 等重复 STOP episode，但足以证明 anchor 编号不能单独成为永久否决权。

---

# 八、修改方案

## 方案一：把 `deferred` 改成真正的“不确定状态”，而不是 pass-through

建议新增 `uncertain_hold`，明确区分：

- `accepted`：有正向到达证据，执行 STOP；
- `vetoed`：有可信“仍然远”的证据，继续导航；
- `uncertain_hold`：既不能接受，也不能确定正确行进方向；
- `forced`：连续正向证据确认到家。

`uncertain_hold` 应：

1. 取消本次 terminal；
2. 不使用不可信 bearing 注入 forward/turn；
3. 暂时零速度停稳；
4. 重新采样 ICP/RGB；
5. 进入有界 terminal verification；
6. 超时后 safe hold，而不是把决定交回单次 VLM。

这可以阻止 ep19、95、196、264、276、310 的 premature stop，同时避免简单“永远 veto”重演 ep89/490。

需要特别验证 ep420、ep489：它们是在真实半径内通过 `deferred` 成功的。因此不能只是把 deferred 永久封死，必须有快速正向确认路径。

## 方案二：Stop gate 同时获得 current 和 target，禁止角色混用

给 `RelativeStartProgress` 增加：

- `confirmed_current_anchor_index`
- `confirmed_current_route_remaining_m`
- `reported_target_anchor_index`
- `reported_target_route_remaining_m`
- `target_role`
- `identity_age_attempts`
- `last_trusted_current_step`
- `evidence_age_updates`
- `pair_generation`

负向 anchor veto 只能把 current anchor 当作“结构性先验”，并满足：

- current identity 最近有可信确认；
- current 没有超过最大 dwell/age；
- pair 没有在机器人持续移动时长期冻结；
- 没有连续、强烈的视觉 STOP 请求；
- evidence 未过期。

否则进入 `uncertain_hold`，不能接受，也不能持续导航 veto。

## 方案三：Route2 必须能拦截 `accepted` VLM stop

新增 consumer operation，例如：

`vlm_stop_accept`

规则：

- target distance/pose 必须被 Route2 判可信；或者
- 有独立 RGB home-place confirmation；或者
- 有连续多次一致的近场证据。

如果 Route2 将 target 判为 untrusted，则把 `accepted` 降为 `uncertain_hold`。

这会直接救 ep205：模型已经以 `p_pose_bad=0.967` 正确拒绝 A0，只是当前没有接入 acceptance 路径。

## 方案四：停止使用过期/多跳 derived distance 做无限 veto

建议：

- hop>1 的 derived evidence 不得执行 `vlm_stop_veto`；
- `evidence_age_updates > 25` 后不得执行 stop accept、force 或 veto；
- VLM STOP 连续超过 3 次且 route state 没有新 evidence 时，必须转 terminal verification；
- derived bearing 可以在严格条件下用于导航，但 derived distance 不应拥有不可逆 terminal authority。

这直接针对 ep490。

## 方案五：Active scan request 不再导致整个 controller 永久关闭

当前逻辑是：

`request_active_scan → disable_on_unimplemented_active_scan → clear quarantine → hold_disabled`

建议拆成两个状态：

- quarantine controller 继续存活；
- scan executor 单独显示 `unavailable/pending/failed`。

短期即使没有 motor scan executor，也应：

- 保留已确认 quarantine；
- 不继续多跳 skip；
- 保持 current；
- 扩大候选集合做静态重评分；
- 进入 safe hold，而不是退回 legacy Route1。

中期实现真正的 scan executor，再按 07-27 investigation 的多视角计划重新取样。

## 方案六：限制连续 next skip

ep95 的 A5→A0、ep264 的 A4→A1、ep367 的 A11→A6 都说明 quarantine chain 正在把“坏读数”转化成“身份大跳”。

建议：

- 每次只允许 `current-1` 的 exactly-one-hop recovery；
- 没有新物理进度证据时禁止继续跳第二个 anchor；
- 一个 next 坏到预算后，保持 current 并 scan/expand candidates；
- 多跳 geometry 只能作为诊断，不能成为 route hint 或 stop authority。

## 方案七：修复 hint 的语义/时间层错位

当前 Route2 判断最新 raw candidate，却用结果阻断经过 Route1 时序平滑后的 stateful hint。

本轮存在大量“被挡住但 bearing 实际仍正确”的提示，例如：

- ep268：48 次
- ep89：25 次
- ep5：18 次
- ep276：14 次
- ep310：12 次

建议分别评分：

1. raw ICP candidate reliability；
2. stateful integrated hint reliability；
3. derived one-hop hint reliability。

不能用 raw candidate 的一次 bad 判定永久封禁已被历史状态稳定过的 hint。

## 方案八：terminal confirmation 期间禁用 stuck recovery

当机器人连续输出 STOP 或进入 `uncertain_hold` 时：

- stuck detector 不应把零速度理解为 wedge；
- recovery 必须暂停；
- 只有 terminal verification 判定“确实不在家”后才能恢复导航。

这直接防止 ep89 的“正确停止 → false veto → 被判卡住 → recovery 对抗停止”。

## 方案九：物理 recovery 与 anchor state 联动

针对 ep5、276、344：

- forward command 连续无有效位移时更早触发 contact-aware recovery；
- 每次 recovery 后必须清空或降权旧 ICP evidence；
- recovery 后强制重新识别 pair，不能继续沿旧 A13/A12 或跳过链；
- 区分真实物理 wedge 与“仍在移动但方向错”的 ep491，不能用同一 recovery 策略。

# 九、建议的验证顺序

1. 先做离线 counterfactual replay：

   - `deferred → uncertain_hold`
   - `accepted → Route2 accept guard`
   - derived stop evidence freshness
   - explicit current/target separation

2. 第一组 live targeted cohort：

   - premature stop：19、95、196、205、264、310
   - missed stop：89、490
   - state dead-end：268、491
   - physical controls：5、344

3. 接受标准：

   - 半径外 STOP acceptance = 0；
   - 半径内连续 VLM STOP 不得无限 veto；
   - Active controller `controller_effects > 0`；
   - 不再出现 `disable_on_unimplemented_active_scan` 后整集失能；
   - multi-hop/expired evidence 的 terminal authority = 0；
   - terminal confirmation 不触发 stuck recovery。
