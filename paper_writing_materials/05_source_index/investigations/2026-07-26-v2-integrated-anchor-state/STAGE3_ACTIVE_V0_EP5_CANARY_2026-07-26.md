# Scheme 1 Stage 3：ep5 Active v0 canary

日期：2026-07-26

## 结论

用户明确批准的单 episode ep5 Active v0 canary 已完成。

结果分成两部分：

1. **安全性 gate 通过**
   - active scope、episode scope、hash、arming 与 kill switch 均正确；
   - 四次 candidate quarantine 都与同一步 promotion suppression 原子执行；
   - 达到 chain budget 后自动撤销全部 V2 临时状态；
   - rollback 后 Active v0 永久 disabled，Route1 恢复推进；
   - 没有 motor、stop 或 hint action；
   - 没有单调性/预算违规；
   - 进程与 GPU 已清理。
2. **有效性 gate 未通过**
   - 四个被隔离的 anchor 中，11、10、9 的 world-pose truth 支持隔离；
   - 第一个 anchor12 是 false quarantine；
   - anchor12 的触发窗口内，V2 将 6/7 次读数判为“不联合可信”，但 truth 只有 2/7 次 pose bad；
   - rollback 后 anchor12 很快恢复正确并被 Route1 晋升为 current。

因此不能因为 fail-safe 正常就继续扩展到 ep491/ep658。当前 Active v0 把 `jointly_trusted=false` 同时当作“应该 abstain”和“足以主动 quarantine”的负证据，权力过大。

下一步应先把状态改成三值语义：

- trusted；
- uncertain/abstain；
- strongly untrusted。

只有强负证据才能改变 candidate identity。完成新的 shadow replay/online gate 后，才讨论新的 Active 批准。

## 批准边界

approved artifact：

`configs/v11_integrated_candidate_controller_active_v0_ep5_approved_20260726.json`

SHA256：

`bc609cf6f09578731013cf101a6e079f3ecd2d57a6efb0744403dfe3659237b2`

artifact scope：

```json
{
  "episode_ids": [5],
  "max_completed_episodes": 1,
  "approved_by": "user_in_conversation"
}
```

同时要求：

- CLI `mode=active`；
- CLI `active_armed`；
- 单独的 ep5 kill-switch path；
- `motor_actions_authorized=false`；
- `stop_actions_authorized=false`；
- action scope 只有 temporary candidate quarantine 与对应的 promotion suppression。

运行结束后已置位：

`.../ep5.active_v0.KILL`

再次执行 active preflight 会因 kill switch 已 engaged 而失败，因此该次批准不能被静默复用。

## Runtime hash

| 文件 | SHA256 |
|---|---|
| `reliability/v11_integrated_candidate_controller.py` | `8cec196b8aa39520105ddd0f1a5ba8e0dca32189784b94c073075f7e4c504b1a` |
| approved policy | `bc609cf6f09578731013cf101a6e079f3ecd2d57a6efb0744403dfe3659237b2` |
| `policy_v2_live_candidate/scripts/round_trip_eval.py` | `9dce7ac859025f1896bcda137d454e827c2868f8fc54f978e2d20e94e55bc881` |
| `policy_v2_live_candidate/scripts/route_memory_agent.py` | `585360936279be97f1530562ed0c5d8adfd5f2cb332b9d8885eddff712aa6791` |
| active/shadow runner | `8c6181a8b86a66cd7cc984d1743ece86811457e41d72171d445e93971e7a7898` |

controller runtime 新增 physical episode scope 校验。即使拿到 approved policy，非 ep5 也会在 `start_episode` 阶段被拒绝。

## 测试与 preflight

- controller/state/selector/wiring：36 passed；
- 完整候选：74 passed，1 failed；
- 唯一失败仍是既有缺失 fixture：
  `experiments/2026-07-23-prospective-results/prospective_v1_1.npz`；
- Active preflight 验证：
  - runtime/config hashes；
  - approved episode 只有 ep5；
  - max completed episodes 为1；
  - action scope 精确匹配；
  - motor/stop authority 均为 false；
  - kill switch 启动前未 engaged。

## 运行与归档

run tag：

`reliability_v11_v2_integrated_candidate_controller_active_v0_ep5_canary_20260726`

结果目录：

`..._ep5.partial.user_stopped.20260726T153950Z`

JSONL：

- SHA256：`d738a9b7fcc60a60e279d26a754e5f1a584ef863f3b9fefe9a334c69c7e0b2c3`
- JSON events：217；
- promotion/state/selector/controller：52/52/52/52；
- 四层 attempt/step 集合一致；
- state/selector/controller sequence 均为1–52连续；
- shadow promotion/state/selector controller effect：0/0/0；
- selector Route1 mutation：0；
- selector 单调性违规：0；
- selector budget 违规：0。

运行在验证 active transition 与 rollback 后手动停止，没有 completion artifact，不进入 round-trip 成功率。

## Active transitions

| sequence | step | current / actual next | Active transition | 临时 quarantine |
|---:|---:|---|---|---|
| 26 | 1874 | 13 / 12 | quarantine + suppress promotion | `[12]` |
| 30 | 1894 | 13 / 11 | quarantine + suppress promotion | `[11,12]` |
| 33 | 1909 | 13 / 10 | quarantine + suppress promotion | `[10,11,12]` |
| 36 | 1924 | 13 / 9 | quarantine + suppress promotion | `[9,10,11,12]` |
| 39 | 1939 | 13 / 8 | chain budget exhausted；rollback/disable | `[]` |

controller summary：

| Executed action | Count |
|---|---:|
| `preserve_route1` | 34 |
| `replace_active_quarantines` | 4 |
| `disable_on_unimplemented_active_scan` | 1 |
| `hold_disabled` | 13 |

其他约束：

- controller effects：5（4次 quarantine update + 1次 rollback）；
- promotion suppressions：4；
- motor action requests：0；
- stop action requests：0；
- rollback 后所有13个 disabled decision 的 active quarantine 均为空；
- rollback 后 promotion suppression 始终为 false；
- 最终事件中 Active 仍 disabled，current12/next7 由 Route1 继续控制。

## World-pose truth

四个 quarantine trigger：

| attempt | anchor | bearing error | distance error | Truth |
|---:|---:|---:|---:|---|
| 26 | 12 | 12.54° | 0.051 m | good；false quarantine |
| 30 | 11 | 75.60° | 3.249 m | bad；correct quarantine |
| 33 | 10 | 60.03° | 2.733 m | bad；correct quarantine |
| 36 | 9 | 69.15° | 1.200 m | bad；correct quarantine |

anchor8 在 scan request 时：

- bearing error：80.88°；
- distance error：0.408 m；
- pose bad。

因此，预算耗尽并不是因为11/10/9/8都被错误判断；这些 downstream candidates 确实很差。问题集中在第一个 anchor12：

| attempt | bearing error | truth pose bad | V2 jointly trusted | `p_pose_bad` |
|---:|---:|---:|---|---:|
| 20 | 1.0° | 0 | true | 0.216 |
| 21 | 8.8° | 0 | false | 0.556 |
| 22 | 175.8° | 1 | false | 0.872 |
| 23 | 7.8° | 0 | false | 0.807 |
| 24 | 132.0° | 1 | false | 0.935 |
| 25 | 10.3° | 0 | false | 0.570 |
| 26 | 12.5° | 0 | false | 0.403 |

V2 的 `jointly_trusted` 在这个窗口的用途是“是否允许把读数当强证据”，并不等价于“该 anchor 已被强证据证明错误”。

当前 state machine 将 6/7 个 `jointly_trusted=false` 累积为 untrusted，然后主动改变 identity。这把一个高 precision 的 abstention gate 错当成高 precision 的 negative classifier。

rollback 后的 truth 进一步支持 anchor12 仍应保留：

- attempt40–41：短暂 bearing bad；
- attempt42–44：重新变为 pose good；
- attempt45：anchor12 为 current，bearing error 4.65°、distance error 0.020 m。

## 架构判断

本 canary 证明了用户提出的核心执行链条在工程上可以工作：

> V2 发现 next 不可信 → 状态机隔离 → Route1 自动看到下一个 next → 同一步不允许旧 next 晋升。

但它也证明不能直接把 V2 的“拒绝使用”升级成“主动拉黑”：

> 不够可信是 abstention；只有强负证据才应拥有改变 anchor identity 的权力。

这与此前 route-hint false reject 分析一致。V2 适合作为证据质量层，但不同控制动作需要不同阈值：

- 不采纳一次读数：可以使用较宽松的 `jointly_trusted=false`；
- 临时 quarantine / candidate identity change：必须要求更强、更连续的负证据；
- stop/hint 仍需各自独立语义。

## 下一步

暂不批准 ep491/ep658 Active v0。

建议 Stage 3.1：

1. promotion assessment 暴露连续概率，而不只传 `jointly_trusted` bool；
2. state classification 改为：
   - trusted；
   - uncertain/abstain；
   - strongly_untrusted；
3. active quarantine 至少要求：
   - 完整或更长的 evidence window；
   - 多次强 `p_pose_bad`，而不是任意 trust gate 失败；
   - current 仍可信；
4. 用本次 ep5 数据先做阈值 replay：
   - anchor12 不应 quarantine；
   - anchor11/10/9 应继续被识别为 strongly untrusted；
5. 再跑 shadow，不生成新的 approved active artifact；
6. 只有 shadow gate 通过后，再单独请求下一次 Active 批准。

一个直接可验证的候选规则是：要求最近4次中至少3次 `p_pose_bad >= 0.85`，并要求 full-window evidence。它会保留本次 anchor12，同时仍能捕获 anchor11/10/9；但该规则必须先在更多历史 episode 上 replay，不能只凭 ep5 单例直接固化。
