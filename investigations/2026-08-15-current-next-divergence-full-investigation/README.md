# current/next 持续分歧根因排查全过程（2026-08-15）

Date: 2026-08-15
Status: 根因链完整排查完毕，三处修复已实现+测试通过，未做live batch验证（smoke测试进行中）。

本文档是这一整天调查的**完整叙事记录**——三份更细的实现文档
（[v11-quarantine-veto](../2026-08-15-v11-quarantine-veto/FINDINGS.md)、
[hint-action-turn-gate-fix](../2026-08-15-hint-action-turn-gate-fix/FINDINGS.md)、
[hint-confidence-collapse-patterns](../2026-08-15-hint-confidence-collapse-patterns/FINDINGS.md)）
只记录了"决定做什么、为什么做"，本篇把中间**走过的弯路、被推翻的假设、完整的37个失败episode分类**都补全，避免只看数据补全README摘要会丢失的排查细节。

数据来源：`line2_closure_off_cooldown_kdtree_100ep_20260815`批次（100/100完成，outbound=67/100，return-rate=27/67≈40.3%，见`investigations/数据补全/README.md`第10节）。全篇方法论：所有结论均用真实捕获数据验证（真实ICP重算、真实轨迹ground truth、真实生产日志字段），不采信"看起来合理"的推断。

## 1. 起点：quarantine跳跃机制的误判

`route_memory_agent.py`的quarantine跳过机制（`_next_candidate_index`）在current长期卡死不动时，会让"next"候选越跳越远，最终撞上`reliability_quarantine_max_chain=4`这个共享预算上限（Injection A可靠性quarantine与position-trend quarantine共用），被迫落地在一个仍可能是坏anchor的位置上。

**真实数据验证**（43次jump≥3事件、194条真实标注）：
- 跳跃步数越大，落地误判率越高：跳2步15%、跳3步14%、跳4步50%、跳5步（预算封顶）57%
- 被跳过的152个anchor槽位里，57%其实是好的（被误杀，浪费了预算）
- 按"跳过区块构成"分三类：全部真坏（8个事件，落地依然坏88%）、全部真好（13个事件，落地依然坏仅8%）、好坏混杂（21个事件，57%）——说明quarantine的误判率本身、而不是预算大小，才是主因

## 2. 从零尝试4种自建信号改善quarantine判断，全部无效

1. **同一组4个标量特征换成模型**（LogisticRegression/RandomForest/GradientBoosting，5折交叉验证）：AUC 0.71-0.75，不如现有硬编码z-score公式的0.764——瓶颈不在"怎么组合"，是这4个特征本身信息量就到顶了
2. **alias_score**（anchor自相似度，已算好但没用上）：误判组vs正确组均值0.714 vs 0.734，几乎不分
3. **loftr_rear_yaw_check**（现成的视觉朝向交叉验证）：37个满足触发条件的读数里一次都没触发过——这个检查专测朝向歧义，而我们的问题主要是位置/平移型走廊aliasing，方向不对，白测
4. **corridor_degeneracy_ratio + localizability**（原始点云几何退化程度）：均值0.780 vs 0.724，也几乎不分

## 3. 找到并验证V1.1可以直接复用

在`/home/teambruce/navila-reliability-v1_1`找到路线2现成的V1.1可靠性模型（distance头，249个特征，91,003条真实读数训练，nested CV AUC 0.969，但**自己的prospective验证协议从未跑过**——如实标注这个局限）。

用它自己的推理管线，对194条真实、V1.1训练时从未见过的样本外读数打分：
- 整体AUC 0.788（不如声称的0.969，但好于我们自建的任何信号）
- **不对称精确率**：`p_distance_bad≤0.5`（confidently好）→ 100%精确（0/54错），覆盖率28%；`p_distance_bad≥0.5`（confidently坏）→ 只有60-68%精确，跟现有规则差不多
- 作为quarantine上的一层**只否决不替代**的安全阀：救回47%（41/87）的误判quarantine，0次误救真坏anchor
- 模拟到全批跳跃行为：落地坏anchor比例48%→29%，撞预算上限比例69%→26%

详见[v11-quarantine-veto/FINDINGS.md](../2026-08-15-v11-quarantine-veto/FINDINGS.md)。**已实现为`--sequential_pair_v11_quarantine_veto`。**

## 4. 37个失败episode完整分类（关键的一次修正）

初步统计：37个失败中，5个能被V1.1直接推进（ep962/367/264/266/960），10个即使V1.1也救不回来（ep646/889/324/555/1062/829/228/291/428/733，整个候选区块真的全坏），17个原本以为跟quarantine完全无关。

**深挖那17个发现12个其实是同一机制**，只是通过多次小跳（每次都<3步，单独看不出来）累积出来的，或者current从return一开始就卡死——用真实数据直接验证（如ep783/784/785：current经过好几次1-2步的小跳逐渐卡死，next却因为quarantine继续推进，最终current/next的gap照样很大）。真正跟这条调查线完全无关的只剩2个：ep319（confidently-wrong-stop，单次错误但confidently的读数骗过了forced-stop）、ep688（差半米的边缘案例）。

**修正后：37个失败里32个（86%）都能追溯到current/next持续分歧这同一个根本机制**，只有2个独立，另有5个（ep1038/490/1004/476/895）失败原因至今未查明，3个是物理摔倒（超出本次范围）。

## 5. 深挖"机器人为什么会走偏"——发现更上游的问题

对V1.1也救不回来的10个episode，把搜索范围一路延伸到anchor 0（路线起点），发现**没有一个anchor的误差是变小的**，很多情况下反而越查越远——不是"该多跳几步就能找到对的"，是那一段路线附近真的没有正确目标可选，机器人已经实质性地偏离了整条路线。

**追溯偏离起点**（用真实轨迹+真实anchor位置反算body-frame方位角，跟`[hint_arbiter]`实际打印值逐步对比）：10个episode呈现几乎一致的模式——
1. return刚开始机器人就站在正确anchor上（`nearest_anchor_dist≈0.00`），hint给出的方向本身跟真值精确一致（差<12°）
2. `hint_action_arbiter`识别出需要一次大角度（~110-150°）转向，强制执行一次
3. 之后连续~125步要么被`occupied_in_local_map_path`挡住不敢再纠正，要么置信度紧接着崩溃、再没机会重试
4. 机器人此后完全无引导地漂移几百步，直到真的走远（真值验证：nearest_anchor_dist从0.0一路涨到最终的4-12m）

**关键代码bug**：`occupied_in_local_map_path`这道闸门测的是"朝目标anchor方向走直线路径会不会撞墙"，这对`forward`类动作是有意义的安全检查，但对纯粹的原地转身动作（转向不涉及任何位移）完全没有意义，却被同一道闸门挡住了。

详见[hint-action-turn-gate-fix/FINDINGS.md](../2026-08-15-hint-action-turn-gate-fix/FINDINGS.md)。**已实现为`--hint_arbiter_turn_override_completes_full_angle`**（转向类跳过clear-path检查 + 一次转完所需角度；前进类完全不动，因为盲走有真实碰撞风险，不像转身）。

扩大到全部22个相关episode后发现，这个"转向被挡"模式只解释5-6个，**不是主流**——数量最大的（10+个）是另一种模式：VLM明明在正常跟随、角度平滑收敛，置信度却突然崩溃。

## 6. 置信度崩溃的两个子病根

用真实ICP重算next角色自己的原始读数（生产日志里没记录这个，只记录被选中的current角色读数），在`[hint_arbiter]`报告`low_relocalization_confidence`的确切步骤上直接检验：

- **②a 真实持续的ICP朝向歧义**（如ep814：anchor4周围场景存在真实几何对称性）：`best_to_second_score_ratio`稳定在0.87-0.99、`match_class=ambiguous_high_confidence`，175个真实步骤全程如此——不是噪声，真解不开，trend平滑救不了
- **②b/③ 读数其实基本准，置信度只是噪声性地卡在0.90阈值下面**（如ep484：return第一次attempt真值0.54m估计0.59m，confidence却只有0.887，差0.013没过线，从第一步guidance就哑火）

对全部22个相关episode逐一真实检验分类：②b（trend_confidence候选修复）9个，②a（真实歧义，救不了）7个。

详见[hint-confidence-collapse-patterns/FINDINGS.md](../2026-08-15-hint-confidence-collapse-patterns/FINDINGS.md)。**已实现为`--hint_arbiter_trend_confidence`**（直接复用本会话早前给`stop_gate.py`实现、已测试但从未接入CLI的`trend_confidence`滑动窗口机制）。

## 7. 三处修复合计覆盖面（离线验证的最终账本）

| | 数量 |
|---|---|
| 37个失败总数 | 37 |
| 排除物理摔倒 | -3 |
| 有效范围内 | 34 |
| **被至少一项改动触及**（确认级别） | **19**（+1个ep366不确定） |
| **三项改动完全没触及到** | **15** |

完全没触及到的15个：7个真实ICP歧义（②a）+ 5个从未深挖过原因（ep1038/490/1004/476/895）+ ep319（confidently-wrong-stop）+ ep688（边缘案例）+ ep366（转向修复触发条件出现太晚，不确定）。

**重要限制**：V1.1否决层的"覆盖7个"是真正离线回放验证的（拿真实捕获数据重算，不需要重跑仿真）；转向闸门修复和trend_confidence的"覆盖X个"，是离线确认了**触发条件会被满足**，但这两个改动本身会改变发给机器人的实际控制指令，一旦指令变了，机器人后续真实轨迹就会跟着变，旧日志没法用来验证"改了之后这一集最终会不会成功"——这需要真正重新跑一遍仿真（live batch）才能知道。当前的smoke测试就是为此而设。

## 8. 代码改动清单（三处，均默认关闭、纯加性、不改变默认行为）

- `route_memory_agent.py` + 新文件`v11_veto.py` + `round_trip_eval.py`：`--sequential_pair_v11_quarantine_veto`
- `hint_action_arbiter.py` + `round_trip_eval.py`：`--hint_arbiter_turn_override_completes_full_angle`
- `hint_action_arbiter.py` + `round_trip_eval.py`：`--hint_arbiter_trend_confidence`（+4个子参数）
- 新增27个单元测试（`test_route_memory_agent.py`新增6个、新建`test_hint_action_arbiter_turn_gate.py`7个、新建`test_hint_action_arbiter_trend_confidence.py`7个，另有其余既有测试文件回归全过），全项目449个测试全部通过，无回归

## 9. 未闭环的开放问题

- ②a（真实ICP歧义，7个episode）还没有确定修法——候选方向是把`loftr_rear_yaw_check`从"降级过度自信的读数"改造成"主动消歧"，但改动量未评估
- ep1038/490/1004/476/895（5个）从未深挖过真正失败原因
- ep319（confidently-wrong-stop）、ep688（边缘案例）两个独立个案未深挖
- ep366需要专门再查（转向修复的触发条件出现在episode后半段，不确定是否真的被覆盖）
- 三处修复尚未做live batch验证，当前只完成到smoke测试阶段
