# 今晚完整结果

## 1. 5ep prospective 基线

测试 episodes 为 319、498、295、430、1008。ep430 在 outbound 阶段失败，
因此只有四集可评分。

Hint v1 数据集包含 3,991 rows、280 episodes、9 scenes：

- `abstain` 703；
- `keep_vlm` 1,339；
- `override_hint` 1,949；
- 94 个 oracle-source rows 在训练前被排除。

全数据 clear conflicts 上，旧 bearing-trust gate 的 precision/recall 为
0.7657/0.3108。unseen 5ep pooled 的旧 gate 为 0.9130/0.3000；Hint v1 提升到
0.9000/0.6429。这直接支持“return 失败中有大量本应介入的 hint 被 anchor
trust gate 拦截”的判断。

但 ep1008 中 Hint v1 有 4 次正确、2 次错误 recommendation。因此问题不能通过
简单放开 hint gate 解决，需要独立模型和独立 clearance boundary。

## 2. Hint-action v2

### Multiclass robust v2

新增了角度环绕、query-gap reset、hint/VLM motion response、相似 hard-negative
加权，并移除 absolute anchor indices。该版本消除了 prospective false
override，但在 5ep 上零 advisory action，属于没有 liveness 的“安全”，不可用。

### Binary v2

把任务收敛成 `override_hint` / `do_not_override` 后：

| Split | Advisory precision | Advisory recall |
|---|---:|---:|
| development OOF | 0.8514 | 0.3425 |
| untouched test | 0.8410 | 0.3723 |
| unseen prospective 5ep | 0.9655 | 0.4000 |

ep1008 上为 4 次正确、0 次错误 recommendation。模型 SHA-256：

```text
567e24aef5036e3310a36a8333ab8cc40ee467a293506973fa544fb1baa49603
```

加独立 clearance 后，untouched test P/R 为 0.8372/0.6136，prospective 5ep
为 1.0000/0.3810。两者 recall denominator 是各自 clearance-eligible 样本，
不可直接互相相减。

严格 zero-OOF-FP execution threshold 在 untouched test 上 precision 1.0、
recall 0.1335，但在 prospective 5ep 零动作，因此当前仍只适合 advisory shadow。

5ep clearance 权重分布为：

- clear 11.5；
- occupied 13.0；
- unavailable 20.5。

`occupied` 必须继续硬拦截；`unavailable` 更适合进入 bounded scan/recheck，
否则会把“暂时看不清”永久解释为“不允许 hint”，再次造成 return liveness
失败。

## 3. Anchor wider-candidate replay

回放调用 authoritative relocalization 代码，候选仅来自运行时可观察的
`current-2/current-1/current/current+1` 与历史 candidates，未注入 oracle。

第一轮九场景 pilot：

- 46 attempts；
- historical coverage 12/46 = 26.1%；
- wider coverage 36/46 = 78.3%。

第二轮 4-way sampled shards：

- 8 episodes / 24 attempts；
- historical coverage 6/24 = 25.0%；
- wider coverage 19/24 = 79.2%；
- missing frames = 0。

两轮结果高度一致，说明主要瓶颈确实是 candidate proposal coverage，而不是
单个 episode 偶然。固定 ±2 仍不能覆盖所有 rebase，因此 Anchor v2 应先提出
bounded rebase neighborhood，再让 ICP/sequence evidence 排序。

工具已支持 deterministic episode sharding、request fingerprint 和安全 resume，
避免全量 112,733 rows 的单进程长任务无法恢复。

## 4. Terminal robust v2

Robust v2 移除了 absolute anchor/source/target index，用七个 development scenes
的 leave-one-scene-out prediction 冻结 threshold 0.713282、streak 4。

- development OOF：balanced accuracy 0.7347，macro-F1 0.6817；
- untouched test：balanced accuracy 0.7416，macro-F1 0.7095；
- development：0 个 true-far false-arrived；
- untouched test：5 个 true-far false-arrived；
- unseen 5ep：0 个 false-far confirmation，但 ep319 arrived recall 为 0。

模型 SHA-256：

```text
f033696bf632134c48edf3ce1734850833c98a93bfdadc7173780ef5ebef6bbb
```

该模型比 v1 更保守，但还没有通过 STOP activation gate，只能作为 shadow
probability sensor。

## 5. 总体判断

目前不应继续仅靠离线指标微调三个模型，也不应激活任何模型。先运行新的
30ep read-only shadow 更有信息价值：

- 验证 Hint v2 是否在长时序中仍有足够 liveness；
- 区分方向判断错误与 clearance unavailable；
- 观察 Terminal v2 的 false confirmation 和 missed arrived run；
- 为 Anchor v2 收集真实 candidate-miss、rebase distance 和 temporal evidence。

只有 shadow 给出 scene-level failure structure 后，下一轮优化才不会退化成对
现有 5ep 的过拟合。
