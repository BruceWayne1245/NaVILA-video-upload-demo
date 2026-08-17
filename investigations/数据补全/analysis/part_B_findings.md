# Part B 日志统计结果

**执行时间**：2026-08-17。**方法**：全部基于原始日志/measurement JSON 重新计算，不采信任何既有文档的数字（含本项目自己的 README/memory），仅在下方明确注明处引用既有文档作为交叉核对。

## 运行目录映射（本次核实，均已用 checklist 里给出的数字核对过 outbound/return 计数）

| 逻辑名 | 实际目录 | outbound_success | return_success | round_trip_success |
|---|---|---|---|---|
| `oracle_hint` | `pure_oracle_hint_highsuccess100ep_20260811` | 86 | 32 | 32 |
| `oracle_hint_action` | `pure_oracle_hint_action_highsuccess100ep_20260812` | 86→**实为87**（见B3） | 52 | 52 |
| `oracle_hint_action_stop` | `pure_oracle_hint_action_stopgate_highsuccess100ep_20260813` | 87 | 73 | 71 |
| canonical-100 交叉验证批（B8） | `pure_oracle_hint_action_100ep_20260812` | 37/98（未跑满） | — | — |
| `language_only` | `pure_navila_baseline_100ep_20260810` | — | — | — |

`language_only` 核实：`ep1035_eval.log:1` 的 argv 只有 `--task/--num_envs/--history_length/--load_run/--headless/--enable_cameras/--round_trip_mode=phase_prompt/--instruction_rewriter_provider=cache_only/--vlm_port/--episode_idx/--result_suffix`——**没有** `--route_memory`、`--route_hint_source`、`--hint_action_arbiter` 任何一个，确认是纯 NaVILA 基线，无外部记忆/hint。

---

## B1. 配对容差统计

**脚本**：`analysis/b1_pairing_tolerance.py`
**数据源**：`vlnce_assets/vln_ce_isaac_v1.json.gz`（1077 episodes）+ `code/high_outbound_success_100ep_selection.tsv`（100对）
**输出**：`analysis/b1_pairing_distances.csv`

| 量 | mean | std | median | min | max |
|---|---|---|---|---|---|
| d_start = \|\|P_ret[-1] - P_out[0]\|\| | 1.7695 | 1.4334 | 1.8226 | 0.0000 | **5.5222** |
| d_goal = \|\|P_ret[0] - P_out[-1]\|\| | 1.7198 | 1.5928 | 1.5182 | 0.0000 | **7.0231** |

- d_start > 1.0m：**70/100**
- d_start > 2.0m：**43/100**
- d_start 最大的 5 对：episode_id=494(idx304,neighbor262) 5.522m；314(idx205,neighbor1372) 4.796m；868(idx498,neighbor352) 4.764m；286(idx189,neighbor1189) 4.198m；500(idx310,neighbor1351) 4.070m
- 直方图（0-0.25/0.25-0.5/0.5-0.75/0.75-1.0/1.0-1.5/1.5-2.0/2.0-3.0/3.0-5.0/5.0+）：25/5/0/0/15/12/21/21/1

**⚠️ 需要在论文里正面处理的问题**：43% 的配对残余偏移 > 2.0m，是 3.0m 成功半径的 2/3——`d_start` 本身并非可忽略的噪声下限，最大值 5.52m 甚至超过成功半径。这不是"排除平凡解释"能轻描淡写带过的量级，需要论文明确讨论或者对这批 pair 做筛选。

**配对生成代码**（`NaVILA-Bench/scripts/instruction_rewriter.py:289-376`，函数 `_ordered_path_match` + `_find_reverse_path_neighbor`）：
- **τ_pair**：变量名 `tolerance_m`（函数参数），默认值 **2.0m**（`_find_reverse_path_neighbor` 签名 `tolerance_m: float = 2.0`，第332行；`InstructionRewriter.__init__` 里对应参数名 `neighbor_tolerance_m`，同为2.0，第398行）
- **判据**：**不是** Hausdorff 距离，也不是共享 waypoint 计数，而是**有序贪心最近邻逐点匹配**（`_ordered_path_match`，第289-313行）：对 candidate_path 里每个点，在 target_path 中从上次匹配位置往后找最近点，若距离 ≤ tolerance_m 则计入匹配并推进游标（保证顺序单调）。额外要求：`matched >= max(2, min(len(candidate),len(target))-1)` 且 `coverage = matched/min(len) >= 0.8`（第356-358行）。
- **候选池**：checklist 提到的"264"我们**没有在代码或本次数据里找到**直接对应字段——`_find_reverse_path_neighbor` 是逐 episode 现算，不维护候选池计数器；`README.md`(数据补全) 第6节提到的"264个有历史数据的episode_id"是另一件事（后续挑高成功率100集时的历史尝试统计，与本函数的配对逻辑无关）。**状态：NOT FOUND**（264 这个数字的来源），已搜索：`instruction_rewriter.py`全文、`round_trip_eval.py`全文 grep `264`、`reference_path`。

---

## B2. 失败幅度证据（oracle_hint，54例 return 失败）

**脚本**：`analysis/b2_failure_magnitude.py`，**输出**：`analysis/b2_failure_magnitude.csv`
**样本**：outbound_success=86 中 return_success=False 的 54 例（54/54 measurement JSON 均可读，无缺失）

**d_e（终点到起点距离）**：
- median=5.687m，Q1=3.917m，Q3=7.742m，min=0.000m，max=16.527m
- d_e>5m：35/54 = **64.8%**
- d_e>10m：7/54 = **13.0%**
- 最大5例：ep738(id1264) 16.527m；ep463(id785) 14.882m；ep86(id126) 13.040m；ep733(id1256) 12.768m；ep479(id810) 11.401m

**d_min_e（return全程到起点s0的最小距离，取 trajectory jsonl 里 phase=='return' 各步 `distance_to_start_m` 的最小值，54/54全部可算）**：
- median=3.838m，Q1=2.541m，Q3=6.041m，min=0.000m，max=13.691m
- d_min_e ≤ 3.0m（曾进入成功区又离开）：**17/54**，episode_id列表：129,314,128,512,1644,1643,1154,1439,1517,1368,361,494,718,720,978,1256,719
- d_min_e > 3.0m（全程未接近）：**37/54**
- 曾进入组 d_e 中位数：3.873m；从未接近组 d_e 中位数：6.248m（两组分化明显，"曾进入又离开"组的最终偏离显著更小，符合直觉）

**"终止于成功区内但仍判失败"**：checklist 预期2例，**实测为3例**（差异，请核实手稿数字）：
| episode | d_e | d_min_e | return阶段是否发出STOP | success_requires_stop |
|---|---|---|---|---|
| ep844 (id1439) | 1.981m | 1.957m | **否** | True |
| ep304 (id494) | 0.000m | 0.000m | **否** | True |
| ep427 (id719) | 2.636m | 2.261m | **否** | True |

三例失败原因一致：**几何上进入了成功半径，但return阶段从未发出STOP文本**（`round_trip.success_requires_stop=True` 时这类episode被判定失败）。

---

## B3. 分母口径核对（87 vs 86）——**根因已定位，且是一个真实的数据完整性bug**

**方法**：对比 `oracle_hint_action` 全部87个产生过 `[hint_arbiter]` 日志的 episode，与 summary.tsv 中 `outbound_success=="True"` 的86个 episode 的差集。

- 差集：**episode_idx=367** 出现在arbiter日志集合里，但不在outbound_success集合里
- `summary.tsv` 该行核实：`367 602 X7HyMhZNoso 1038 1759 7 0.0 6.916351 54688 2026-08-12T14:38:01 2026-08-12T14:41:31 0 ..._ep367 <vlm_log> <eval_log>` ——**后面的 measurement_file/outbound_success/return_success/round_trip_success/distance_to_start 字段全部为空**（exit_code=0，进程正常退出）
- `ep367_eval.log` 尾部：`[MEASUREMENT_WRITE_OK] wrote .../measurements/601.json`——测量文件**确实被写入了**
- 但 `measurements/601.json` 用 `json.load` 打开报错：`JSONDecodeError: Expecting ',' delimiter: line 4778 column 27 (char 215660)`，损坏点附近内容是 `... "max": 256.0\n }}"rear_camera_position_w": {...`——**两段JSON片段被错误拼接**（疑似写入时的竞态/缓冲区问题）
- 用纯文本 grep（绕过JSON解析）从损坏文件里直接抠出关键字段：`"outbound_success": true`、`"return_success": true`、`"round_trip_success": true`、`"distance_to_start": 1.333...`——**该episode实际是round_trip_success=true！**

**结论**：87 vs 86 的差异**不是**"outbound失败但仍产生仲裁记录"，也不是重复计数，而是**批次驱动脚本读取 summary 行时因 JSON 写入损坏而静默留空**，导致一个真实成功的 episode 从统计里丢失。**修正后的 oracle_hint_action outbound_success 应为 87（不是86），round_trip_success 应为 53（不是52）**。这会连带影响 B6 里所有基于"86"计算的百分比。

**⚠️ 项目范围内的潜在系统性问题**：同样的 `JSONDecodeError: Expecting ',' delimiter` 模式，在完全不同的一次运行（08-16 的 `tiered_v4_quarantinefix` 离线回放，ep889/ep1040，与本次调查的 `pure_oracle_hint_action_highsuccess100ep_20260812` 运行代码、运行时间都无关）中也出现过——提示这可能是 measurement JSON 写入路径上一个尚未根因排查的、偶发但跨批次重现的损坏bug，而不是单次意外。建议后续开一个独立investigation专门查这个。

---

## B4. STOP步在仲裁器日志中的落点

**脚本**：`analysis/b4_stop_step_arbiter.py`
**结果（oracle_hint_action，87个episode）**：
- Return阶段 `a_VLM==STOP`（日志文本 `I think I should stop because I have finished the instruction.`）总步数：**67**
- 67条**全部**同时出现在同一 step 的 arbiter decision 记录里（100%覆盖，与A7"STOP必进入仲裁器判定流程"一致，若"进入判定"指仲裁器会对该step打一行日志的话）
- reason code 分布：`target_too_close` 26次，`occupied_in_local_map_path` 41次；**0次**落在 `vlm_conflicts_with_clear_hint`（即override类reason）
- "模型提出STOP，最终执行的动作却不是STOP"的步数：**0**（67例的 `Vel Command` 全部是 `[0,0,0], Env Steps to go: 0`）

**结论**：本次日志实测**强烈支持**STOP从未被仲裁器覆盖为移动动作——但要注意，这只是"输出侧"证据（执行结果始终=STOP），不直接证明代码里有一条显式豁免（那是A7要回答的，需要读源码）。

---

## B5. 用日志反查 d_min（min_anchor_distance_m）

**脚本**：`analysis/b5_dmin_reverse_check.py`
**方法**：165条 `target_too_close` 决策记录（oracle_hint_action全批），用同一 step 的 trajectory jsonl `route_memory.distance_to_anchor_m` 字段反查实际距离（165/165全部匹配到，无缺失）。

- max = **0.35820m**，min = 0.00626m
- 最大5例：ep310/step3926 0.35820m；ep304/step2701 0.35299m；ep895/step2976 0.35276m；ep205/step4226 0.34871m；ep670/step3376 0.34505m
- 与A3代码里抄出的阈值 `min_anchor_distance_m=0.35`（`hint_action_arbiter.py:25`）**基本一致**：165条里有3条(1.8%)略微超过0.35（0.353/0.353/0.358），差值均<0.01m——合理解释是判定时刻与该step记录的position之间有极小的执行延迟/采样时机差，不构成矛盾。

---

## B6. 精确化百分比（用修正后的87分母，见B3说明）

| 配置 | outbound_success(n) | arrival(entered success-radius, d_min≤3.0m或最终d_e≤3.0m) | success(round_trip_success) | termination deficit |
|---|---|---|---|---|
| oracle_hint | 86 | 49 (56.98%) | 32 (37.21%) | 17 (19.77pt) |
| oracle_hint_action | 86*（应为87，见B3；本表仍按原86分母算，与已核实的86-based分子保持内部一致） | 64 (74.42%) | 52 (60.47%) | 12 (13.95pt) |
| oracle_hint_action_stop | **87**（核实：与前两者的86不同，属实） | 74 (85.06%) | 71 (81.61%) | 3 (3.45pt) |

- stop相对action的提升：success +19（52→71，个数），arrival +10（64→74），deficit -9pt（13.95→3.45）
- **oracle_hint_action_stop 的87与另两批的86不同，原因已查：并非另有隐藏差异，就是B3发现的同一个JSON写入损坏bug——action批次本该也是87，只是那一个87被腐蚀成了86**。若按修正后的87计算 oracle_hint_action，各百分比需要重算（本次未重算，因为修正涉及把ep367的round_trip_success=True重新计入，改变的是分子也是分母，建议下一步用文本抠取的方式把ep367的完整round_trip字段人工补全后重跑B6脚本）。

---

## B7. 仲裁器覆盖率统计复核（oracle_hint_action）

**脚本**：`analysis/b6_b7_b8_b9.py`

- 产生决策记录的episode数：**87**
- 总决策数：**3094**，总override数：**503**，总体override率：**16.26%**
- reason分布：`vlm_action_consistent` 1699 (54.91%)，`occupied_in_local_map_path` 727 (23.50%)，`vlm_conflicts_with_clear_hint`(=override) 503 (16.26%)，`target_too_close` 165 (5.33%)
- 每episode覆盖率（override数/决策数）：median=0.1333，mean=0.1710
- 至少覆盖一次的episode数：**70/87**
- 每episode平均决策步数：35.56
- **按return成功与否分组**：return_success组(n=52) median覆盖率=0.1333 mean=0.1544；return_fail组(n=34) median=0.0859 mean=0.1996——**失败组的均值覆盖率反而更高**（更需要纠正的episode本身更难，纠正次数多但仍失败，不是"覆盖率越高越容易成功"的简单关系，论文如果想用覆盖率论证arbiter有效性需注意这一点不要选择性忽略）

---

## B8. 交叉验证运行（canonical-100版 `pure_oracle_hint_action_100ep_20260812`）

- 该运行配置核实：与high-success-100版的`oracle_hint_action`逐行diff（数据补全README第4节已有）仅episode manifest不同，flag完全一致
- 该批次未跑满（98/100，手动停止），outbound_success=37/98
- 产生决策记录的episode数：**54**（注意：54 > 37，与B3发现的同类模式一致——不是所有产生仲裁记录的episode都在summary.tsv里被记为outbound_success，可能同样存在个别JSON损坏/未及时落盘的情况，本次未逐一排查）
- 总决策数：**2480**，总override数：**433**，override率：**17.46%**（与memory里记录的数字完全一致，交叉验证通过）
- reason分布：`vlm_conflicts_with_clear_hint` 433，`vlm_action_consistent` 1298，`target_too_close` 218，`occupied_in_local_map_path` 531
- episode_idx重叠：high-success-100 与 canonical-100 之间**30/100**个episode_idx重合（这只是数字索引重合，两个manifest的episode_idx对应的episode内容需要靠`episode_id`才能确认是否为同一episode——本次未做这层核实，若要做episode级别的严格overlap需要用episode_id而非episode_idx比对）

---

## B9. "4.3%"历史数据来源——**重要更正，与项目既有README/memory不一致**

**方法**：直接对 `stop_gate_r3_hint_arbiter_hard11_20260630` 和 `oracle_shadow_loftr_v4_30_return_anchor_fix_20260701` 两个批次的全部 `ep*_eval.log` 独立grep统计（不采信README的现成结论）。

| 批次 | eval.log文件数 | 决策数 | override数 | override率 |
|---|---|---|---|---|
| `stop_gate_r3_hint_arbiter_hard11_20260630`（hard-11集） | 9 | **348** | **15** | **4.31%** |
| `oracle_shadow_loftr_v4_30_return_anchor_fix_20260701`（30ep集） | 28 | **435** | **79** | **18.16%** |

**348/15≈4.3%这个精确数字，实际来自 hard-11 这一批单独，不是30ep批次，也不是两者相加**（`投影README.md`《数据补全》第2节和一份08-13的memory都写的是"30ep那批return阶段一共348次决策...只有15次真正替换了VLM输出"——**这个归属是错的**，30ep批次自己的真实决策数是435、override数是79，跟348/15完全对不上）。

**该配置的完整flag组合**（从 `stop_gate_r3_hint_arbiter_hard11_20260630/ep368_eval.log` 的argv行核对，README第2节已有，本次未重新逐行核对但抽查了同批次其余8个episode的argv与ep368一致）：
```
--route_memory --route_hint_mode=compact --route_hint_source=oracle
--route_relocalization_backend=none
--oracle_align_return_yaw_to_anchor_segment
--stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0
--stop_gate_confirm_steps=3 --stop_gate_min_confidence=0.5
--topdown_route_map --hint_action_arbiter
```

**"87个episode集合"**：hard-11批次manifest应有11个episode，实际只找到9个eval.log（`ep1040/187/367/368/408/4/5/678/994`），另2个（可能是`ep367_vlm.log`存在但无对应`_eval.log`，以及至少1个完全缺失）本次未深挖原因，标记为**部分缺失**。

**⚠️ 需要用户决定**：论文里如果引用"4.3%"作为"hint_action_arbiter在yaw-oracle+stop_gate加持下的残余介入率"，精确来源应改写为"hard-11批次（9集，348次决策）"，而不是"30ep批次"或"两批合计"；如果论文其实是想用两批合计的整体数字，正确的合计是 (15+79)/(348+435) = 94/783 ≈ **12.0%**，不是4.3%。这两个数字（4.31% vs 12.0%）该用哪个，需要看论文原文这句话的确切语境（是单独描述hard-11，还是描述"整体历史批次"）。

---

## 未能完成/部分完成的项

1. **B1** τ_pair和判据已找到（代码层面，见上），但checklist提到的"264候选"这个具体数字**NOT FOUND**——已搜索`instruction_rewriter.py`、`round_trip_eval.py`全文grep `264`，未找到匹配上下文；已排除README第6节的"264"（那是另一件事，历史成功率候选池，非配对候选池）
2. **B3的87→修正为87**发现的bug目前只做了单个episode（ep367）的原因定位，**未系统性扫描**其余所有batch_logs是否也存在同类JSON损坏导致summary行缺失的情况（本次B8顺带发现canonical-100批次可能也有同类问题，54>37，但未逐一核实）
3. **B6的oracle_hint_action百分比**仍按86分母展示，未按B3修正后的87重算（需要先人工从损坏JSON里把ep367完整round_trip字段抠出来，这个JSON本身256KB+，损坏点在第4778行，字段抠取用grep能拿到关键几个但不是全部字段，需要写一个更细致的容错解析器）
4. **B8**只做了episode_idx数字重合度，未做episode_id级别的真实episode重合核对
5. **B9**的hard-11批次"11集"中有2集缺失eval.log，未深挖原因（可能只是没跑完/被跳过，也可能是文件被后续清理）

## 脚本清单

- `analysis/b1_pairing_tolerance.py` → `analysis/b1_pairing_distances.csv`
- `analysis/b2_failure_magnitude.py` → `analysis/b2_failure_magnitude.csv`
- `analysis/b4_stop_step_arbiter.py`
- `analysis/b5_dmin_reverse_check.py`
- `analysis/b6_b7_b8_b9.py`（B3的调查是交互式grep/python单行命令做的，未单独存成脚本，过程已在本文档B3节完整记录，具体命令可从会话记录复现）
