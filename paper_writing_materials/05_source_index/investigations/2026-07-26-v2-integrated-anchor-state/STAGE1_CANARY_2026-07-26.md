# Scheme 1 Stage 1 targeted shadow canary

日期：2026-07-26

目标：验证 V2 assessment 接入 promotion vote 之前的观测点，并在不改变控制的前提下回答：

1. 旧末端 `anchor_promotion` guard 是否确实介入太晚；
2. 哪些 V2 reject 真正会改变 Route1 vote，哪些只是与 Route1 原负票重合；
3. current/next trust 应如何驱动后续 quarantine/state transition；
4. Stage 1 日志本身是否完整、独立且无 controller effect。

## 运行边界

隔离候选：

`/home/teambruce/navila-reliability-v1_1-v2-integrated-20260726`

run tag：

`reliability_v11_v2_integrated_promotion_shadow_canary_20260726`

控制条件：

- Route1 + 原 Active V2 consumer guard 继续执行；
- `--reliability_v11_integrated_promotion_mode=shadow`；
- integrated `executed_vote` 必须始终等于 Route1 `baseline_vote`；
- 不改变 hint、stop、motor、timeout 或 recovery 参数；
- 不合并同日独立 Route1 camera-yaw/LoFTR 改动。

两个 episode 都在关键证据充分后按用户指示手动停止，因此产物明确标记为 `partial.user_stopped`，不能进入 round-trip 成功率分母，也不能被表述为 completed episode。

### 产物

batch log：

`/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/reliability_v11_v2_integrated_promotion_shadow_canary_20260726`

ep5：

`..._ep5.partial.user_stopped.20260726T112350`

ep491：

`..._ep491.partial.user_stopped.20260726T113915`

ep491 第一次 VLM bootstrap 因手动停止 ep5 后残留的两个独立 process group 占用约 20 GB GPU 而 OOM。该次没有创建 result directory，不是 episode/model failure。核对命令行后终止 ep5 残留进程，GPU 回到 53 MB，再进行一次干净启动。

## Shadow 安全性

| Episode | integrated events | `executed_vote != baseline_vote` |
|---:|---:|---:|
| 5 | 813 | 0 |
| 491 | 253 | 0 |

Stage 1 没有改变任何 promotion vote。

## ep5

### 运行概况

- return 起点：step1750，world distance to start 约 10.164 m；
- 手动停止前最后 integrated event：step6099；
- 物理 wedge 后距离长期约 8.85–8.90 m；
- 保留 integrated events：813。

current/next 序列：

| Pair | attempts |
|---|---:|
| 12 / 11 | 358 |
| 11 / 10 | 10 |
| 10 / 9 | 5 |
| 10 / 8 | 5 |
| 10 / 7 | 84 |
| 10 / 6 | 5 |
| 10 / 5 | 346 |

这次运行把旧调查中的两个推断升级为直接证据。

### 证据 1：末端 guard 太晚，并最终自我失效

Route1 对 anchor11 形成 30 次最终 promotion proposal：

- 前 29 次被旧 V2 末端 guard veto；
- 第 30 次触发 `promotion_veto_fallback_fail_open`；
- anchor11 被放行晋升；
- guard 被标记为 episode disabled；
- 随后 anchor10 promotion 以 `episode_disabled_fail_open` 直接放行。

总计：

- legacy promotion proposals：31；
- anchor11：30；
- anchor10：1；
- executed allow：2；
- fail-open decisions：2。

这证明当前结构会经历：

1. Route1 的 vote history 已经形成；
2. V2 只能在 commit 前反复拒绝；
3. 拒绝不修复 current/next 状态；
4. streak 达到 30 后不是换 anchor，而是关闭整个 V2 guard；
5. 剩余路线失去 V2 protection。

### 证据 2：V2 应在 vote-history 层区分两种作用

在 legacy fail-open 前，实际记录到 58 个 counterfactual delta：

- 52 次：next 不可信，Route1 baseline 为正，integrated counterfactual 改为负；
- 6 次：current 不可信、next 可信，Route1 baseline 因 current/next 冲突为负，integrated counterfactual 恢复为正。

这两种 delta 方向相反，说明“V2 reject”不能作为单一计数使用：

- 坏 next：阻止正证据入账；
- 坏 current + 好 next：解除 current 对 next 的错误否决。

### 证据 3：quarantine chain 用满后固定在 next5

fail-open 后 current 到达 anchor10，next 依次：

`9 → 8 → 7 → 6 → 5`

这与最多 quarantine 四个 anchor 的预算完全一致：9、8、7、6 被跳过后，next5 长期持续 346 次 attempt。

因此后续不能只增加“V2 不可信即 quarantine”：

- 必须记录每次 quarantine 的证据来源；
- 必须有 TTL/re-entry；
- 必须定义 chain budget 用满后的 active scan/候选扩展；
- 不能让最后一个 next 永久吸收所有错误读数。

### 证据 4：物理 wedge 是独立失败轴

即使 anchor state 可更早修复，本次 ep5 的机器人在约 8.86 m 处几乎没有位移，recovery 多次翻转方向仍未脱困。

因此 ep5 不能用来宣称“修正 vote 即可让 episode 成功”。方案 1 解决 anchor state；locomotion/recovery 仍需独立指标。

## ep491

### 运行概况

- return 起点：step2350；
- world distance to start：约 2.420 m；
- step2850/3350：约 2.428/2.427 m；
- anchor authority distance：持续约 12.4–13.1 m；
- wedge recovery：step2901 开始；
- 手动停止前最后 integrated event：step3609；
- integrated events：253；
- pair 始终为 current13/next12。

本次随机轨迹的 outbound 终点和 anchor 数量与旧 ep491 不同，因此不能要求复现完全相同的 anchor 编号；这里只比较机制。

### 关键结果：大量 reject 不等于 V2 造成冻结

253 次 integrated decision 中：

- `pre_closure_vote=True`：0；
- `baseline_vote=True`：0；
- `counterfactual_vote=True`：0；
- vote delta：0；
- legacy final promotion proposal：0。

trust reason：

| Reason | Count |
|---|---:|
| next 不可信 | 130 |
| trusted next，保留 Route1 vote | 117 |
| current 不可信、next 可信 | 6 |

也就是说，虽然 V2 有 130 次认为 next 不可信，但 Route1 本身在所有 253 次 attempt 中都已经给负票。这里的 pin 不是“V2 在末端拦截了本可发生的晋升”，而是 Route1 vote/closure/quality 体系从未形成正 promotion evidence。

这直接否定一种过度简化解释：

> 高 route-hint/V2 reject rate 本身不能证明 V2 导致失败。

必须区分：

- V2 与 Route1 同时拒绝；
- V2 独有的 vote delta；
- current 不可信导致的错误 closure veto；
- 两边都无可信证据时缺少状态迁移。

### near-home 与 authority 的矛盾

world position 已在 3 m 成功半径内，但 anchor authority 持续远报 12 m 以上，机器人仍继续运动并进入 wedge recovery。

本次日志中的 stop-gate decision 是 `pass`，不是对 VLM stop proposal 的 veto；因此不能从该样本断言“错误 authority 单独阻止了 stop”。可以确定的是：

- route state 的距离语义严重错误；
- VLM 没有在这段提出可终止的 stop；
- 系统没有独立、可信的 near-home positive evidence；
- anchor trust 不能同时承担 route progress 与 home detection。

这继续支持独立 `P(home)`/near-home evidence，而不是用 anchor trust 对 stop 做对称 allow/deny。

## Canary 发现的 Stage 1 观测 bug

首次实现复用了 legacy guard 的 `_disabled` 状态。ep5 在第30次 promotion veto 后 legacy guard fail-open，导致后续 455 条 integrated shadow decision 退化为照抄 baseline。

这没有影响控制，但会让 integrated observer 在最需要观察的 fail-open 后失明。

已修复：

- 仅由 `promotion_veto_streak_reached` 引发的 legacy disable 不再关闭 integrated shadow；
- 模型输出无效等真实 runtime failure 仍保守 preserve baseline；
- event 增加 legacy disable reason 与“忽略 legacy promotion fail-open”标记；
- 相关测试 18/18 通过；
- 全候选测试 42 passed、3 个与基线相同的缺少 `scikit-learn` 环境失败。

用 event 中已记录的 trust/pre-closure/baseline 字段离线重算 ep5：

- 全部 813 events；
- counterfactual delta：63；
- 正→负：57；
- 负→正：6；
- delta pair：12/11 有58次，11/10 有5次。

该离线重算只修复 observer 的计数，不声称重建改票后的真实轨迹；第一次状态改变后，后续输入分布会变化。

## 对方案 1 的更新

Stage 1 接入点验证通过，但不能直接进入简单 active vote filtering。

Stage 2/3 最小闭环必须同时包含：

1. 在 vote 入账前区分 current/next trust；
2. next 不可信的正票不入账；
3. current 不可信、next 可信时解除 current closure veto；
4. per-anchor 风险 streak，而不是 episode-global fail-open；
5. temporary quarantine + TTL + re-entry；
6. chain budget 用满时的 active scan/候选扩展；
7. 两边都不可信时的有界恢复；
8. 独立 near-home evidence；
9. 完整记录 quarantine set、预算与状态迁移。

下一步应先实现可重放的 per-anchor state-transition policy，并在 shadow 中输出“如果 active，下一状态是什么”；不能仅把本次 63 个 vote delta 机械应用到旧轨迹，也不能直接开启 active。
