# Route 2 — Anchor V2 显式 recovery 状态机与 recovery10 排队记录

日期：2026-08-04  
状态：运行时实现和离线验证已完成；首批 10EP active regression 已排队，尚未产生新 live 结果。

## 今天的结论

`anchor_v2_full_active_semanticfix30_rerun1_20260804` 的主要剩余问题不是 Anchor V2
再次把绝对 anchor 选错，而是当 current/next pair 失去可信 ICP 后，系统会在同一对
anchor 上反复 hold/probe，继续把这对已经失效的 pair 当作导航和 terminal 证据。

为此，Route 2 已从隐式的

```text
normal pair -> untrusted -> hold/probe -> original pair
```

改为显式的

```text
NORMAL -> PAIR_SUSPECT -> PROBING -> COMMIT_RECOVERY | NO_LOCK_FALLBACK -> NORMAL
```

这次修改只处理 anchor/relocalization recovery；**terminal 的独立距离语义改造没有在
本次上线**。曾短暂加入的“直接 A0 visual probe 距离作为 `terminal_distance_m`”已撤回：
离线数据出现远距离 false-positive 近零匹配，不能把它当终止证据。

## 语义与失败复盘

上一批有效 return 样本的 canonical 失败中：

- 直接属于旧 pair 卡死后仍被 terminal 采用的：EP95、658、680；
- pair 卡死、无法继续恢复导航的：EP4、367；
- 可能受益但仍需实测的 false local ICP/pair freeze：EP994；以及导航尚未回到成功区的 EP268；
- 独立低层/VLM 导航问题：EP5；
- terminal 本身的问题而不是本次 anchor recovery 的充分验证对象：EP89、276，和过冲 EP310、427、888、961。

因此不能声称本次改动会修复全部 return 失败；它应直接修复前两类，可能改善 EP994/268，
并把失锁 pair 从旧 terminal 证据链中显式移除。

完整逐条分类见 [FINDINGS.md](FINDINGS.md)，实现和队列防护见
[IMPLEMENTATION_AND_QUEUE.md](IMPLEMENTATION_AND_QUEUE.md)。

## 已排队的首批 recovery10

- run tag：`anchor_v2_full_active_recovery10_20260804`
- EP：`4, 95, 268, 367, 89, 658, 994, 680, 5, 961`
- 目的：覆盖 deadlock、stale-pair terminal veto、false ICP pair freeze、低层导航
  control 与 terminal control；不是新的 success-rate cohort。
- 上游：正在运行的 Route1
  `navila-route2-semanticfix30-to-line2-stopgate-redesign-queue-20260804.service`。
- 排队服务：`navila-route2-recovery10-after-line2-20260804.service`。

它只会在上游服务结束、带上游 result suffix/端口的进程被清理、且 GPU 至少空闲
22GiB 后启动；若清理 10 分钟仍不收敛，会 fail-closed，绝不与上游抢 GPU。

## 后续判定

这 10EP 完成后首先审计：

1. `PAIR_SUSPECT/PROBING/COMMIT_RECOVERY/NO_LOCK` 的触发与退出；
2. EP4/367 是否不再在原 pair 无限循环；
3. EP95/658/680 失锁后旧 pair 是否不再否决 stop；
4. 每 EP 的 cleanup fence 是否都在启动下一 EP 前确认 evaluator、VLM 和 GPU 释放；
5. canonical return 与“进入 3m 后安全主动结束”的实际 return 两种口径。

只有这一步稳定后，才单独恢复 terminal 距离证据的设计与测试。
