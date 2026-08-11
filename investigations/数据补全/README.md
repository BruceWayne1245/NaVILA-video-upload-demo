# 数据补全 —— oracle_hint / oracle_hint_action 系列消融配置记录

**目的**：为论文补齐缺失的数据点，在 NaVILA(navila-llama3-8b-8f)这条主线上，针对同一份 100-episode canonical manifest（`run_pure_baseline_100ep_20260810.sh` 引入，`pure_navila_baseline_100ep_20260810`/`pure_oracle_hint_100ep_20260811` 均复用），逐步跑不同配置的 round-trip 批次。本文档记录 2026-08-11/12 这两天围绕 `oracle_hint` → `oracle_hint_action` 消融设计所做的调查和最终决定，重点是：**当前正在跑的 `pure_oracle_hint_100ep_20260811` 与 2026年6-7月产出"4.3%干预率、返程成功率50%→97%"结论的那批历史批次之间，配置到底差在哪，以及我们准备运行的下一批采纳了其中哪些设置**。

## 1. 当前正在跑的批次：`pure_oracle_hint_100ep_20260811`

脚本：`scripts/run_pure_oracle_hint_100ep_20260811.sh`（`RUN_TAG=pure_oracle_hint_100ep_20260811`）

核心 flag：
```
--round_trip_mode=phase_prompt --instruction_rewriter_provider=cache_only
--route_memory --route_hint_mode=compact --route_hint_source=oracle
--route_relocalization_backend=none
```

明确不开：
- `--stop_gate`：oracle hint 的 `relocalization_confidence` 恒为 1.0，`stop_gate.py` 的 `_extract_d_and_conf` 会把任何 oracle 来源的置信度视为满分，一旦距离连续 `confirm_steps` 次落在 `r_in` 内就会被 `FORCED` 路径直接判定返程成功——这样测出来的是 stop_gate 自己的判断，不是 VLM 自己的停止决策。
- `--oracle_align_return_yaw_to_anchor_segment`：会用 ground truth 直接改写机器人返程朝向，是比 hint 文本更强的一层 oracle 介入。
- `--hint_action_arbiter`：这是本篇要讨论的主角，故意留到下一批再加。

这批复现的是 2026-06-29 `direct_oracle_hard_fresh_20260629` 批次的 route-memory flag 组合（已核对该批次自己 eval_log 里的真实 argv），只是把测试集从原来的 hard-11 换成了本项目 7/20 起统一使用的 100-episode canonical set。

截至本文档撰写时批次仍在跑，最终 return-success 数字会在 `final_data/` 下按跟 `pure_navila_baseline_100ep_20260810` 相同的方法论汇总（分母 = outbound-success 集合，含跨批次历史成功的合并规则）。

## 2. "4.3%/97%"结论的真实来源（2026-06-30 / 07-01）

项目 README 里反复引用的"hint_action_arbiter 只在 4.3% 的返程决策上介入，却把返程成功率从约50%拉到97%"这个结论，来自两批加总的结果，**都是 NaVILA 本身跑的**，不是后来 08-08 拿来测试跨backbone泛化性的那批 StreamVLN 数据（那批是另一条独立支线，用的是完全不同的VLM/policy，不能跟本项目主线混着比）：

- `stop_gate_r3_hint_arbiter_hard11_20260630`：hard-11 集合，7/7
- `oracle_shadow_loftr_v4_30_return_anchor_fix_20260701`：30集，10/11

两者相加 17/18 = 94.4%（配合同期不开 hint_action_arbiter 的三批 14/28=50% 基线做对照）。30ep 那批 return 阶段一共 348 次决策，180 次已经跟 hint 一致、153 次被 clear-path 检查挡下，**只有15次真正替换了 VLM 输出，15/348≈4.31%≈4.3%**。

**真实 flag 组合**（直接从 `stop_gate_r3_hint_arbiter_hard11_20260630` 的 `ep368_eval.log` 里 `Passing the following args to the base kit application` 这行原始 argv 核对得到，不是凭记忆/文档推测）：

```
--route_memory --route_hint_mode=compact --route_hint_source=oracle
--route_relocalization_backend=none
--oracle_align_return_yaw_to_anchor_segment
--stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0
--stop_gate_confirm_steps=3 --stop_gate_min_confidence=0.5
--topdown_route_map
--hint_action_arbiter
```

30ep 那半（`run_oracle_shadow_loftr_v4_30_batch_20260701.sh`）唯一的差异是 `--route_relocalization_backend=loftr_depth`（而不是 none）——但因为 `route_hint_source=oracle`，真正喂给 VLM 的 hint 数值仍然来自 oracle，这个 backend 只是跑一份非oracle的LoFTR影子重定位做诊断记录（脚本自己的注释写的是"non-oracle LoFTR shadow telemetry"），不影响实际驱动机器人的信号，因此不算一个真正的配置差异。

**结论：历史上 `--hint_action_arbiter` 从未单独跑过**，每一个用到它的历史批次（逐个 grep 过所有同时含 `route_hint_source=oracle` 和 `hint_action_arbiter` 的脚本确认），都是跟 `--oracle_align_return_yaw_to_anchor_segment` + `--stop_gate`(+四个子参数) + `--topdown_route_map` 打包一起出现的。

## 3. 当前 `oracle_hint` 批次 vs 4.3%历史来源：完整差异表

| flag | pure_oracle_hint_100ep_20260811（当前正跑） | 4.3%/97%历史来源（06-30/07-01） | 功能说明 |
|---|---|---|---|
| `--route_hint_source=oracle` | 有 | 有 | 相同 |
| `--route_relocalization_backend` | none | none（hard11半）/ loftr_depth（30ep半，仅影子诊断，不影响驱动信号） | 基本相同 |
| `--hint_action_arbiter` | 无 | 有 | 返程时若 VLM 输出的方向与 route hint（记录路线上到下个锚点的方位角）方向性冲突、且 hint 方向经清路检查确认无障碍，就临时替换掉那一步的 VLM 输出（一次一步，不持续接管）|
| `--oracle_align_return_yaw_to_anchor_segment` | 无 | 有 | 直接用 ground truth 改写机器人返程朝向——是对机器人姿态本身的强oracle介入，跟 hint_action_arbiter 不是一回事 |
| `--stop_gate`(+r_in=3.0/r_out=3.0/confirm_steps=3/min_confidence=0.5) | 无 | 有 | 独立判断"什么时候该停/算不算返程成功"的仲裁机制，跟"往哪走"完全正交；oracle恒定置信度1.0会让它绕过VLM自己的停止决策直接判成功，这也是当前 `oracle_hint` 批次一开始就不开它的原因 |
| `--topdown_route_map` | 无 | 有 | 不是独立决策逻辑，只是给 hint_action_arbiter 自己已有的清路检查提供一个俯视地图作为备用数据源（优先用机器人自己的LiDAR局部地图，查不到才退回用这张图）|

## 4. 准备运行的下一批：`pure_oracle_hint_action_100ep_20260812`

脚本：`scripts/run_pure_oracle_hint_action_100ep_20260812.sh`（`RUN_TAG=pure_oracle_hint_action_100ep_20260812`），跟当前 `pure_oracle_hint_100ep_20260811` 逐行 diff 确认，eval 命令里只多了两行：

```diff
 --route_relocalization_backend=none \
+--topdown_route_map \
+--hint_action_arbiter \
```

**采纳**：`--hint_action_arbiter`（本批要测的核心机制）、`--topdown_route_map`（不是独立机制，只是让 arbiter 的清路检查数据源跟历史批次一样完整，避免因为地图数据缺失而低估 arbiter 的介入率）。

**明确不采纳**（用户 2026-08-12 复核后决定排除）：
- `--oracle_align_return_yaw_to_anchor_segment`——跟 hint_action_arbiter 不是同一类机制，混进来会让测不出 hint_action_arbiter 单独的贡献。
- `--stop_gate`（+四个子参数）——同样是独立机制，且历史上排除它的理由（oracle 恒定置信度会让 stop_gate 抢着自己判定成功）在这里同样成立。

**结论：这一批不能跟历史 4.3%/97% 数字直接比较**——它测的是"在当前 `oracle_hint` 基础上，只加 hint_action_arbiter（以及它自己需要的清路数据源）这一个机制，单独的效果是什么"，而不是复现历史上那套四件套打包配置。

同一份 100-episode canonical episode 列表跟 `pure_oracle_hint_100ep_20260811`/`pure_navila_baseline_100ep_20260810` 完全一致（逐行核对过）。

截至本文档撰写时，该批次尚未启动（当前 `pure_oracle_hint_100ep_20260811` 仍在运行，等它跑完释放 GPU 后再启动）。

## 5. 下下批计划：在此基础上再加 `--stop_gate`

2026-08-12 已确认的下一步计划：等 `pure_oracle_hint_action_100ep_20260812` 跑完，**在它的基础上再叠加一个变量 `--stop_gate`**（预计沿用历史配置的四个子参数：`--stop_gate_r_in=3.0 --stop_gate_r_out=3.0 --stop_gate_confirm_steps=3 --stop_gate_min_confidence=0.5`），也就是说三批将构成一条逐步叠加的消融链：

```
oracle_hint  →  oracle_hint_action(=oracle_hint + hint_action_arbiter + topdown_route_map)  →  oracle_hint_action + stop_gate
```

`--oracle_align_return_yaw_to_anchor_segment` 目前不在这条链的计划内，暂不添加。具体的第三批脚本/flag细节留到那时候再定，本节先记录已经确认的方向，供后续接手的人核对。

## 相关文件

- `scripts/run_pure_oracle_hint_100ep_20260811.sh`（当前正跑）
- `scripts/run_pure_oracle_hint_action_100ep_20260812.sh`（已准备好，未启动）
- `investigations/2026-08-11-pure-oracle-hint-100ep-and-stopgate-audit/README.md`（oracle_hint 批次的完整背景、stop_gate审计、hint文本机制对比）
- `code/run_pure_oracle_hint_100ep_20260811.sh`、`code/run_pure_oracle_hint_action_100ep_20260812.sh`（本文件夹内两份脚本快照，供对照）
