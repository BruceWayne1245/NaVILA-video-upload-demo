# 8/4 Findings — 从 pair deadlock 到可提交 recovery

## 1. 为什么旧机制会卡死

旧机制在 V1.1 判定 pose-untrusted、V2 产生 recovery 类动作或 current/next ICP
相互矛盾后，最多只执行 hold 与重复 probe。probe 的结果没有改变 active pair 的
提交路径；没有新证据时又回到同一 pair。因此系统既没有承认失锁，也没有把“谁坏了”
转成受限的拓扑恢复动作。

这不是简单的 V2 “偏好 ahead”。8/3 已确认多数 2--3 ahead 来自旧 controller 将
`hold` 等动作错误解释为 forward progress 的累计漂移；该语义错位已先行修复。
本次针对的是语义修复后仍会发生的 **pair 无法重新定位**。

## 2. probe 的局部判别

对下降序列 `(C, N=C-1)`，probe 同时检查：`C+1, C, N, N-1`。

- `C+1`：current 是否需要向后回退；
- `C`：当前已提交 anchor；
- `N`：希望推进到的 next；
- `N-1`：next 坏时的单 anchor 前向替代。

支持/拒绝不只来自 V1.1 pose head；还要求 ICP 基础质量（inlier、overlap、residual）
和局部可观测性通过。输出为 `current_supported`、`next_supported`、相应 rejected，
或全部无信息。

尚未实现且刻意延后：为了消除短基线歧义而执行受控安全移动、积累约 0.3m 基线后再采样。
本次不把额外运动混入首轮 recovery10；现有 probe 使用正常运行中已有的观测。

## 3. 可提交的恢复动作

| probe 结论 | 已实现动作 | 限制 |
|---|---|---|
| current rejected、next supported | `recovery_promote_next` | 仅 C -> N 一步 |
| current supported、next rejected | `recovery_quarantine_next`，active pair 改为 `(C,N-1)` | N 仅在本轮 quarantine；不得由 V2 `skip_or_rebase` 直接跳过 |
| C/N 都拒绝但一侧邻居有支持 | 在 `{C+1,C}`、`{C,N}`、`{N,N-1}` 之一重建 | 不跨两组、不按模型概率选远 anchor |
| 所有候选无信息 | `NO_LOCK_FALLBACK` | 撤销旧 pair 的导航权和陈旧 next hint；移动约 0.5m 后强制重定位 |

进入 `PAIR_SUSPECT` 的阈值是：同一 pair 连续 3 次 V1.1 pose-untrusted，或连续 2 次
V2 高置信 recovery 信号，或 current/next ICP 互相矛盾且无进展。

## 4. 旧 pair 与 terminal 的边界

EP95、658、680 的旧失败并非“ICP 直接把机器人到 A0 的欧氏距离算错”。terminal 使用的
是“ICP 到当前 target anchor + 该 anchor 到 A0 的历史路线余量”。pair 卡死时，这个量会
保持很大，导致已在 3m 内也无法停。

本次的最小且正确边界是：在 `NO_LOCK_FALLBACK`，让旧 pair 的 relocalization evidence
变 stale，因此 stop gate 不得继续把它作为拒停依据。它**不等于**已经解决 terminal
distance 语义；后者仍需直接 A0 或独立验证的几何证据，并会另立实验。

## 5. 已完成的离线验证

- full-active controller 的直接回归测试通过；
- evaluator/controller/agent/online 均通过 Python 编译；
- `_nearest_neighbor_2d` 对异常、空或非有限输入已转为安全 no-candidate，避免其造成
  evaluator fatal；
- 10EP manifest 数量与 metadata 校验通过；
- recovery10 启动脚本固定了本次 evaluator、agent、controller、online 和 Anchor V2
  model 的 SHA-256，启动前不符即拒绝运行。

没有把上述离线验证表述为 live 成功率验证；新状态机尚需 recovery10 的运行轨迹验证。
