# 100ep批次(34.1%)难度调查 + Route2最好成绩核实 + 66%代码复现

Date: 2026-08-16

## 起因

`line2_v11veto_turngate_trendconf_100ep_20260815`批次跑完，round_trip_success=29/85=**34.1%**，明显低于用户记忆中"50ep拿到50%多"、"30ep拿到70%"的历史结果。用户怀疑是当前这批用的100ep manifest本身更难。

## 结论：不是episode难度问题，是配置/代码差异

### 1. manifest的"high success"标签只描述outbound，跟round-trip无关

`run_pure_oracle_hint_highsuccess100ep_20260811.sh`的注释里写明：这100集是按**历史outbound成功率**（聚合94.85%）选出来的top 100，明确注明"NOT the 7/20 canonical-100 set"，从未声称round-trip容易。

### 2. 客观路线长度：当前manifest反而更短

用`anchor_labels.json`（本session早些时候为anchor质量建模而汇总的、跨93个历史批次池化的真实距离数据）里每个episode的`distance_from_start_m`最大值做路线长度代理：

| 集合 | n | 路线长度中位数 |
|---|---|---|
| 当前100ep manifest | 96/100有数据 | 9.75m |
| 50ep(55.6%)批次 | 47/50 | 11.25m |
| 30ep(08-04, 70%)批次 | 22/30 | 11.75m |

当前集合的路线**更短**，不是更长。

### 3. 决定性证据：同一批episode，不同批次表现天差地别

当前100ep批次跟50ep(`reliability_v11_policy_v2_active_50ep_outbound_top_20260725`)批次重叠35集（29集双方outbound都成功）：

- 当前批次在这29集上：**24%**(7/29)
- 50ep批次在**同样这29集**上：**66%**(19/29)

同一批episode，一次66%一次24%，episode难度不可能是原因。跟30ep(08-04)批次重叠7集也是同方向：43% vs 57%。

### 4. 同一份manifest，换配置跑出27%~82%

| 批次 | 配置要点 | round-trip |
|---|---|---|
| pure_oracle_hint | oracle提示，无action | 37.2% |
| pure_oracle_hint_action | +action override | 60.5% |
| pure_oracle_hint_action_stopgate | +stop_gate | **81.6%** |
| line2_stopgate_redesign_no_yaw_align | 纯自驱动ICP，无yaw矫正 | 27.3% |
| **line2_v11veto_turngate_trendconf**(当前这批) | 纯自驱动ICP + 3个新fix(含已知有害的trend_confidence) | 34.1% |

### 5. 66%批次的真实配置差异

抓取两批的完整启动参数逐项diff，发现66%那批(`reliability_v11_policy_v2_active_50ep_outbound_top_20260725`)：

- 跑的是**完全不同的代码分支**：`/home/teambruce/navila-reliability-v1_1-policy-v2-active50-20260725/policy_v2_live_candidate/scripts/round_trip_eval.py`，Route2自己独立维护的候选代码，不是主仓库这一份。
- 带`--oracle_align_return_yaw_to_anchor_segment`（oracle级返程朝向矫正），当前批次**完全没有任何yaw矫正**。
- 决策机制是Route2的Policy V2 active控制器（`--reliability_v11_consumer_mode=active`，学习模型主动接管promote/quarantine决策），当前批次是纯手工heuristic门槛。
- 当前批次额外带了一堆08-03到08-15陆续加的新机制（current_evict窗口化、stop_veto、trend_confidence[已知有害]、v11_quarantine_veto、vision_disagreement downgrade等），66%那批都没有。

**结论**：34.1% vs 66%的差距主要是机制配置差距（尤其是有无yaw矫正 + 有无Route2主动学习控制器），不是同一套系统的运气问题，更不是episode难度问题。

## Route2历史最好成绩核实

用户记得Route2应该有比55.6%更高的成绩。逐一核查：

- **"60.0%(18/30)"**（`investigations/2026-07-26-v2-integrated-anchor-state/README.md`）——是同一个50ep批次在ep687冻结点做的**中期快照**（当时只有30个outbound成功，最终跑完是36个）。等这批完整跑完，20/36=55.6%，不是两个独立成绩。
- **"66.7%(10/15)"**（`anchor_v2_full_active_batch49_20260802`）——论文汇总表(`RETURN_SUCCESS_SUMMARY.md`)自己写明这是"actual/geometric return success"，**严格口径下的评测结果只有7/15=46.7%**，比55.6%还差。
- **全项目Route2相关批次普查**（严格round_trip_success/outbound_success口径，样本量≥15）：

| 批次 | outbound | round_trip | 严格成功率 |
|---|---|---|---|
| policy_v2_active_50ep_outbound_top_20260725 | 36 | 20 | **55.6%** |
| route2_terminal_recovery_active50_20260727 | 39 | 21 | 53.8% |
| anchor_v2_full_active_batch49_20260802 | 15 | 7 | 46.7% |
| route2_anchorv2_terminal_collection50_20260801_batch49 | 21 | 9 | 42.9% |
| anchor_v2_full_active_recoveryfix30/semanticfix30 | 20 | 6 | 30.0% |

**结论**：同一套一致口径下，55.6%确实是Route2所有正式批次里最高的一个。

## 66%代码的完整性验证

原始路径`/home/teambruce/navila-reliability-v1_1-policy-v2-active50-20260725`已在08-12的home目录清理里被整体搬到归档区，未被删除或覆盖：

- 新位置：`/home/teambruce/navila_archive/staging_dirs/navila-reliability-v1_1-policy-v2-active50-20260725/`
- 代码自包含：`round_trip_eval.py`本地import `route_memory_agent.py`/`relocalization.py`/`hint_action_arbiter.py`/`stop_gate.py`/`stuck_recovery.py`，都在同目录下，不依赖主仓库的共享模块（字节级diff确认这几个模块跟主仓库现在的版本完全不同，证明是独立冻结的快照）。
- mtime检查：目录内所有源码文件最后修改时间都在2026-07-25或更早，之后再无改动（排除pytest_cache等运行时产物）。
- 复用检查：项目全部batch_logs里，只有这一批自己引用过这个路径作为`--reliability_v11_runtime_root`，从未被后续批次复用/原地修改——Route2的工作方式是"每轮开一个新的带日期目录"，不是原地迭代，这正是这份代码能完整保留下来的原因。
- 早先误判：曾错误地说"这个目录本身是独立git仓库"——实际上目录内没有`.git`，`git status`是walk-up到了`/home/teambruce`本身（一个无关的BRUCE机器人项目仓库）。已纠正：这只是一份纯文件快照，没有commit级别的历史，但上述mtime+复用检查已经足够确认完整性。

## KD-tree ICP加速——已验证不完全等价，复现批次里保留原始暴力实现

主仓库`relocalization.py`的`_nearest_neighbor_2d`在08-15换成了`scipy.spatial.cKDTree`（O(N log M)代替O(N×M)暴力搜索），66%那份归档代码里还是原始暴力版本。

- 单次ICP耗时~135ms，跟目标距离基本无关（24种子×16迭代的固定计算量）。
- 用ep4的11个真实anchor点云互相配准（110组）做实测：两种实现在**110组里22个点的最近邻index选择不同**，但这些分歧点上两者算出的距离值几乎完全相同(差距~1e-6)——是真实的"平局"情况下tie-breaking策略不同，不是精度bug。这类平局集中出现在走廊退化/重复结构这类本项目一直在关注的高歧义场景。
- **决定**：这次复现批次为了保持跟当年一模一样、排除额外变量，**不引入KD-tree**，继续用原始暴力实现（唯一代价是运行更慢，不影响结果的可比性）。

## 已launch的复现批次

用66%原始代码（`policy_v2_live_candidate`分支）+ 完全一致的flag集合（仅`reliability_v11_runtime_root`等4个路径重定向到归档新位置），跑当前100ep high-success manifest的全部100集。

- systemd unit: `navila-policyv2-highsuccess100ep-20260816`（`systemctl --user status`查看），已启用linger，可扛住session断线。
- 输出目录: `batch_logs/policy_v2_active50_replay_on_highsuccess100ep_20260816/`
- 状态：**进行中**，预计15-25小时（参照当年50ep批次单集15-45分钟的真实历史耗时）。
- 目的：得到"66%那份代码在完整100ep manifest上的真实round-trip成功率"，可以直接跟当前批次的34.1%、以及manifest上其他历史配置（27%-82%区间）做对照。
