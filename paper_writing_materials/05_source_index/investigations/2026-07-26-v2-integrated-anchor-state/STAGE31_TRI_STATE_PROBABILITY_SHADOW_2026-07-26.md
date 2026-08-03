# Scheme 1 Stage 3.1：三值概率状态与 shadow 验证

日期：2026-07-26

## 结论

Stage 3 Active v0 ep5 canary 暴露的 false quarantine 已在隔离候选中修正，并完成单元测试、三组定向 replay、38 个既有 outbound-success 日志的历史触发点分析，以及 ep5/ep491 两个新的在线 shadow canary。

新状态语义为：

- `trusted`：`jointly_trusted` 在 Route1 的滚动窗口内达到可信确认；
- `uncertain`：V2 abstain 或证据不足，不拥有改变 candidate identity 的权力；
- `strongly_untrusted`：最近4次中至少3次 `p_pose_bad >= 0.90`，且至少已有3个概率样本。

即使 next 已经 `strongly_untrusted`，也只有 current 已确认 `trusted` 时才允许产生 temporary-quarantine proposal。current 不可信或只是不确定时，状态机只能 hold；current 与 next 连续8次都为 `strongly_untrusted` 时，才产生一次 edge-triggered active-scan request。

另外，所有 probability/trust evidence 都限定在同一个 current-anchor phase 内。Route1 的 current 一旦变化，旧 evidence window、quarantine chain 与 scan latch 一起清空，防止把上一段轨迹中的旧高风险概率用于刚进入的新 route phase。

结果：

- Active v0 原 ep5 日志 replay：
  - anchor12 false quarantine 消失；
  - anchor11/10/9/8 仍在 attempt 30/33/36/39 被正确识别；
  - 四次 proposal 的 world-pose truth 均为 pose bad；
- 新 ep5 在线 shadow：
  - 89 组 promotion/state/selector 严格配对；
  - 连续概率字段完整；
  - integrated controller OFF；
  - 0 quarantine、0 scan、0 Route1 mutation；
- 新 ep491 在线 shadow：
  - current10/next9 连续8次 strongly-untrusted 后，在 attempt68 只触发一次 scan request；
  - world-pose truth 同时确认两者 pose bad；
  - 0 quarantine、0 Route1 mutation；
- 38 个既有 outbound-success 日志的原轨迹历史触发点上，`p>=0.90` 三次强负证据并要求 current trusted 后，瞬时 truth precision 为 96/97 = 99.0%。

这证明三值分离和 current-authority 条件显著降低了 identity-change 风险，但 97 个历史触发点中仍有1个瞬时 false positive。因此 **没有生成新的 Active artifact，也没有重新开启 Active v0**。下一步应先分析该唯一 false positive（ep5 attempt171 anchor10）并定义 active-scan 执行语义，再决定是否请求新的单 episode Active 批准。

## 修改边界

隔离候选：

`/home/teambruce/navila-reliability-v1_1-v2-integrated-20260726`

修改：

- `reliability/v11_consumer_policy_v2.py`
  - integrated promotion decision 新增 current/next 的：
    - `p_bearing_bad_30`
    - `p_distance_bad_0p5`
    - `p_pose_bad`
  - 新在线日志不再只传 `jointly_trusted` bool。
- `reliability/v11_integrated_anchor_state.py`
  - 新增独立 pose-probability window；
  - `jointly_trusted=false` 不再等价为 negative evidence；
  - 新增 `strongly_untrusted`；
  - temporary quarantine 要求 next strongly-untrusted 且 current trusted；
  - current phase 改变时清空旧 evidence；
  - decision event 记录 strong count/fraction/window size。
- `configs/v11_integrated_anchor_state_shadow_v1.json`
  - `strong_untrusted_pose_probability_threshold=0.90`
  - `strong_untrusted_window_attempts=4`
  - `strong_untrusted_min_observations=3`
  - `strong_untrusted_min_count=3`
- `tools/replay_v11_integrated_anchor_state.py`
  - 新日志直接使用 promotion event 中的连续概率；
  - 老日志自动 join 同目录 `reliability_v11_shadow.jsonl`；
  - 缺失对应 attempt/anchor score 时显式失败，不静默退化成 bool。
- state/consumer tests；
- canary runner 的 hash 与 policy preflight。

没有修改：

- Route1 主代码；
- `round_trip_eval.py`；
- `route_memory_agent.py`；
- stop、hint、motor 或 locomotion 行为；
- 既有 Active v0 controller scope；
- 已消耗的 ep5 Active approval。

## Runtime hash

| 文件 | SHA256 |
|---|---|
| `reliability/v11_consumer_policy_v2.py` | `3815283afc1da70c29e455519cf657d67049f708287bb14fd9213ccf5660244a` |
| `reliability/v11_integrated_anchor_state.py` | `40d55111ec4335d1c5a6c6d6386f173d753524038c005536211c672f6a08c9d4` |
| `configs/v11_integrated_anchor_state_shadow_v1.json` | `2ea87ed0e16a669ef85a1445a76f318a8cea8d48c9b3138ebc09664e9fd6876a` |
| `tools/replay_v11_integrated_anchor_state.py` | `fbb1607d21d0132499020b1970b4dd7b19875c96841d5452a78a5917c8499c47` |
| canary runner | `c016329c44dabf629e593873927cfbbe41279b753abaea47f239648a9d46898e` |
| `round_trip_eval.py`（未改） | `9dce7ac859025f1896bcda137d454e827c2868f8fc54f978e2d20e94e55bc881` |
| `route_memory_agent.py`（未改） | `585360936279be97f1530562ed0c5d8adfd5f2cb332b9d8885eddff712aa6791` |

## 为什么不是简单提高 bool 窗口

Active v0 的 anchor12 触发窗口为：

| attempt | truth pose bad | `jointly_trusted` | `p_pose_bad` |
|---:|---:|---|---:|
| 20 | 0 | true | 0.216 |
| 21 | 0 | false | 0.556 |
| 22 | 1 | false | 0.872 |
| 23 | 0 | false | 0.807 |
| 24 | 1 | false | 0.935 |
| 25 | 0 | false | 0.570 |
| 26 | 0 | false | 0.403 |

旧状态机看到的是 6/7 个 false，然后把 anchor12 当成 untrusted。新状态机看到的是“只有一次达到0.90的强负证据”，因此保持 uncertain。

这一区分不是阈值微调，而是把两种不同语义拆开：

- `jointly_trusted=false`：这一次读数不适合作为正向控制证据；
- 多次高 `p_pose_bad`：有足够强的证据主动改变 candidate identity。

## stale evidence 修正

第一版 Stage 3.1 replay 消除了 attempt26 的 anchor12 误杀，但在 Route1 将 current 从13推进到12后，旧状态仍保留了 anchor11 在上一段 route phase 中的高概率历史，于 attempt45 又会错误隔离当时已经正确的 anchor11。

world-pose truth：

- attempt45 current12 已恢复正确；
- next11 bearing error 10.1°、distance error 0.006 m，为 pose good；
- 触发依据全部来自 current13 阶段的旧 observation。

因此 evidence 的作用域必须是：

`episode + current-anchor phase + candidate anchor`

而不能只有：

`episode + candidate anchor`

加入 current-change reset 后，attempt45 的旧窗口只剩新 phase 的1个 observation，不再触发 quarantine。专门的回归测试覆盖了该案例。

## 定向 replay

### ep5 Active v0 日志

旧状态：

- temporary quarantine：7；
- 其中 anchor12 attempt26 为 false quarantine；
- 随后 chain budget exhausted 并 rollback。

Stage 3.1：

| attempt | current | next | action | world-pose truth |
|---:|---:|---:|---|---|
| 30 | 13 | 11 | temporary quarantine | bad |
| 33 | 13 | 10 | temporary quarantine | bad |
| 36 | 13 | 9 | temporary quarantine | bad |
| 39 | 13 | 8 | temporary quarantine | bad |

- anchor12：不 quarantine；
- four-trigger precision：4/4；
- 没有 stale phase re-quarantine；
- replay controller effects：0。

这里使用的是原 Active v0 已改变过的轨迹，只用于验证 counterfactual state decision，不是新的 active 执行结果。

### ep491 Stage 2.5 日志

- temporary quarantine proposal：1（attempt58，anchor10）；
- current 不可信时的 strong-next observation：只 hold，不改变 identity；
- 没有把“next 强负证据”越权解释成“current 也能授权跳过”。

### ep658 Stage 2.5 日志

- temporary quarantine proposal：0；
- active scan：0；
- 所有40个 selector proposal 都保留 Route1 next。

这比旧 bool 状态机更保守；旧状态在 attempt3 就隔离 anchor8。anchor8 当时 truth 确实 bad，但连续概率尚未达到 identity-change 所要求的强证据门槛。

## 38-run 历史触发点分析

数据范围：

- Active50 运行中38个非 incomplete、具有 `reliability_v11_shadow.jsonl` 的 outbound-success 结果目录；
- 逐次使用 next-role `p_pose_bad`；
- current index 改变时重置 probability/trust window；
- 每个 current phase/next anchor 只计第一次触发；
- truth 使用同一 attempt 的 posthoc world-pose label。

候选规则对比：

| 规则 | 触发数 | 同步 truth bad | precision |
|---|---:|---:|---:|
| `p>=0.85`，最近4次至少3次 | 146 | 138 | 94.5% |
| `p>=0.90`，最近4次至少3次 | 140 | 136 | 97.1% |
| 上一行 + current 必须 trusted | 97 | 96 | **99.0%** |

`p>=0.90 + current trusted` 同时保留了 ep5 Active v0 中 anchor11/10/9/8 的强负触发。

唯一同步 false positive：

- ep5；
- attempt171；
- current11 trusted；
- next10；
- probability window：0.981、0.953、0.964；
- 同步 truth：bearing error 5.3°、distance error 0.024 m，pose good；
- 该窗口的三个同步 truth 为 `[bad, good, good]`。

因此99.0%不是“无误杀”。在新的 Active 批准前必须继续检查：

- 这是短暂恢复、truth 抖动还是模型系统误判；
- 是否需要加入 strong-negative 的时间新鲜度/趋势条件；
- temporary quarantine TTL 是否足以让该类 false positive 快速 re-entry。

该统计基于原轨迹，未模拟 quarantine 后的下一候选及机器人轨迹变化，不能解释为 active 成功率。

## 新在线 shadow canary

统一 run tag：

`reliability_v11_v2_integrated_anchor_state_stage31_shadow_canary_20260726`

共同边界：

- legacy consumer Policy V2：保持原 Active50 配置；
- integrated promotion：shadow；
- integrated anchor state：shadow；
- integrated candidate selector：shadow；
- integrated candidate controller：OFF；
- 没有 motor、stop、hint 或 Route1 identity mutation；
- 两个运行都在获得所需结构证据后人工停止并标记为 `partial.user_stopped`，不进入 round-trip 成功率分母。

### ep5：negative/abstention gate

归档：

`..._stage31_shadow_canary_20260726_ep5.partial.user_stopped.20260726T160127Z`

最终日志：

- consumer JSONL SHA256：
  `b5b668d7e8c8490365e283d9eda24581289ac2ff62746c493a747f3a976390d1`
- promotion/state/selector：89/89/89；
- attempt/step 严格配对；
- state/selector sequence 连续；
- continuous probability fields：89/89完整；
- promotion/state/selector controller effect：0/0/0；
- Route1 mutation：0；
- temporary quarantine：0；
- active scan request：0；
- selector：89次全部 `preserve_route1_next`。

state action：

| action | count |
|---|---:|
| `accumulate_evidence` | 51 |
| `preserve_route1_vote` | 28 |
| `hold_strong_next_without_current_authority` | 10 |

本次 return 从 current12/next11 开始，没有发生 current transition，因此没有在线覆盖 current-phase reset；该边界由 ep5 Active 日志 replay 和专门单元测试覆盖。

后段 current/next 同时出现 strong-negative，但没有连续8次稳定满足触发条件，因此没有错误锁存 scan。

### ep491：both-strong positive gate

归档：

`..._stage31_shadow_canary_20260726_ep491.partial.user_stopped.20260726T160819Z`

最终日志：

- consumer JSONL SHA256：
  `bc941fee6316a830258b9673af19daf365672bcc68d68299a125179e220e68b4`
- promotion/state/selector：75/75/75；
- attempt/step 严格配对；
- state/selector sequence 连续；
- promotion/state/selector controller effect：0/0/0；
- Route1 mutation：0；
- temporary quarantine：0；
- active scan request：1（attempt68）；
- 后续7次为 `hold_active_scan_request`，没有重复 edge trigger。

attempt68：

| role | anchor | strong count / window | bearing error | distance error | truth |
|---|---:|---:|---:|---:|---|
| current | 10 | 4/4 | 170.63° | 0.481 m | bad |
| next | 9 | 4/4 | 116.96° | 1.264 m | bad |

状态机在 current 不可信时没有 quarantine next，而是在 both-strong 连续8次后请求有界恢复；这正是三值设计要求的 authority separation。

## 测试

定向：

- consumer/state/selector/controller/wiring：51 passed。

完整候选：

- 77 passed；
- 1 failed；
- 唯一失败仍是既有缺失 fixture：
  `experiments/2026-07-23-prospective-results/prospective_v1_1.npz`。

新增回归覆盖：

- abstention 不累积为 strong negative；
- continuous probabilities 从 consumer decision 传入 state；
- strong next 在 current 未确认可信时不能 quarantine；
- current transition 不复用旧 strong-negative window；
- existing shadow locks 与 active-controller scope 不变。

runner preflight：

- 50个 manifest episode 唯一；
- runtime/config hash 全部匹配；
- integrated state policy 的0.90/3-of-4参数匹配；
- Active v0 controller 仍为 OFF。

运行停止后残留的两个 Isaac/VLM GPU child process 均按精确 PID 发送 TERM；最终 GPU process list 为空。

## 当前 Active 状态

Stage 3 的 ep5 approved artifact 没有被修改，但其一次性批准已经用完，kill switch 仍 engaged。

Stage 3.1：

- 没有新 approved artifact；
- 没有运行 integrated Active；
- 没有把 shadow policy 改为 active；
- 没有扩大 controller scope；
- active scan 仍只是 proposal，不会执行 motor/search。

## 下一步

1. 深挖历史唯一 false positive：ep5 attempt171 anchor10。
2. 决定 temporary quarantine 是否需要额外的 temporal recovery/trend gate，而不是只依赖3个高概率。
3. 为 `request_active_scan_both_untrusted` 定义一个单独、有限、可回滚的执行语义；Active v0 当前遇到 scan proposal 只会 fail-open disable。
4. 对新规则扩大 replay cohort，并把“同一触发窗口的 truth 序列”而非单一触发帧作为安全指标。
5. 只有上述 gate 通过后，才向用户请求一个新的、明确 episode-scoped Active 批准。

