# 2026-07-22 目前最佳结果 —— fix-ON A+B+C 基线, 真值 return 63%

本文件记录截至 2026-07-22 的**当前最佳往返(round-trip)结果**: `reliability_fixon_100ep_20260721_accumulated`
批次(2026-07-21 启动、successfirst 排序、2026-07-22 从 ep5 RESUME、跑到 73 集后为腾 GPU 手动停止)
在**全部 19 个 outbound-success 集**上的**真值 return 成功率 = 12/19 ≈ 63%**(含 1 个 near-miss 则 13/19 ≈ 68%)。

> 这是**新改动之前**的基线配置: `--reliability_quarantine_shared_trend_budget` 与 `--stuck_recovery`
> 两个 flag **均未开启**(它们 2026-07-22 才加入代码, 默认关闭)。因此本结果可在今天的 live 代码上
> 通过"用下方 flag 组合、不加那两个新 flag"**逐字节复现**。

---

## 0. TL;DR

| 指标 | 结果 |
|---|---|
| 批次 | `reliability_fixon_100ep_20260721_accumulated` (停在 73 集) |
| exit_code=98 (VLM 启动失败, 基础设施) | 7 |
| 可判集 (非-98) | 66 |
| **outbound 成功率** | 19/66 ≈ **29%** |
| **真值 return 成功率** | **12/19 ≈ 63%** (严格判停 <3m); 含 near-miss 13/19 ≈ 68% |
| self-report (summary.tsv `round_trip_success`) | 仅 11 —— **偏低, 勿用** |

真值口径: 从每集 trajectory 的**真实世界坐标**计算 return 结束时机器人到真实起点(step0)的距离,
`< success_radius = 3.0m` 记成功。**不使用** summary/measurement 里的 `distance_to_start` 字段
(该字段大量未落盘写成 0.0, 且末帧常被下一集 reset 帧污染 —— 见第 5 节方法论)。

---

## 1. 结果总览

- 19 个 outbound-success 集全部有 trajectory(本批无 capture-crash 丢文件)。
- **SUCCESS 12**: 4, 88, 89, 368, 500, 589, 647, 680, 708, 813*, 1038, 1040
  (*813 到家 min 0.25m 但未主动判停, REACHED-NOSTOP, 按真值到家计入成功)
- **NEAR-MISS 1**: 367 (停在 3.09m)
- **FAIL 6**: 5, 134, 187, 491, 669, 678

这个 12 与 2026-07-22 investigation 里记录的 "≈12/20=60%" 完全对应, 数字稳健。

---

## 2. 完整配置 (flag 组合)

`--route_hint_source=integrated`, `--route_relocalization_backend=sequential_pair`,
`--oracle_align_return_yaw_to_anchor_segment` 之外, 完整 `EXTRA_ISAAC_ARGS`:

```
--route_relocalization_interval_updates=5
--stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0
--topdown_route_map --hint_action_arbiter
--hint_arbiter_min_relocalization_confidence=0.90
--sequential_pair_quarantine --sequential_pair_quarantine_mode=trend
--route_local_map_icp_objective=point_to_point
--route_local_map_voxel_size_m=0.10
--route_local_map_max_points=512
--route_local_map_profile=default
--route_local_map_quality_policy=diagnostic
--sequential_pair_promotion_mode=bounded_evidence
--sequential_pair_promotion_window=5
--sequential_pair_promotion_min_votes=3
--sequential_pair_promotion_alias_aware
--sequential_pair_promotion_alias_threshold=0.6
--sequential_pair_promotion_alias_window=8
--sequential_pair_promotion_alias_min_votes=5
--sequential_pair_promotion_alias_stall_attempts=200
--sequential_pair_promotion_use_pre_closure_estimates
--sequential_pair_short_baseline_disambiguation
--sequential_pair_short_baseline_min_travel_m=0.3
--sequential_pair_short_baseline_max_rotation_disagreement_deg=20.0
--sequential_pair_disable_temporal_smoothing
--sequential_pair_closure_check
--sequential_pair_closure_reconciliation_signal=bearing
--sequential_pair_report_next_anchor
--sequential_pair_report_next_anchor_suppress_if_stale
--stop_gate_anchor_corroboration --stop_gate_forced_anchor_confirm_steps=2
--sequential_pair_anchor_geometry_source=accumulated
--capture_icp_replay_dataset
--sequential_pair_reliability_quarantine --reliability_quarantine_threshold=2.5
--sequential_pair_reliability_demote_current
--sequential_pair_reliability_distrust_downstream
```

**与今天(2026-07-22 v11 shadow)批次的唯一 config 差异** —— 今天在以上基础上**多开**了:
- `--reliability_quarantine_shared_trend_budget` (2026-07-22 新增, 默认关)
- `--stuck_recovery` (+ 其子参数, 2026-07-22 新增, 默认关)

`closure_mode` 保持 `threshold` (默认), `belief`/`trust_aware_guard` 未开。

---

## 3. 运行指令

两段式启动(successfirst 优先跑 batch2 的 27 个 outbound-success 集, 再跑其余 73; 次日从 ep5 RESUME):

- launcher: `run_reliability_fixon_100ep_successfirst_20260721.sh` (原文见同目录)
- resume:   `run_reliability_fixon_100ep_RESUME_from_ep5_20260722.sh` (原文见同目录)
- 底层驱动: `NaVILA-Bench/scripts/run_oracle_anchor_100ep_batch_20260720.sh`

核心调用(每 phase):
```bash
RUN_TAG="reliability_fixon_100ep_20260721_accumulated" \
PORT_BASE=55321 \
ROUTE_HINT_SOURCE=integrated \
ROUTE_RELOCALIZATION_BACKEND=sequential_pair \
ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT=1 \
ONLY_EPISODES="<episode list>" \
EXTRA_ISAAC_ARGS="<第 2 节的完整 flag>" \
bash scripts/run_oracle_anchor_100ep_batch_20260720.sh
```

---

## 4. 代码状态 (以开关形式记录)

昨天(本批运行时)与今天(live)的代码差异**仅为两个默认关闭的开关**, 关闭时行为逐字节一致
(2026-07-22 CODE_CHANGES 已验证 309 tests / 0 regressions)。因此本结果不依赖某个已被覆盖的代码快照。

| 文件 | 昨天(premerge, 本批) sha256(前16) | 今天(live) sha256(前16) | 差异 |
|---|---|---|---|
| `round_trip_eval.py` | `a9e42b5441f5a445` | `7941f9a9611c11c1` | +`--stuck_recovery` 集成(默认关) |
| `route_memory_agent.py` | `fe37b7117087ea5d` | `1e6af8cef24b2743` | +`--reliability_quarantine_shared_trend_budget`(默认关) |
| `relocalization.py` | `226a87b68d5727982` (未变) | `226a87b68d5727982` | 无 |
| `stop_gate.py` | `0c37014abdc4bc4a` (未变) | `0c37014abdc4bc4a` | 无 |
| `stuck_recovery.py` | 不存在 | `a23cfc6c18816eb8` | 今天新增模块(默认关) |

premerge 备份: `navila-gating-ab-v1/live_backup_premerge_20260722_stuckrecovery/`。

**复现方法**: 在今天的 live 代码上, 用第 2 节 flag 组合、**不加**那两个新 flag, 即等价于本批配置。

---

## 5. 逐集真值明细

完整数据见同目录 `per_episode_truth.tsv`。列说明: `true_final_d2s`=return 末帧真值到起点距离;
`true_min_d2s`=return 全程最近距起点; `believed_end`=控制器自认的最终距离; `track_err`=真值−believed
(正=以为比实际近, 有早停风险); `stop_decision`=stop_gate 末次决策。

| ep | scene | wp | 判定 | true_final | true_min | believed | track_err | stop_decision | 根因 |
|---|---|---|---|---|---|---|---|---|---|
| 4 | x8F5xyU | 5 | SUCCESS | 1.47 | 1.47 | 2.81 | -1.34 | forced@c0.20 | ok |
| 5 | x8F5xyU | 5 | **FAIL** | 9.47 | 9.44 | 12.51 | -3.04 | pass@c0.58 | 物理楔死 (68% cmd-fwd/speed≈0) |
| 88 | EU6Fwq7 | 5 | SUCCESS | 2.77 | 2.28 | 2.93 | -0.17 | forced@c0.77 | ok |
| 89 | EU6Fwq7 | 5 | SUCCESS | 2.76 | 2.15 | 2.58 | 0.18 | forced@c0.76 | ok |
| 134 | 2azQ1b9 | 7 | **FAIL** | 7.15 | 6.92 | 3.19 | 3.96 | pass@c0.69 | reloc-conf 崩溃/没导回家 (141 low-conf gate) |
| 187 | EU6Fwq7 | 6 | **FAIL** | 8.26 | 8.19 | 4.62 | 3.64 | pass@c0.20 | 物理楔死 (73%) |
| 367 | X7HyMhZ | 7 | NEAR-MISS | 3.08 | 3.08 | 6.53 | -3.45 | deferred@c0.20 | 差一点 (~3.1m) |
| 368 | X7HyMhZ | 7 | SUCCESS | 1.33 | 1.33 | 4.23 | -2.90 | deferred@c0.20 | ok |
| 491 | X7HyMhZ | 6 | **FAIL** | 6.70 | 3.71 | 10.25 | -3.55 | pass@c0.80 | reloc-conf 崩溃/没导回家 (82 low-conf) |
| 500 | zsNo4HB | 4 | SUCCESS | 2.82 | 2.82 | 2.82 | -0.00 | forced@c0.20 | ok |
| 589 | QUCTc6B | 5 | SUCCESS | 2.43 | 2.43 | 2.99 | -0.55 | forced@c1.00 | ok |
| 647 | x8F5xyU | 4 | SUCCESS | 1.50 | 1.50 | 2.67 | -1.18 | forced@c0.47 | ok |
| 669 | X7HyMhZ | 5 | **FAIL** | 4.60 | 3.00 | 1.42 | 3.18 | forced@c0.74 | confidently-wrong 骗停 (believed 1.42≪true 4.60) |
| 678 | zsNo4HB | 7 | **FAIL** | 11.30 | 6.76 | 11.01 | 0.28 | deferred@c0.20 | reloc-conf 崩溃/没导回家 |
| 680 | zsNo4HB | 7 | SUCCESS | 1.45 | 1.45 | 8.90 | -7.45 | deferred@c0.20 | ok |
| 708 | QUCTc6B | 5 | SUCCESS | 0.24 | 0.00 | 4.97 | -4.73 | deferred@c0.20 | ok |
| 813 | x8F5xyU | 4 | SUCCESS* | 0.31 | 0.25 | 7.97 | -7.66 | pass@c0.20 | 到家未主动停 (REACHED-NOSTOP) |
| 1038 | X7HyMhZ | 7 | SUCCESS | 0.82 | 0.82 | 4.25 | -3.43 | deferred@c0.20 | ok |
| 1040 | X7HyMhZ | 7 | SUCCESS | 2.54 | 2.54 | 2.55 | -0.01 | forced@c0.79 | ok |

### 6 个 FAIL 的根因归类 (全部为既有老问题, 对应 2026-07-22 taxonomy)
- **物理楔死 (control/wall)**: ep5, ep187 —— cmd 前进但实际 speed≈0, 机器人卡死墙角。
- **reloc-conf 崩溃 / 没能导回家**: ep134, ep491, ep678 —— 置信度崩到 0.2, 机器人从未被导到起点附近。
- **confidently-wrong 骗停**: ep669 —— believed 1.42m 触发 forced stop, 真值 4.60m。

注意成功集大量是靠 `stop_gate` 的 **forced / deferred**(anchor-corroboration)兜底, 很多 believed 与真值
差很大(如 680 believed 8.9/真值 1.45)却仍成功 —— 与 2026-07-22 结论一致: 是分层冗余(bearing 重建 +
arbiter + stop_gate anchor 兜底)在扛成功率, 不是单一 anchor 身份追准了。

---

## 6. 真值计算方法论 (务必遵循, 勿被 summary 骗)

1. **起点** = trajectory `output_*.jsonl` 的 step0 `position`(outbound 起点 = return 目标)。
2. **return 末帧真值** = phase=='return' 的最后一帧 `position` 到起点距离; 若最后一帧相对前帧
   跳变 >1.0m 且 speed≈0, 是**下一集 reset 污染帧**, 剔除。
3. **判停位置** = measurement `round_trip.stop_events` 里 phase=='return' 那条的 `position` 真值距离。
4. **绝不使用** `summary.tsv` 的 `distance_to_start` 列 / measurement `round_trip.distance_to_start`
   字段 —— 大量未落盘写成 0.0(成功集有时是准的, 失败/崩溃集常为 0.0)。
5. **崩溃/未进 return 集**要单列: 若 trajectory 只有 outbound+confirm 没有 return phase,
   且 eval log 结尾是 Isaac `Shutting Down`+mesh corruption, 属 confirm 阶段崩溃 → 排除, 非 return 失败。

---

## 7. 与其他批次对照 (真值同口径)

| 批次 | 新改动 | episode 集 | outbound 率 | 真值 return |
|---|---|---|---|---|
| **本批 fix-ON (73 集)** | OFF | successfirst 难集白名单 | 19/66=29% | **12/19 = 63%** (+near 68%) |
| 今天 v11 shadow (进行中) | ON | 全新随机 100 | ≈44% | 10/23≈43% (+near 57%) 截至快照 |

**两批 episode 集完全不同、非配对、样本小**, 不能据此判断新改动优劣。逐集根因显示今天的失败同为
老问题(confidently-wrong / 楔死 / tracking 漂移), 新改动 stuck_recovery/trend_budget do-no-harm
(成功集零触发、零误伤)。干净的因果判断需要**同一批 episode 上的 fix-OFF vs fix-ON+新改动 配对 A/B**。
