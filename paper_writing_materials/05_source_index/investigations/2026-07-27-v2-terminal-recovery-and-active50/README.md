# Route2 终段恢复、ep205 根因与 Active-50 队列（2026-07-27）

## 当前结论

本 investigation 以 GitHub `main` 在开始工作时的最新提交
`6a603b421572675df5e249c14cd57d495ce64afa` 为背景权威，并延续
`investigations/2026-07-26-v2-integrated-anchor-state/` 的 Route2 路线。

ep205 的失败不是“进入 3 m 后 forced stop 单点失效”，也不是某个模型判断
逻辑突然反转。真实链路是：

1. 机器人第一次进入 3 m 欧氏半径时仍位于返程路径的非终点段，立即强制停止
   并不合理；
2. 随后 next anchor A1 的观测质量快速下降；
3. 旧系统把 A1 的低可信度同时传播到 route hint、hint action 和 stop
   consumer；
4. A2 本身仍然高度可信，但旧系统无法让 A2 通过固定 A2→A1 边重建出的
   A1 几何继续辅助控制；
5. 终段由此同时失去导航提示和停止保护，最终在 4.476 m 处接受 VLM stop。

因此这是一个系统级脆弱性：**单个坏 next anchor 足以让整条辅助链路在最关键的
停止区间失能**。今天的修改修复了这个已观测 failure path，同时保持 stop
侧默认保守。Active scan 只完成了可审计计划层，真实 motor executor 尚未启用。

## Stage 3.2 的实际 5ep 结果

昨天批准的 5ep cohort 实际得到两个严格可用 completion：

| episode | outbound | return | strict round trip | 最终距离 | 说明 |
|---:|:---:|:---:|:---:|---:|---|
| 5 | true | true | true | 2.685 m | 成功；4 次 quarantine 经 world-pose 检查均正确 |
| 205 | true | false | false | 4.476 m | completion 完整；用于今天的终段根因分析 |

ep491 的 VLM bootstrap 失败，exit code 98，没有 result directory；runner 因旧版
“无结果目录立即中止”策略没有继续到 ep500/658。因此不能把这次 5ep 启动写成
5 个任务结果，也不能用 1/2 的小样本估计总体成功率。机器可读冻结见
[`data/stage32_results.json`](data/stage32_results.json)。

## ep205 证据链

完整 ep205 completion 包含：

- trajectory 3652 行；
- replay frame 1702；
- V1.1 shadow 1025 行；
- V2 consumer 1056 行；
- outbound success=true；
- return success=false；
- 最小 distance-to-start=2.656 m；
- 最终 distance-to-start=4.476 m。

第一次进入 3 m 是 step 2973，distance=2.996 m；此时 nearest return-path
index=3，并非终点 anchor。最接近起点发生在 step 3236。最终 stop 在 step
3651。

在真正失能的 A2/A1 区间：

- recovery replay 的 geometry fallback 覆盖 attempts 247–258、steps
  3179–3234，完整使用 12-assessment budget；
- attempt 251 / step 3199：
  - A2 `jointly_trusted=true`、`bearing_trusted=true`、
    `p_pose_bad=0.002042`；
  - A1 `jointly_trusted=false`、`bearing_trusted=false`、
    `p_pose_bad=0.984326`；
- 旧 consumer 因 raw A1 阻止 hint action；
- 新 consumer 允许使用 A2 的 bearing trust 驱动单跳重建 hint action；
- 新 consumer 仍禁止 derived forced stop，并保留 VLM stop veto。

真实日志中 step 3201 的单跳重建向量：

- predicted distance=2.202 m，truth=1.926 m，误差=0.276 m；
- predicted bearing=-75.256°，truth=-76.298°，误差=1.04°。

这证明在实际失败区间里，可信 A2 加固定 A2→A1 几何确实能提供有用方向。
它是 recorded-log counterfactual，不等价于已经证明物理 trajectory 必然成功。
机器可读证据见 [`data/ep205_terminal_recovery_evidence.json`](data/ep205_terminal_recovery_evidence.json)。

## 三个系统问题及修改

### 1. A0 为什么没有可用 ICP

旧实现只在机器人沿 outbound 路径移动并达到 anchor 间距时采集完整
RGB-D/local-map descriptor。A0 只是逻辑起点，保存 pose/distance，但 reset
时没有执行与普通 anchor 等价的 sensor capture；因此 A0 没有可匹配点云。
这是采集生命周期的设计缺口，不是 A0 环境天然不可定位。

新增 opt-in：

`--route_memory_capture_start_anchor_descriptor`

reset 后以 zero command 捕获一次 RGB-D/local map 并回填 A0。A0 的 pose、
distance 和固定边仍保持原值，避免为了补 descriptor 改写路线几何。实现位于：

- [`code/production_snapshot/route_memory_agent.py`](code/production_snapshot/route_memory_agent.py)
- [`code/production_snapshot/round_trip_eval.py`](code/production_snapshot/round_trip_eval.py)

### 2. 一个坏 anchor 不再击穿整套系统

`AnchorRelocalization` 和 `RelativeStartProgress` 现在携带：

- `estimate_kind`；
- `source_anchor_index`；
- `edge_hop_count`；
- source/target confidence；
- evidence update/age。

对 fresh、exactly-one-hop 的 `geometry_reconstructed` evidence：

- route hint 与 hint action 使用 source anchor 的 `bearing_trusted`；
- 单跳重建 confidence 可显式继承可信 source，而不再被坏 target 的 raw
  confidence 取 `min` 拉低；
- evidence 超过 25 update 或 hop count 不等于 1 时拒绝；
- derived distance 永远不能授权 forced stop；
- `vlm_stop_veto` 不允许被该 derived evidence 撤销。

同时状态机在 `current=trusted, next=strongly_untrusted` 时先保持 next identity，
使用可信 current 加固定 edge 重建 next，最多 12 assessments；不立即消耗
quarantine chain。预算耗尽才提出 active scan。

核心实现：

- [`code/reliability/v11_consumer_policy_v2.py`](code/reliability/v11_consumer_policy_v2.py)
- [`code/reliability/v11_integrated_anchor_state.py`](code/reliability/v11_integrated_anchor_state.py)
- [`configs/v11_integrated_anchor_state_recovery_shadow_v1.json`](configs/v11_integrated_anchor_state_recovery_shadow_v1.json)

### 3. Active scan 当前到什么程度

今天实现的是 default-closed scan plan，不是 motor executor：

- yaw offsets：`[-90,-60,-30,+30,+60,+90,0]`；
- angular velocity：30°/s；
- 总旋转路程 270°、理论 9 s；
- 最多一个 scan cycle；
- 每个方向都计划重新取样；
- motor rotation、translation 和 stop authority 全部为 false。

它已接入 integrated selector 的 shadow log，用于验证何时请求、选择哪些视角、
何时取消。50ep 中不会真的旋转机器人。真实执行前仍需独立批准，并至少实现：

1. 与 locomotion controller 的互斥和安全停稳；
2. 每个 yaw target 的到位判据与 timeout；
3. 新 observation 与旧 evidence 的 freshness 隔离；
4. 重新评分后连续可信确认；
5. scan 失败后的 safe hold；micro-translation 必须另行授权。

代码和策略：

- [`code/reliability/v11_active_scan_plan.py`](code/reliability/v11_active_scan_plan.py)
- [`configs/v11_active_scan_plan_shadow_v1.json`](configs/v11_active_scan_plan_shadow_v1.json)

## 验证

- focused integration tests：71 passed；
- full candidate tests：97 passed，1 failed；
- 唯一失败是此前已记录的缺失 fixture：
  `experiments/2026-07-23-prospective-results/prospective_v1_1.npz`；
- modified runtime modules：`py_compile` pass；
- 50ep runner：`bash -n` pass；
- frozen-artifact preflight：pass；
- out-of-scope `RUN_ONLY_EPISODE=999`：启动前拒绝。

测试快照位于 [`code/tests/`](code/tests/)，机器可读汇总位于
[`data/verification.json`](data/verification.json)。

## Route2 Active-50

用户在 2026-07-27 明确批准使用与 Route1 A/B 完全相同的固定 50ep cohort。
manifest 为 [`data/episodes.tsv`](data/episodes.tsv)，SHA256：

`5c31cf60c05e64f97e1842a5d9d36cf95484ac775f0b9a50bd3afc9b93dac957`

run tag：

`reliability_v11_route2_terminal_recovery_active50_20260727`

systemd unit：

`navila-route2-recovery-active50-20260727.service`

队列只有满足以下条件才启动 Route2：

1. 原 Route1 A/B master 已退出；
2. downgrade 与 diagnostic 两个 summary 各覆盖 exact 50ep 的全部终态；
3. Route1 master log 存在最终完成标志；
4. 没有任何 `round_trip_eval.py` 或 `vlm_server.py`；
5. GPU free memory ≥12000 MiB，并稳定 60 秒。

若 Route1 不完整结束，Route2 会以 exit 20 拒绝启动。Route2 对 invalid episode
最多重试一次，随后继续剩余 cohort；resume 时只跳过经过严格 completion
validator 的结果。

### 与当前对话完全解耦

2026-07-27 10:48 BST 验证：

- service `ActiveState=active`, `SubState=running`；
- MainPID=1836069；
- ControlGroup 属于 `user@1006.service/app.slice`；
- service parent 是用户级 systemd，不是 Codex shell；
- `loginctl` 显示 `Linger=yes`；
- 进程只有 queue shell 和 `sleep 60`，没有 Route2 VLM/Isaac child。

因此关闭本对话、终端或 SSH 连接不会取消队列。它不保证跨机器重启恢复；当前保证
的是脱离对话和登录 session。

冻结脚本：

- [`code/live_batch_scripts/run_recovery_active50.sh`](code/live_batch_scripts/run_recovery_active50.sh)
- [`code/live_batch_scripts/wait_for_route1_then_run.sh`](code/live_batch_scripts/wait_for_route1_then_run.sh)
- [`code/live_batch_scripts/validate_route1_handoff.py`](code/live_batch_scripts/validate_route1_handoff.py)

批准 artifact：

- [`configs/v11_consumer_policy_v2_recovery_active50_20260727.json`](configs/v11_consumer_policy_v2_recovery_active50_20260727.json)
- [`configs/v11_integrated_candidate_controller_active_v0_recovery50_approved_20260727.json`](configs/v11_integrated_candidate_controller_active_v0_recovery50_approved_20260727.json)

队列冻结时 Route1 downgrade=5/50、diagnostic=0/50，故 Route2 正确保持 waiting。
状态快照见 [`data/active50_queue_snapshot.json`](data/active50_queue_snapshot.json)。

## 关键 hash

| artifact | SHA256 |
|---|---|
| `round_trip_eval.py` | `baa24b746bdbaa6cee3d5434fe2adc7004f94ff90e349f7b4c8af0d309cdd51b` |
| `route_memory_agent.py` | `d1f1c5f924fd05e346ef9c027977046290f42539c124c0e37c1d407888184cb1` |
| `v11_consumer_policy_v2.py` | `b821ac1717abe94c0ccf22645d562a6fcc3967d2406798d762361b137bf3fde8` |
| `v11_integrated_anchor_state.py` | `23cea0bedaf69434a4aa0d7b6abe00d1a361b49a9eaa82764c2f623cf3462065` |
| `v11_active_scan_plan.py` | `1b98061049ed9b19271f572c1f1819204cba1046a94e603dbd88c43d46159d6f` |
| recovery state policy | `3024228d7db7aa1f267eb6f766698f5120b4b686a230396aa50729baec0197a3` |
| scan policy | `5991d7bbc3823f6db337ced840bb7e7cf8253ba1076c98710c7996842fa5d6f1` |
| consumer Active-50 policy | `eeb94179a5ca7a00df63e9ad9e0aa53bb366d762817ac51e87625500a044fd1e` |
| controller Active-50 approval | `37ce8e234bc9f665b7bbdd278978c06c7129013a77506cb5f19c13ea546f8930` |
| Active-50 runner | `3bca3e9a1c99ce508d6f834f888136c0411c79dc765f3391b25d07912c4953ea` |
| handoff validator | `ed52bcdc28cfeceb29c5b9a250daef0e2524d40cb4c8500966c739843ad49811` |

## 剩余风险

1. A0 descriptor 在 replay/单元层已接线，但尚无独立 live episode 只验证 A0
   matching quality。
2. ep205 证明了单跳重建方向准确，但不证明所有环境中的固定 edge 都可靠；因此
   当前严格限制为 fresh one-hop。
3. derived distance 不参与 forced stop，所以终点停止仍需要可信 raw evidence
   或后续独立 home evidence。
4. scan motor executor 尚未实现，不能把 shadow plan 写成“active scan 已完成”。
5. 当前 50ep 是单臂 prospective validation，不是与旧版本同时运行的严格 A/B；
   应按 episode 与既有 Route2/Route1 结果配对分析。
