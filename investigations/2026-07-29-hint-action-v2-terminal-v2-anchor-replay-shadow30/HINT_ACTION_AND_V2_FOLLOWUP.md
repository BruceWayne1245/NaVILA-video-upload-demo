# 2026-07-29：专用 hint-action 模型与 v2 离线回放

## 结论

可以、也应该把 `hint_action` 从“anchor bearing 是否可信”中拆出来单独建模。
第一版数据、模型和 unseen 5ep 回放已经完成，但当前只允许 shadow。

现有实现确实把两件不同的事绑定在一起：

- `hint_action_arbiter.py` 在计算完整动作仲裁前，会因
  `low_relocalization_confidence` 直接拒绝 override；
- `v11_consumer_policy_v2.py` 对 `hint_action_override` 使用
  `bearing_trusted` 作为 authority。

这会把“ICP 不足以证明 anchor pose 精确”错误地等价成“route hint 一定不比
VLM movement 好”。历史 oracle 结果同时证明不能简单改成 always-on：正常集里
强制 hint 多数正确，但 bad-ICP 集 ep680 中强制 hint 只有 5/22 正确。

因此新职责边界是：

1. Anchor 模型只估计 route identity / observation quality；
2. Hint-action 模型只在 true-far movement conflict 中决定
   `override_hint`、`keep_vlm` 或 `abstain`；
3. Terminal 模型独立管理 STOP 证据；
4. local-map/collision clearance 保持独立硬门，不由学习模型绕过。

## Hint-action v1

标签不复制旧门控，而是分别把 hint 和 VLM movement 与 oracle route direction
比较。STOP 行被排除，oracle 字段只作监督、不进入 features。

- 3,991 rows，280 episodes，9 scenes；
- class rows：703 abstain、1,339 keep_vlm、1,949 override_hint；
- 94 个 oracle-source rows 在训练前排除；
- artifact SHA-256：
  `1851c727534f943396c7f74ec6b47f8da0695753cb0edc17fd957cdc532f03ca`。

旧 bearing-trust gate 在全数据 clear conflicts 上 precision 76.57%、
recall 31.08%，说明“本应介入但被拦住”是可量化的主要漏检。

scene-held-out test：

- 三分类 balanced accuracy 0.4870，macro F1 0.4808；
- 旧门控 precision/recall 0.6466/0.3905；
- validation 选择的 hint operating point 在 test 上为
  0.7464/0.4711。

unseen prospective 5ep 中，ep430 outbound failure 不可评分。其余四集 pooled：

- 旧门控 precision 0.9130、recall 0.3000；
- 专用模型 precision 0.9000、recall 0.6429。

方向成立，但 ep1008 有两次错误介入，因此 v1 不可 active。

后续 Hint v2 使用 leave-one-scene-out calibration、角度环绕、query-gap reset、
hint/VLM motion response 和相似 hard-negative 加权。ep1008 仍是冻结验收集，没有
进入训练。

三分类 v2 虽然消除了 false override，但 5ep 完全不再介入，属于无效的
“安全”。改成直接回答 `override_hint` / `do_not_override` 的二分类后：

- development OOF advisory precision/recall：0.8514/0.3425；
- untouched test advisory precision/recall：0.8410/0.3723；
- unseen 5ep advisory precision/recall：0.9655/0.4000；
- ep1008：4 次正确 recommendation，0 次 false override。

独立 clearance gate 后 unseen 5ep precision/recall 为 1.0000/0.3810，但
untouched test 仍为 0.8372/0.6136；严格 zero-OOF-FP policy 在 5ep 上零动作。
因此二分类 v2 是更稳的 advisory 模型，但仍不能 active。

5ep 的 clearance 权重分布为：clear 11.5、occupied 13.0、unavailable 20.5。
occupied 必须继续硬拦截；下一版 controller 应把 unavailable 变成 bounded
scan/recheck 状态，而不是永久 hint veto，否则即使方向模型正确也无法改善
return liveness。

## Anchor wider-candidate pilot

使用 authoritative relocalization 代码做只读离线 ICP replay；候选只来自运行时
可观察的 `current-2/current-1/current/current+1` 与历史 candidates，不注入
oracle candidate。

九场景 46 attempts pilot 上：

- historical oracle-candidate coverage：12/46 = 26.1%；
- wider coverage：36/46 = 78.3%。

固定 ±2 仍无法覆盖所有 rebase，所以 Anchor v2 下一步应先提出 bounded
rebase neighborhood，再由 ICP/sequence evidence 排序。全量 112,733 rows
串行成本过高，因此 replay 工具已经加入 deterministic episode sharding、
selection fingerprint 和安全 resume；一行端到端 smoke replay 通过。下一步只需
选择计算预算后启动 sampled shards。

随后运行的 4-way sampled shard（8 episodes、24 attempts）再次得到：

- historical coverage：6/24 = 25.0%；
- wider coverage：19/24 = 79.2%；
- missing frames：0。

这与九场景 pilot 的 26.1% -> 78.3% 一致，说明提升不是单个 episode 偶然。

## Terminal v2

Robust v2 移除了 absolute anchor/source/target index，使用七个 development
scene 的 leave-one-scene-out prediction 冻结 threshold 0.713282、streak 4。

- untouched test balanced accuracy 0.7416、macro F1 0.7095；
- development scenes：0 true-far false-arrived；
- untouched test：5 true-far false-arrived；
- unseen 5ep：0 false-far confirmation，但 ep319 arrived recall 为 0。

它比 v1 更保守，但仍未通过 stop activation gate，只能作为 probability sensor。

## 已完成的隔离边界

- 所有训练与回放输出位于
  `/home/teambruce/navila-anchor-terminal-training-data-20260729`；
- Active evaluator 与已保存 capture 均未修改；
- unseen 5ep 均为 `control_effect=none`；
- ep319 两处损坏只在内存解析时修复，源文件未改；
- 20 个 unit tests、artifact load、strict JSON validation 和一行 ICP replay
  smoke test 全部通过。

## 下一步

1. 用已经实现的确定性 episode sharding 生成 Anchor v2 可训练的覆盖样本；
2. 对 hint-action 做 leave-one-scene-out calibration，并针对 ep1008 false
   override 增加 temporal agreement、motion response 和 clear-path state；
3. 先做 online read-only shadow，记录 missed-beneficial 与 harmful override
   的连续时长；
4. 只有每个 held-out scene 都满足零高代价 harmful override，才允许 bounded、
   reversible canary；STOP authority 继续留给独立 Terminal gate。

完整训练包报告：

- `reports/v1/hint_action_training_report.md`
- `reports/v2/prospective5_hint_terminal_v2.md`
- `reports/v2/terminal_v2_robust_report.md`
- `reports/v2/wider_candidate_pilot.md`
