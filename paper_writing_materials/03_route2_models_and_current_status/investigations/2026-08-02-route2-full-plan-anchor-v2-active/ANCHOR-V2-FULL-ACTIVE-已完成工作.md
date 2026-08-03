# Anchor V2 full-active：已完成工作记录

日期：2026-08-02

本文只记录本次已完成的 Anchor V2 full-active 实现、验证和当前限制；长期路线以同目录的《【重点】Route 2 完整系统改进方案》为准。

## 已实现

- 新增独立 `AnchorTransitionControllerV2`，不再把旧的 bounded promotion guard 冒充 full-active。
- 模型类别为 `advance_one`、`hold`、`rebase`、`rollback`、`skip_or_rebase`。这些类别是相对于 observed next candidate 的 correction，不是盲目的绝对 index 指令。
- `full_active` 下 legacy heuristic 只作为 counterfactual telemetry；正常低置信度、stale、pose-untrusted、pair mismatch 和 OOD 路径不会 fail-open。
- V1.1 pose trust、候选拓扑、artifact/schema 和 head-authority firewall 已接入；紧急 kill-switch 是唯一允许 legacy fallback 的路径。
- 保持因果时序：完整的 attempt `t` 只能影响 `t+1`，不能影响产生该特征的同一 attempt。
- 增加 bounded recovery、long-hold、candidate exhaustion、oscillation protection 和依赖失败出口。
- 增加静态 preflight canary launcher；必须同时显式传入 launch arm 和环境批准变量才会启动 episode。默认使用 3600 秒超时，未实际排队 live episode。

## 固定 artifact 与代码位置

- Runtime：`/home/teambruce/navila-route2-v11-core-20260801`
- Controller：`anchor_transition_runtime/full_active_controller.py`
- Runtime wiring：`runtime_candidate/scripts/round_trip_eval.py`、`runtime_candidate/scripts/route_memory_agent.py`
- Frozen model：`models/core_v2/anchor_transition_v2_robust.joblib`
- SHA-256：`461577a982e3cd4a551e321741cb21bf5b0ac167d83252e67fb6d8cd5877a9cd`

## 验证结果

- 完整本地测试：`101/101 passed`。
- 校准阈值只用 EU6 validation 选择：progress `0.60`、recovery `0.70`、一次完整 causal observation、12-attempt unconfirmed-hold budget。
- EU6 validation：promotion precision `0.9971`、recall `0.3917`、promotion rate `0.3575`。
- x8 test：precision `0.9850`、recall `0.5524`、promotion rate `0.4255`。
- locked20（阈值冻结后才评估）：16/20 可评分；precision `0.9969`、recall `0.3691`、specificity `0.9751`、promotion rate `0.3538`。

locked20 的 5 条 weighted false-promotion rows 全部集中于 ep304 的 A5→A4 连续 dwell（attempts 278–280、282–283）。这应作为 live active recovery watch case，而不是事后污染 locked threshold 的理由。

## 当前边界

实现、测试、causal replay、报告和 launcher 已完成；新的 live cohort 尚未启动。下一步只能先以 Anchor V2 active 为单一变量做 wiring/prospective canary，观察 return 成功率、恢复和数据完整性；确认稳定后才进入 TRB，再后续处理 Hint 和 Terminal。

