# Scheme 1 Stage 3：Active v0 默认关闭实现与 ep5 shadow gate

日期：2026-07-26

## 结论

Active v0 的代码路径已经在隔离候选中实现，但仍处于 **不可启动的默认关闭状态**。本阶段没有运行 active controller。

Active v0 只允许两项原子操作：

1. 把 V2 已连续确认不可信的 next 放入独立、可逆的临时 quarantine；
2. 在同一个 control attempt 阻止该 next 晋升，避免出现“刚隔离、同一步又被 Route1 promotion commit”的竞态。

明确不允许：

- 旋转、前进或任何 motor action；
- stop、stop-veto、hint 或 hint-action 修改；
- 修改 Route1 永久 quarantine set；
- 无预算的候选跳过；
- 执行尚未定义的 active scan。

ep5 在线 selector shadow 已补齐。最终 119 组三联事件中，V2 对 anchor10 建议两次临时隔离、一次可信 re-entry，并在 current11/next10 双不可信后只产生一次 scan request。对该真实在线日志做未执行的 Active v0 回放：

- 3 次可逆 quarantine-set 同步；
- 22 个 attempt 会原子阻止被隔离 next 的 promotion；
- 第一次 active-scan request 时撤销全部 V2 临时状态，并永久降级为该 episode 的 Route1；
- 0 motor/stop/hint action。

因此，代码和 shadow gate 已达到 **请求一个 3–5 episode Active v0 canary 批准** 的条件；尚未获得该批准，也没有生成可运行的 approved policy artifact。

## 隔离候选与 hash

隔离候选：

`/home/teambruce/navila-reliability-v1_1-v2-integrated-20260726`

| 文件 | SHA256 |
|---|---|
| `reliability/v11_integrated_candidate_controller.py` | `3472444e6c51fc5e705df7c26b6b2315af37cbacb183b45d9ca4b51a14e1c5a5` |
| `configs/v11_integrated_candidate_controller_active_v0.template.json` | `90f3b7f06438787e6cac63ec4fab1b94430756d5663d75684a6ed73b4322dbf9` |
| `policy_v2_live_candidate/scripts/round_trip_eval.py` | `abd208adbeba08caa12886cff5dc65b01d14eed1ecafe659e163b1f8f8323cb3` |
| `policy_v2_live_candidate/scripts/route_memory_agent.py` | `585360936279be97f1530562ed0c5d8adfd5f2cb332b9d8885eddff712aa6791` |
| ep5 shadow runner | `7f79ab9d04a00ed9a040a20cba4a40b7fdb6b5726a50f778442824577d827fb7` |

没有修改：

- Active50 原目录；
- Route1 主代码；
- 同日 camera/LoFTR/vision-disagreement 工作流；
- stop/hint/motor/locomotion 逻辑。

## 默认关闭与四重授权

Active controller CLI 默认为：

```text
--reliability_v11_integrated_candidate_controller_mode=off
```

启动 Active v0 必须同时满足：

1. CLI 明确指定 `mode=active`；
2. CLI 明确提供 `active_armed`；
3. policy 同时包含：
   - `mode=active`
   - `enforcement_approved=true`
   - `identity_override_authorized=true`
4. 必须提供 episode kill-switch sentinel path。

仓库候选中当前只有：

`v11_integrated_candidate_controller_active_v0.template.json`

该模板故意固定为：

```json
{
  "enforcement_approved": false,
  "identity_override_authorized": false
}
```

因此，即使误加 active CLI，该模板也会在初始化时被结构性拒绝。目前没有 approved Active v0 artifact。

## Controller 边界

### 1. 与 Route1 quarantine 分离

RouteMemoryAgent 新增独立集合：

`_v11_active_quarantined_anchor_indices`

Route1 原有 `_quarantined_anchor_indices` 不被 V2 修改。候选选择只在 `_next_candidate_index` 中临时使用两者并集。

这使得：

- V2 quarantine 可以随 trusted re-entry 撤销；
- current 生命周期改变后可以清理；
- kill switch/预算失败时可以完整 rollback；
- 不会把 shadow/active 实验状态永久写进 Route1 证据历史。

### 2. 同一步 promotion suppression

candidate transition hook 位于：

- Stage 1 promotion assessment 之后；
- Route1 promotion history/commit 之前。

Active directive 若隔离当前 next，则必须同时返回：

`suppress_promotion=true`

RouteMemoryAgent 验证 next 已实际存在于 V2 临时 quarantine set，否则抛出运行时错误。这样 quarantine 与 promotion suppression 是一个原子边界，而不是两个可能竞态的操作。

### 3. 硬预算

policy 同时限制：

- `max_active_quarantines=4`
- `max_state_mutations_per_episode=12`

RouteMemoryAgent 再次验证：

- 所有 V2 quarantine index 必须小于 current；
- 数量不得超过 Route1 chain budget；
- promotion suppression 必须有对应的 quarantined next。

### 4. Kill switch 与 fail-safe rollback

kill-switch sentinel 每个 decision 都重新检查。

以下任何条件发生时：

- kill switch 文件出现；
- active quarantine 数超限；
- episode mutation budget 耗尽；
- 收到 active-scan request；

controller 会：

1. 撤销全部 V2 临时 quarantine；
2. 不再 suppress promotion；
3. 将该 episode 的 Active v0 永久 disabled；
4. 回退到 Route1；
5. 保持 motor/stop/hint 权限为 false。

rollback 即使在 mutation budget 已耗尽时仍允许执行，因为它是撤销影响，而不是扩大影响。

## 为什么 Active v0 不执行 active scan

Stage 2.5 已确认 scan latch 的 request/cancel 状态语义，但没有证明哪一种真实动作最好：

- 原地旋转；
- 小角度扫描；
- 短步探索；
- 扩大同时匹配的 candidate window。

这些方案会改变 observation distribution 或 locomotion，不能隐含塞进 candidate quarantine canary。

因此 Active v0 收到任何 scan request 时采用：

`disable_on_unimplemented_active_scan`

它撤销 V2 临时状态并回到 Route1。第一轮 Active canary 只回答：

> 在 scan 之前，V2 的可逆 quarantine + 原子 promotion suppression 是否能更早离开错误 next，并且不破坏成功路径？

## 测试

定向 controller/state/selector/wiring：

- 35 passed。

完整候选测试：

- 73 passed；
- 1 failed；
- 唯一失败仍为既有缺失 fixture：
  `experiments/2026-07-23-prospective-results/prospective_v1_1.npz`。

新增测试覆盖：

- 未批准模板不可加载；
- approved policy 仍必须显式 armed；
- quarantine 与 promotion suppression 原子执行；
- trusted re-entry 撤销 V2 quarantine；
- active scan 不触发 motor，直接 disable；
- kill switch 阻止并回滚状态；
- mutation budget fail-safe rollback；
- scope 中加入 motor/stop 或删除原子 promotion suppression 均被拒绝；
- RouteMemoryAgent 只在 active directive 下改变临时 selector state；
- shadow callback 保持零副作用。

## ep5 在线 shadow

run tag：

`reliability_v11_v2_integrated_candidate_selector_stage25_ep5_shadow_canary_20260726`

结果目录：

`..._ep5.partial.user_stopped.20260726T152920Z`

JSONL：

- SHA256：`3c7af7f2c5607ae4629922e356de947e3f8a580ac4df4051e8e439cb24b78b92`
- JSON events：375；
- promotion/state/selector：119/119/119；
- attempt/step 集合严格一致；
- promotion/state/selector controller effect：0/0/0；
- Route1 state mutation：0；
- 单调性违规：0；
- budget 违规：0。

state action：

| Action | Count |
|---|---:|
| `accumulate_evidence` | 18 |
| `preserve_next_gate_without_current_authority` | 9 |
| `preserve_route1_vote` | 43 |
| `temporarily_quarantine_next` | 2 |
| `hold_temporary_quarantine` | 17 |
| `release_quarantine_on_trusted_reentry` | 1 |
| `request_active_scan_both_untrusted` | 1 |
| `hold_active_scan_request` | 28 |

selector action：

| Action | Count |
|---|---:|
| `preserve_route1_next` | 68 |
| `propose_next_candidate` | 22 |
| `request_active_scan` | 1 |
| `hold_active_scan_request` | 28 |

关键转移：

| sequence | step | current / next | transition |
|---:|---:|---|---|
| 62 | 2004 | 11 / 10 | 第一次 temporary quarantine；selector 提出 anchor9 |
| 75 | 2069 | 11 / 10 | trusted re-entry，撤销 quarantine |
| 82 | 2104 | 11 / 10 | 第二次 temporary quarantine |
| 91 | 2149 | 11 / 10 | current/next 双不可信，产生一次 scan request |
| 92–119 | 2154–2289 | 11 / 10 | 28 次 hold，无重复 request |

数据充分后手动停止；没有 completion artifact，不进入 round-trip 成功率分母。对应 VLM/Isaac 进程组已清理，GPU 无残留 compute process。

## 未执行的 Active v0 回放

将 ep5 的 119 个真实在线 selector proposal 输入 approved-in-memory controller，仅计算 directive，不修改原轨迹：

| Executed action | Count |
|---|---:|
| `preserve_route1` | 87 |
| `replace_active_quarantines` | 3 |
| `disable_on_unimplemented_active_scan` | 1 |
| `hold_disabled` | 28 |

结果：

- controller state effects：4，其中 3 次同步/撤销 quarantine，1 次 scan 时 fail-safe rollback；
- promotion suppression attempts：22；
- 第一次 scan request 后 episode disabled；
- motor/stop/hint effects：0。

这里的 22 次 suppression 是同一 shadow 轨迹上的计数。真实 Active 执行第一次 quarantine 后，下一 attempt 的候选将改变，因此后续轨迹会分叉；不能把 22 次解释成真实 Active 一定会执行 22 次 suppression。

## Active readiness

现在已经满足小规模 Active v0 canary 的工程门槛：

- ep491、ep658、ep5 selector shadow 均完成；
- 成功保持、quarantine、re-entry、scan request/cancel、chain budget 均有在线证据；
- Active v0 权限被限制在候选 quarantine + 对应 promotion suppression；
- active scan、motor、stop、hint 均不在 scope；
- kill switch、硬预算、rollback、provenance 已接线；
- checked-in template 不可运行。

下一步需要独立、明确批准：

1. 从模板生成 hash 固定的 approved policy；
2. 冻结 3–5 个 episode 的 canary manifest，至少包含：
   - ep5：物理 wedge/双不可信压力例；
   - ep491：长期错误候选压力例；
   - ep658：能够恢复信任的 negative/control 例；
3. 每个 episode 独立 kill-switch path；
4. 先单 episode，再扩到 3–5 个；
5. partial、timeout、kill-switch fallback 均不计入成功率。

尚不应直接运行 50ep，也不应在这一轮把 active scan、route-hint 或 stop 修正混入同一个 canary。
