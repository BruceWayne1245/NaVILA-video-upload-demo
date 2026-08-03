# 下一步

## 立即执行：完成 shadow30

先等待 ep670 canary。放行剩余 29 集必须同时满足：

1. episode 结果可评分；
2. Anchor、Terminal、Hint v1、Hint v2 四个 scorer 全部成功；
3. summary 明确 `control_effect=none`；
4. evaluator/V1.1 consumer 始终未加载模型或采用模型动作。

shadow 结束后先按 scene 和 return phase 汇总，不只看 pooled 指标。

## Hint-action 验收

重点统计：

- beneficial override 的 precision、recall；
- harmful override 数量及最长连续 run；
- `occupied` 与 `unavailable` 分别造成的 veto；
- missed-beneficial 中有多少可由 bounded scan/recheck 恢复；
- v1 高召回 comparator 与 binary v2 保守 comparator 的增量关系。

在任何 active canary 前，要求每个 held-out scene 都没有高代价 harmful run，
并证明策略不是靠“零动作”获得安全指标。

## Terminal 验收

重点统计：

- true-far false-arrived；
- missed arrived 的连续长度；
- threshold crossing 到实际终点证据的时间差；
- ep319 型 arrived recall 失败是否在更多 scene 重现。

Terminal robust v2 当前只能提供 probability；STOP authority 不进入本轮 canary。

## Anchor v2 数据路线

基于已验证的 coverage 提升，下一步生成有计算预算上限的 sampled shards：

1. 提出 bounded rebase neighborhood；
2. 保存 historical/wider candidate coverage；
3. 保存每个候选的 ICP 和 sequence evidence；
4. 以 scene/episode 为 group 做验证；
5. 不把 oracle candidate 注入 inference candidates。

只有 candidate coverage 先达到可用水平，继续优化当前 Anchor classifier 才有意义。

## 可能的受控激活顺序

如果 shadow 通过，推荐顺序仍是：

1. Hint binary v2 仅 advisory；
2. `unavailable -> bounded scan/recheck`，`occupied` 继续硬 block；
3. bounded、可逆、低频 movement canary；
4. Terminal 继续 shadow；
5. Anchor v2 在新 replay 数据完成后另行评估。
