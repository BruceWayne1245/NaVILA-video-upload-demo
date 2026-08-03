# 2026-07-29：Hint-action v2、Terminal v2、Anchor replay 与三模型 shadow30

## 本次归档结论

今晚完成了从上一轮 5ep prospective 数据出发的三条独立工作线：

1. 将 `hint_action` 从 anchor bearing trust 中拆出，训练专用模型；
2. 训练去除绝对索引泄漏、按 scene 校准的 Terminal robust v2；
3. 用 authoritative ICP replay 验证 Anchor wider-candidate 的覆盖收益；
4. 在以上离线结论基础上启动 30ep、三模型、完全 read-only 的在线 shadow。

截至本归档快照时间，所有学习模型均为 `control_effect=none`。没有模型被接入
evaluator，也没有 promotion、rebase、movement override 或 STOP authority。
30ep 当前仍处于 ep670 canary 运行中，不能把“已启动”表述为“已通过”。

## 最重要的数据

| 项目 | 结果 | 当前结论 |
|---|---:|---|
| Hint v1 数据 | 3,991 rows / 280 episodes / 9 scenes | 专用建模方向成立 |
| 旧 gate，unseen 5ep | P/R 0.9130 / 0.3000 | recall 明显不足 |
| Hint v1，unseen 5ep | P/R 0.9000 / 0.6429 | recall 提升，但 ep1008 有 2 次错误介入 |
| Hint binary v2，unseen 5ep | P/R 0.9655 / 0.4000 | 更稳的 advisory，仍不可 active |
| Hint binary v2 + clearance，unseen 5ep | P/R 1.0000 / 0.3810 | clearance 仍是主要 liveness 边界 |
| Anchor wider replay，9-scene pilot | 12/46 -> 36/46 | candidate coverage 26.1% -> 78.3% |
| Anchor wider replay，8-episode sample | 6/24 -> 19/24 | candidate coverage 25.0% -> 79.2% |
| Terminal robust v2，untouched test | BA 0.7416 / macro-F1 0.7095 | shadow-only probability sensor |
| 三模型 shadow30 | 30 episodes / 9 scenes | ep670 canary 运行中 |

## 文档导航

- [FINDINGS.md](FINDINGS.md)：完整实验结果与解释；
- [CHANGES_AND_WORKLOG.md](CHANGES_AND_WORKLOG.md)：今晚代码、数据与运行改动；
- [HINT_ACTION_AND_V2_FOLLOWUP.md](HINT_ACTION_AND_V2_FOLLOWUP.md)：hint-action
  职责拆分和 v2 细节；
- [THREE_MODEL_SHADOW30_LAUNCH.md](THREE_MODEL_SHADOW30_LAUNCH.md)：30ep
  shadow 启动、隔离边界和 cohort；
- [NEXT_STEPS.md](NEXT_STEPS.md)：shadow 验收和之后的模型路线；
- [runtime_status/SNAPSHOT.md](runtime_status/SNAPSHOT.md)：归档时刻的实时运行快照；
- [ARTIFACT_MANIFEST.sha256](ARTIFACT_MANIFEST.sha256)：本目录文件哈希。

## 归档内容

- `data/`：Hint 数据、episode/split provenance、两轮 wider-candidate replay；
- `models/`：Hint v1、Hint v2 两版、Terminal v2 两版；
- `reports/`：机器可读 JSON 和对应 Markdown 报告；
- `code/`：数据构造、特征、训练、replay、prospective scorer、shadow runner；
- `code/tests/`：本轮执行并通过的 20 个单元测试；
- `runtime_status/`：30ep service 启动 provenance 和归档时日志快照。

Anchor/Terminal v1 的大型基础数据和模型已经完整归档于
[`../2026-07-29-learned-anchor-terminal-models-and-shadow-handoff/`](../2026-07-29-learned-anchor-terminal-models-and-shadow-handoff/)。
本目录引用而不重复提交其中约 80MB 的 `anchor_state.jsonl.gz` 与
`terminal_decision.jsonl.gz`，但保留了本轮新增的全部 Hint 数据、replay 输出、
模型、报告与代码。

## 复现与安全边界

- 原始训练工作区：
  `/home/teambruce/navila-anchor-terminal-training-data-20260729`；
- 5ep capture 只读；ep319 的两处损坏仅在解析内存中修复；
- 训练标签可使用 oracle，模型 features 不包含 oracle 字段；
- Hint/Terminal robust v2 移除了 absolute anchor/source/target indices；
- wider-candidate replay 不注入 oracle candidate；
- 20 个 unit tests、artifact load、strict JSON validation 和单行 ICP replay
  smoke 均通过。
