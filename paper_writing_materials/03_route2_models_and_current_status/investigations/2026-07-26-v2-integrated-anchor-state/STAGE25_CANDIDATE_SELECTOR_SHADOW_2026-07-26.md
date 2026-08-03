# Scheme 1 Stage 2.5：candidate-selector shadow 与可恢复 scan latch

日期：2026-07-26

## 结论

Stage 2.5 已在隔离候选中把 Stage 2 的 per-anchor 状态建议继续向 Route1 的候选选择层推进，但仍保持 **纯 shadow、零 controller effect、零 Route1 状态修改**。

它回答了两个此前缺少运行时证据的问题：

1. V2 建议临时隔离 next anchor 后，系统是否能够在不破坏 Route1 单调性和跳过预算的前提下，明确提出下一个候选；
2. active-scan request 是否能够在信任恢复后撤销，而不是一旦锁存就永久停留在 scan 状态。

在线结果确认：

- ep491 中，selector 能在 shadow quarantine anchor10 后提出 anchor9，且严格遵守单调性和预算；
- ep658 的早期 anchor8 quarantine 不是误杀：world-pose truth check 显示其 bearing error 约为 73.5°；
- 第一版 ep658 暴露的真正问题是 scan latch 不会在信任恢复后撤销；
- 加入 3 次连续可信确认的 cancellation hysteresis 后，更新版 ep658 在线出现了完整的
  `request_active_scan_both_untrusted → hold → cancel_active_scan_on_trust_recovery → preserve Route1`
  转移；
- 同一更新版运行后段又真实触发了 quarantine-chain budget exhausted，说明 “active scan 到底执行什么” 仍是进入 active 前必须定义的 controller 语义，不能把 shadow proposal 直接接成动作。

因此，Stage 2.5 证明了 **候选选择接线和可恢复状态边界可行**，但尚未批准 active quarantine、active candidate override 或 active scan。

## 代码边界

隔离候选：

`/home/teambruce/navila-reliability-v1_1-v2-integrated-20260726`

新增：

- `reliability/v11_integrated_candidate_selector.py`
- `tests/test_v11_integrated_candidate_selector.py`

修改：

- `reliability/v11_integrated_anchor_state.py`
- `configs/v11_integrated_anchor_state_shadow_v1.json`
- `policy_v2_live_candidate/scripts/route_memory_agent.py`
- `policy_v2_live_candidate/scripts/round_trip_eval.py`
- `tools/replay_v11_integrated_anchor_state.py`
- Stage 2.5 canary runner 与 wiring/state tests

关键 runtime/config hash：

| 文件 | SHA256 |
|---|---|
| `reliability/v11_integrated_anchor_state.py` | `17f56d6237a3c83dc15cced9e1fcb7b99910dce57ffbc640249ed5015c5fd328` |
| `reliability/v11_integrated_candidate_selector.py` | `3f29596146143fbc7628f76c740895d4e45c909dadf942e75e379ab349f9c498` |
| `configs/v11_integrated_anchor_state_shadow_v1.json` | `653c6f3db7e77e39f97e4511437593001e9ca41b0c0997c92d0acc7ea8c1a037` |
| `policy_v2_live_candidate/scripts/round_trip_eval.py` | `e9c51f0016dc6b73184a66fed9710ef838a1fc4820af168b745cb01409e8e249` |
| `policy_v2_live_candidate/scripts/route_memory_agent.py` | `5445edabed36aee59115361bec19b4ac49f17aa9efb55dfbcbf861f3a33569cc` |

没有修改：

- Active50 原运行目录；
- Route1 主代码或同日 camera/LoFTR 路线；
- stop/hint/motor/locomotion 行为；
- Route1 实际 current、next、quarantine set 或 promotion vote。

## Candidate selector shadow

新增 CLI：

```text
--reliability_v11_integrated_candidate_selector_mode=shadow
```

该模式结构上要求：

- integrated promotion 为 `shadow`；
- integrated anchor state 为 `shadow`；
- policy 中 `enforcement_approved=false`；
- `identity_override_authorized=false`；
- candidate direction 为 `descending_anchor_index`。

每个 Stage 2 state decision 后，selector 读取同一时刻的：

- Route1 current/next；
- 可用 anchor indices；
- Route1 quarantine set；
- Route1 quarantine budget used/limit；
- V2 shadow quarantine set；
- active-scan latch。

然后输出 `v11_integrated_candidate_selector_shadow_proposal`，可能的 proposal 为：

- `preserve_route1_next`
- `propose_next_candidate`
- `request_active_scan`
- `hold_active_scan_request`
- 没有合法候选或预算不足时的 scan request

候选选择使用 Route1 与 shadow quarantine set 的并集，并明确记录：

- 实际 Route1 next 与 proposed next；
- 被排除的 anchors；
- projected budget；
- 是否满足单调性；
- 是否需要对新候选做 counterfactual assessment；
- `controller_effect=false`；
- `route1_state_mutated=false`。

它不会直接修改 Route1。尤其是，shadow 中提出一个新 next 并不等价于证明新 next 可信；新候选必须在 active 设计中先经过 V2 assessment，不能盲跳。

## Scan latch 修正

Stage 2 的第一版 latch 只会在 current anchor 改变时清空。初版 ep658 在线数据表明，这会把短暂的 “both untrusted” 固化为永久 scan request，即使后续 current/next 已恢复可信。

修正后的 policy：

- `both_untrusted_scan_attempts`：3 提高到 8；
- 新增 `active_scan_cancel_trusted_attempts=3`；
- both-untrusted 触发的 scan：current 或 next 任一方连续恢复可信 3 次后取消；
- repeated-quarantine / chain-budget 触发的 scan：只有 next 连续可信 3 次后取消，避免因 current 原本就可信而立即自取消；
- cancellation 作为独立事件
  `cancel_active_scan_on_trust_recovery`
  记录，保留被取消的 trigger action。

这不是 active scan 的实现；它只是把 shadow state 由单向永久 latch 改为有 hysteresis 的可恢复状态。

## 离线 replay

Replay 工具同步输出 synthetic candidate proposal。由于历史 Stage 1 日志没有记录 Route1 quarantine snapshot，离线 replay 明确标记：

`synthetic_all_seen_anchors_no_route1_quarantine`

因此，第一次候选分歧之后的 proposal 只能用于验证状态机和不变量，不能被解释为真实执行后的轨迹。

### ep5

- state/selector controller effect：0；
- Route1 state mutation：0；
- 单调性违规：0；
- 预算违规：0；
- selector action：
  - `hold_active_scan_request`：616
  - `preserve_route1_next`：66
  - `propose_next_candidate`：124
  - `request_active_scan`：7

首个候选分歧：

- sequence 50，step 1994；
- current12；
- Route1 next11；
- proposed next10。

这仍不能解决 ep5 的物理 wedge；它只证明 selector 不会因为长期不可信而停在“只能拒绝、没有下一步”的接口上。

### ep491

- state/selector controller effect：0；
- Route1 state mutation：0；
- 单调性违规：0；
- 预算违规：0；
- selector action：
  - `hold_active_scan_request`：95
  - `preserve_route1_next`：121
  - `propose_next_candidate`：34
  - `request_active_scan`：3

修正后的 replay 中 repeated-quarantine scan 分别在 sequence 89、151、215 触发，并在 next 恢复可信后于 sequence 131、190、232 取消。

## 在线 shadow canary

所有 canary 均在获得结构证据后手动停止并标记为 `partial.user_stopped`；没有 completion artifact，不进入 round-trip 成功率分母。

### ep491：candidate-selector 接线

run tag：

`reliability_v11_v2_integrated_candidate_selector_stage25_shadow_canary_20260726`

结果目录：

`..._ep491.partial.user_stopped.20260726T155544`

JSONL：

- SHA256：`59540250735ea03e247fe127e6d36b4733bc6fff865c29cc3089ccd099068e2d`
- JSON events：327；
- promotion/state/selector：98/98/98；
- 三类事件 attempt/step 严格配对，sequence 连续；
- promotion/state/selector controller effect：0；
- Route1 state mutation：0；
- 单调性/预算违规：0。

selector action：

| Action | Count |
|---|---:|
| `preserve_route1_next` | 55 |
| `propose_next_candidate` | 10 |
| `request_active_scan` | 1 |
| `hold_active_scan_request` | 32 |

首个分歧：

- sequence 56，step 2449；
- current11；
- Route1 next10；
- proposed next9；
- Route1 quarantine set 为空；
- shadow quarantine set 为 `[10]`；
- projected budget 为 1/4。

sequence 66 在 current/next 都不可信时产生一次 scan request，之后只 hold，没有重复 request。

第一次 bootstrap 曾在 VLM checkpoint setup 中出现一次性 Python unpack 异常；没有 result directory、没有启动 Isaac。唯一一次干净重试正常，因此该事件只记为基础设施失败，不计为 episode/model failure。

### ep658 第一版：negative control 与 stale latch

run tag：

`reliability_v11_v2_integrated_candidate_selector_stage25_shadow_canary_20260726`

结果目录：

`..._ep658.partial.user_stopped.20260726T155951`

JSONL SHA256：

`9fe8ae302e9d0c9c48f1e9923c732eabc0b6039708ef9e04d18c7730627d22e2`

第一版在线结果最初看起来像 “ep658 被错误 quarantine”，但 world-pose truth check 否定了这个解释：

- sequence 3 的 next anchor8 bearing error 约为 73.5°；
- early current/next 确实存在双不可信；
- 后续 current/next 恢复可信；
- 真正的 bug 是 scan latch 没有 cancellation transition。

因此，本例没有证明 V2 quarantine 是 false positive；它证明了永久 latch 的恢复语义不完整。

### ep658 更新版：request、cancel、再次耗尽预算

run tag：

`reliability_v11_v2_integrated_candidate_selector_stage25_hysteresis_shadow_canary_20260726`

结果目录：

`..._ep658.partial.user_stopped.20260726T151228Z`

最终落盘数据：

- JSONL SHA256：`39cb256b6d473b02e15e1c46e5482e9a151888cea2e85c5f08ccd23a92754863`
- JSON events：451；
- promotion/state/selector：146/146/146；
- 三类事件 attempt/step 集合完全一致；
- state/selector sequence 均为 1–146 连续；
- promotion controller effect：0；
- anchor-state controller effect：0；
- selector controller effect：0；
- Route1 state mutation：0；
- 单调性违规：0；
- 预算违规：0。

原有 Active V2 consumer 仍产生 7 次 controller effect；这属于冻结的旧 consumer path，不是 Stage 2.5 的副作用。

关键状态转移：

| sequence | step | current / next | transition |
|---:|---:|---|---|
| 3 | 1434 | 9 / 8 | shadow quarantine anchor8；selector 提出 anchor7 |
| 10 | 1469 | 9 / 8 | `request_active_scan_both_untrusted` |
| 28 | 1559 | 9 / 8 | next 恢复可信，`cancel_active_scan_on_trust_recovery` |
| 66 | 1749 | 7 / 6 | shadow quarantine anchor6；selector 提出 anchor5 |
| 95 | 1899 | 7 / 5 | 合并 quarantine 后提出 anchor4 |
| 100 | 1929 | 7 / 4 | 提出 anchor3 |
| 105 | 1959 | 7 / 3 | projected budget 4/4，提出 anchor2 |
| 110 | 1989 | 7 / 2 | `request_active_scan_chain_budget_exhausted` |

selector action：

| Action | Count |
|---|---:|
| `preserve_route1_next` | 48 |
| `propose_next_candidate` | 43 |
| `request_active_scan` | 2 |
| `hold_active_scan_request` | 53 |

该运行给出了两个互补证据：

1. both-untrusted scan 不再永久锁死，可信恢复后能明确取消；
2. 当 Route1/V2 合并 quarantine chain 真正达到预算时，系统仍需要一个已定义的 active-sensing 行为；仅有 “request scan” 事件不等于问题已经解决。

## 测试

- 新增/相关测试：36 passed；
- 完整候选测试：62 passed，1 failed；
- 唯一失败是既有缺失 fixture：
  `experiments/2026-07-23-prospective-results/prospective_v1_1.npz`；
- canary preflight 固定全部 runtime/config SHA，并校验：
  - `both_untrusted_scan_attempts=8`
  - `active_scan_cancel_trusted_attempts=3`

## Active readiness

当前结论是：**可以开始实现“结构上默认关闭的 active mode”，但还不能直接进行 active controller canary。**

进入 active canary 前必须完成：

1. 定义 `active scan` 的真实语义：
   - 是原地视觉扫描、有限角度旋转、短步探索，还是只扩大候选集合；
   - 何时开始、何时结束、最大持续时间和失败后的 fallback；
   - 必须与 locomotion/stuck recovery 的职责分开。
2. active selector 对每个 proposed next 必须先获取同语义层的 V2 assessment，不能把 shadow proposal 直接写入 Route1 identity。
3. 实现但默认关闭：
   - 显式 `off/shadow/active`；
   - policy approval bit；
   - episode 级 kill switch；
   - quarantine/skip/scan 的硬预算；
   - 完整 provenance 与 `session_end` 审计。
4. 再跑至少一个 ep5 在线 selector shadow，或补充正常成功 episode，验证候选推进没有对成功路径造成系统性回归。
5. stop 与 route-hint consumer 继续独立处理：
   - Stage 2.5 不批准取消 stop veto；
   - 不可信 raw candidate 不能直接封禁 post-filter stateful hint。

完成以上实现和 shadow 验收后，下一步才是少量、可中止、明确排除 partial 的 3–5 episode active canary；不是直接启动新的 50ep。
