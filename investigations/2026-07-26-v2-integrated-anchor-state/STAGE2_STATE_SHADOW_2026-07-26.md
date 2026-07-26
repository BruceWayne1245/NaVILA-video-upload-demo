# Scheme 1 Stage 2：per-anchor state-transition shadow

日期：2026-07-26

## 结论

Stage 1 已证明 V2 必须从“末端否决器”前移到 promotion evidence/state 层。Stage 2 在新的隔离候选中实现了一个 **只读、可重放、无 controller effect** 的 per-anchor 状态机，用来回答：

1. next 连续不可信时，何时应进入临时 quarantine；
2. quarantine 后出现可信证据时，何时允许 re-entry；
3. 同一 anchor 在可信/不可信之间反复振荡时，何时应停止反复切换并请求 active scan；
4. current 和 next 同时不可信时，如何结束无限 hint blackout；
5. 一个 scan condition 是否会逐帧重复发请求。

离线重放结论：

- ep5 的持久双不可信被稳定识别；scan request 从逐帧重复变成每个 current-anchor 生命周期仅一次；
- ep491 的 anchor12 不再发生 11 次 quarantine / 10 次 re-entry 抖动，而是在两次完整隔离周期后，于第三次确认失信时发出一次 active-scan request；
- ep5、ep491 的全部 Stage 2 decision 都是 `controller_effect=false`；
- 结果足以进入小规模 **在线 shadow**，不足以批准 active quarantine、active scan 或 hint suppression。

## 代码边界

隔离候选：

`/home/teambruce/navila-reliability-v1_1-v2-integrated-20260726`

没有修改：

- Active50 原运行目录；
- Route1 主代码；
- 同日独立的 Route1 camera/LoFTR 路线；
- stop、motor、recovery 或 locomotion 行为。

关键文件与 hash：

| 文件 | SHA256 |
|---|---|
| `reliability/v11_integrated_anchor_state.py` | `e66c129d229b760dda9387814a4fc51227012a907c2d8a0dd1635466992a1d2e` |
| `configs/v11_integrated_anchor_state_shadow_v1.json` | `e4f7ef1bd9d8f048101ce51618260f746c8783ae0da550cc2e546ed55a2a3bbc` |
| `policy_v2_live_candidate/scripts/round_trip_eval.py` | `5a79aa923c2e1a623626e6a99b2b9b30cac4c892f902adc18948688639d23593` |
| `policy_v2_live_candidate/scripts/route_memory_agent.py` | `c54ff7875caaad41a9d130ec1221278ee710ab3ffe775fff7a50c669d0769ee5` |

Stage 2 CLI：

```text
--reliability_v11_integrated_promotion_mode=shadow
--reliability_v11_integrated_anchor_state_mode=shadow
--reliability_v11_integrated_anchor_state_policy=.../v11_integrated_anchor_state_shadow_v1.json
```

状态事件继续写入 `reliability_v11_consumer_v2.jsonl`，事件类型为：

`v11_integrated_anchor_state_shadow_decision`

结构上只有 `off`/`shadow`，policy 同时要求：

- `mode=shadow`
- `enforcement_approved=false`
- `identity_override_authorized=false`

因此该实现不能改变 Route1 vote、anchor identity、quarantine set、route hint、scan action 或 stop decision。

## 状态机

### 1. 每个 anchor 独立积累证据

每个 anchor 保存：

- trusted/untrusted 连续 streak；
- 最近 8 次 V2 assessment；
- trusted fraction；
- quarantine TTL；
- 当前 current 生命周期内的 quarantine cycle 数。

确认阈值：

- trusted：至少 2 个样本，最近窗口内 trusted fraction ≥ 0.75；
- untrusted：至少 3 个样本，最近窗口内 untrusted fraction ≥ 0.75；
- 其余为 uncertain；
- assessment 缺失时为 missing。

这里不再使用“一次 True 即恢复、三次 False 即隔离”的对称短 streak。原因是 ep491 的真实序列包含长段 True/False 交替；只增加 streak 阈值只能延后抖动，不能识别振荡。

### 2. 临时 quarantine 与 re-entry

- next 确认 untrusted 后建议临时 quarantine；
- TTL 为 30 个 assessment attempt；
- quarantine 中只有窗口重新达到 trusted 状态才建议 re-entry；
- re-entry 不再清空该 anchor 的 quarantine cycle history；
- 同一 current 生命周期最多允许同一 anchor 完成 2 个 quarantine cycle。

第三次确认失信时，不再进行第三轮 quarantine/re-entry，而是建议 active scan。

### 3. scan request 锁存

scan condition 只在状态边沿产生一次 request。之后的事件记录为：

`hold_active_scan_request`

锁存在 current anchor 改变时清空，因为新的 current 表示进入新的状态生命周期。这样既保留“每个 current 都需要独立恢复”的语义，又避免同一错误状态每 5 个 control step 重复发 scan request。

### 4. 两边都不可信

current/next 同时确认 untrusted 并持续 3 次时：

- 建议 `request_active_scan_both_untrusted`；
- `requires_expanded_candidates=true`；
- `would_suppress_precise_hint=true`；
- 实际 controller 不执行任何一项。

这实现的是用户提出的核心变化：V2 不再只能说“不可信”，而是能输出下一步状态迁移建议。但在本阶段它仍然只是观察器。

## 第一版回放暴露的问题

第一版仅使用短 streak，并且每帧重复输出 scan request。

ep5：

- `request_active_scan_both_untrusted`：357；
- `request_active_scan_chain_budget_exhausted`：235；
- `request_active_scan_repeated_quarantine`：24。

ep491：

- temporary quarantine：11；
- trusted re-entry：10。

这两个结果都不能直接上线：

- ep5 的请求是 event spam，不是 616 个独立恢复机会；
- ep491 的 11/10 是状态抖动；
- re-entry 时清空 cycle count 会掩盖持续振荡。

因此在最终策略中加入 8-sample / 75% rolling hysteresis、保留 cycle history，并锁存 scan request。

## 最终离线重放

输入仍是 Stage 1 的两个 `partial.user_stopped` 产物。重放使用既有轨迹，只验证状态机对历史 assessment sequence 的解释；它不能模拟执行 quarantine/scan 后的新轨迹。

### ep5

输入：

`..._ep5.partial.user_stopped.20260726T112350/reliability_v11_consumer_v2.jsonl`

输入 SHA256：

`49cc8cc0799992043cf835425f3273a9c8f39568545d387b4042dd6dee916f0c`

| Action | Count |
|---|---:|
| `accumulate_evidence` | 15 |
| `admit_next_evidence_without_current_veto` | 1 |
| `temporarily_quarantine_next` | 3 |
| `request_active_scan_both_untrusted` | 3 |
| `hold_active_scan_request` | 751 |
| `hold_temporary_quarantine` | 3 |
| `preserve_next_gate_without_current_authority` | 6 |
| `preserve_route1_vote` | 31 |

三个 scan request 分别对应三个 current-anchor 生命周期：

| current / next | request sequence | step | 触发 |
|---|---:|---:|---|
| 12 / 11 | 52 | 2004 | both untrusted |
| 11 / 10 | 363 | 3559 | both untrusted |
| 10 / 9 | 373 | 3609 | both untrusted |

每个生命周期只发一次 request，之后保持 latch。最终事件仍为 current10/next5 双不可信，但不再重复请求。

这说明：

- 状态机能够识别导致 hint starvation 的持久双不可信；
- 它没有把 751 个 hold 错算成 751 次独立 scan；
- ep5 的物理 wedge 仍然是独立失败轴，不能从该回放推断 active scan 会使 episode 成功。

### ep491

输入：

`..._ep491.partial.user_stopped.20260726T113915/reliability_v11_consumer_v2.jsonl`

输入 SHA256：

`09f08fe3b210e7bc5908c26c5e0adcf447e749ecc9ab2a3ef6f8911d6ca9d1b1`

| Action | Count |
|---|---:|
| `accumulate_evidence` | 36 |
| `temporarily_quarantine_next` | 2 |
| `release_quarantine_on_trusted_reentry` | 2 |
| `request_active_scan_repeated_quarantine` | 1 |
| `hold_active_scan_request` | 164 |
| `hold_temporary_quarantine` | 18 |
| `preserve_next_gate_without_current_authority` | 3 |
| `preserve_route1_vote` | 27 |

关键转移：

| sequence | step | transition |
|---:|---:|---|
| 16 | 2424 | anchor12 第一次 temporary quarantine |
| 29 | 2489 | 8-sample 窗口恢复到 75% trusted，re-entry |
| 39 | 2539 | anchor12 第二次 temporary quarantine |
| 60 | 2644 | 第二次 re-entry |
| 89 | 2789 | 第三次确认失信，发出一次 repeated-quarantine active scan request |

原来的 11/10 抖动被压缩为 2/2；第三个失信周期被明确识别为振荡，不再继续来回切换。

同时必须保留 Stage 1 的结论：ep491 的 Route1 `baseline_vote` 全程为负，V2 不是唯一阻止 promotion 的模块。Stage 2 的价值在于给“两边无稳定证据/同一 next 振荡”一个有界出口，不是证明 V2 单独造成了 freeze。

## 验证

- 新增/相关测试：28/28 passed；
- 完整候选测试：54 passed，1 failed；
- 唯一失败是仓库缺少旧 fixture：
  `experiments/2026-07-23-prospective-results/prospective_v1_1.npz`；
- Stage 2 canary preflight 通过：
  - 50 个 manifest episode 唯一；
  - Active V2 artifact 仍是显式批准的原 policy；
  - Stage 2 runtime/config 与固定 SHA 完全一致。

## 下一步与批准边界

下一步是仅运行小规模在线 shadow canary，优先 ep5/ep491，验证：

1. 实时事件数与 integrated promotion event 一一对应；
2. `controller_effect` 始终为 0；
3. scan request 在每个 current 生命周期只发一次；
4. rolling window 和 quarantine cycle 不因实时缺失 assessment 产生异常重置；
5. 日志末尾 summary 与逐事件 action count 一致；
6. Route1 executed vote 与 Stage 1 baseline 保持一致。

当前明确 **不批准**：

- 真实修改 promotion vote history；
- 真实 quarantine/next+1；
- 真实 active scan；
- 真实 suppress route hint；
- 任何 stop consumer 改动。

进入 active evidence admission 前还需要设计并验证一个关键接口：状态机如何把“建议 quarantine/scan”反馈给 Route1 candidate generator，并在实际 current/next 改变后保持单调性、最大跳过边界和可恢复性。离线旧轨迹回放不能替代这个闭环验证。
