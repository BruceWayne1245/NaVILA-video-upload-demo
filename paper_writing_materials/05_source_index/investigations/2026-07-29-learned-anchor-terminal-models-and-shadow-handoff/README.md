# 2026-07-29：Anchor/terminal 训练、Active-50 取证与 shadow handoff

这是 2026-07-29 的主 handoff。它承接：

- `../2026-07-28-session-handoff/`
- `../2026-07-28-route2-active50-return-failure-forensics/`
- `../2026-07-28-promotion-quarantine-controller-model/`
- `../2026-07-28-anchor-support-recovery/`
- `../2026-07-28-terminal-stop-evidence-state-machine/`

本目录同时保存今天构建的完整训练数据、模型、代码、报告和运行队列快照。
后续会话不应依赖聊天记录恢复这些信息。

## 一、当天结论

### 1. V1.1 的正确定位

V1.1 仍然是有价值的 ICP 可靠性模型。已有失败取证表明，它经常能够正确识别：

- 当前 ICP pose 是否错误；
- bearing/distance 是否不可信；
- current/next 中哪一侧缺乏可靠观测。

例如 Route2 ep491 中，A10 真值 bad 914/1001 次，V1.1 判 untrusted
963/1001 次。失败并非来自模型没有报警，而是报警后：

1. 没有机制恢复正确 anchor identity；
2. promotion、route hint 和 stop consumer 同时失去可用证据；
3. controller 请求尚未实现的 active scan 后进入长期 disabled/hold；
4. 机器人继续运动，anchor state 却保持 A11/A10 共 1001 attempts。

因此当前最准确的架构结论是：

> V1.1 应作为 observation-quality sensor，而不应把一次
> `not trusted` 直接解释成 anchor 晋升、跳过、回退或允许停车。

### 2. “60% 跌到 20%”不是单调模型退化

复算后的 return 条件成功率：

| 批次 | 成功/Outbound-success | 比率 | 说明 |
|---|---:|---:|---|
| 2026-07-21 fix-ON A+B+C | 12/19 | 63.2% | success-first；真值终点半径口径 |
| 2026-07-25 Active V2 冻结点 | 18/30 | 60.0% | 最终 summary 为 19/32=59.4% |
| 2026-07-26 Route1 downgrade | 8/24 | 33.3% | 有效 completion 受 infra loss 影响 |
| 2026-07-27 Route2 中途取证点 | 8/23 | 34.8% | 当时只完成了失败偏重的前段 |
| 2026-07-27 Route2 最终有效结果 | 20/36 | 55.6% | 同一系统继续跑后恢复到约 56% |
| 2026-07-29 Active-50 已完成前缀 | 3/11 | 27.3% | 12 个有效 completion，11 个 outbound success |

最重要的配对证据：Route2 在当前 Active-50 已跑到的同一前缀上只有
2/10=20%，但完整 Route2 是 20/36=55.6%。当前 Active-50 在这段前缀为
3/11=27.3%，不能据此判定完整系统已经退化到 20%。

此外，旧 12/19 是 outbound 后的条件成功率。按其 66 个有效 episode 计算，
端到端 round trip 是 12/66=18.2%。旧报告还把 ep813
“到达但没有真正停车”按真值到达计为成功；当前 evaluator
`success_requires_stop=True`，口径更严格。

详细分析见 [FINDINGS.md](FINDINGS.md)。

当天后续完成的专用 hint-action 模型、Anchor wider-candidate pilot、
Terminal v2 robust 训练及 unseen 5ep 固定回放见
[HINT_ACTION_AND_V2_FOLLOWUP.md](../2026-07-29-hint-action-v2-terminal-v2-anchor-replay-shadow30/HINT_ACTION_AND_V2_FOLLOWUP.md)。

三模型新 30ep read-only shadow 的 cohort、冻结哈希、隔离边界和监控入口见
[THREE_MODEL_SHADOW30_LAUNCH.md](../2026-07-29-hint-action-v2-terminal-v2-anchor-replay-shadow30/THREE_MODEL_SHADOW30_LAUNCH.md)。

### 3. Active-50 前缀的两类失败

停止 Active-50 时，共有：

- 14 个 unique episode 已开始；
- 12 个严格有效 completion；
- 11 个 outbound success；
- 3 个 return success：ep4、ep95、ep310；
- 8 个 return failure：ep19、88、89、93、196、205、264、268；
- ep276 为 outbound failure；
- ep5、ep87 无有效 completion；
- ep344 第一次 timeout，第二次在确认不可逆后按用户要求停止。

使用今天构建的 oracle return-route distance，而不是欧氏 3m 半径，八个 return
failure 被分为：

| 类型 | Episodes | 数量 |
|---|---|---:|
| 从未进入 `route_distance <= 2.65m` 的 arrived band | 19、89、93、196、205、264、268 | 7 |
| 已进入机制允许形成停车正证据的 arrived band，但未停车 | 88 | 1 |

对应最小 oracle route distance：

| ep | 最小 route distance | 结果 |
|---:|---:|---|
| 19 | 6.202m | never arrived |
| 88 | 2.556m | entered arrived band |
| 89 | 3.379m | boundary 外侧；never arrived |
| 93 | 12.628m | never arrived |
| 196 | 4.966m | never arrived |
| 205 | 7.497m | never arrived |
| 264 | 3.398m | 略高于 far/boundary 分界 |
| 268 | 12.134m | never arrived |

第一类的共同系统链路是：

```text
初始 pair 多数正常
→ ICP 质量下降
→ V1.1 检测到不可信
→ 旧状态机冻结 current 或连续跳过 next
→ 可用 hint 减少/消失
→ 没有恢复正确 identity 的执行器
→ VLM 单独导航并逐渐偏离
```

但不能把七集全部写成“只有 anchor 选择一个原因”。物理运动、VLM
决策、stuck recovery 和 terminal policy 仍可能是共同原因。可以确认的是：
“检测坏观测”本身没有恢复导航能力。

## 二、今天完成的训练数据

训练包 schema：`navila-anchor-terminal-training-v1`。

### Anchor-state

- 112,733 rows；
- 282 episodes；
- 9 Matterport scenes；
- exact duplicate trajectory 删除 20 个；
- 损坏 JSON 排除 7 个；
- 训练/验证/测试严格按 scene 隔离；
- 46,727 行为 exact/high-quality，权重 1.0；
- 22,369 行 off-route 或 label ambiguous，仅审计、权重 0；
- oracle next 在历史 controller 实际 probe candidates 中的覆盖率只有 28.2%。

最后一点非常关键：当前数据适合训练 transition/rebase 和时序状态判断，
但不适合把“未出现在历史候选集合中的正确 anchor”当作普通 closed-set negative。
完整 anchor posterior 需要后续 wider-candidate offline ICP replay。

### Terminal-decision

- 10,900 rows；
- `arrived` 2,079；
- `boundary` 365；
- `far` 8,456；
- VLM STOP rows 1,635；
- `verify` 只有 28 行。

标签使用 return-route distance：

- `arrived`: `<=2.65m`
- `boundary`: `(2.65m, 3.35m]`
- `far`: `>3.35m`

它不是欧氏 distance-to-A0 标签。完整说明和限制见：

- [DATA_CARD.md](DATA_CARD.md)
- [data/v1/audit.json](data/v1/audit.json)
- [data/v1/splits.json](data/v1/splits.json)

## 三、今天训练的两个模型

### Anchor-transition v1

Classes：

- `advance_one`
- `hold`
- `rebase`
- `rollback`
- `skip_or_rebase`

| Split | Balanced accuracy | Macro F1 | ROC AUC |
|---|---:|---:|---:|
| train | 0.9830 | 0.9829 | 0.9994 |
| validation / EU6Fwq7SyZv | 0.7346 | 0.7155 | 0.9028 |
| test / zsNo4HB9uLZ | 0.7710 | 0.7708 | 0.9531 |

训练到跨场景存在明显 generalization gap，因此只能 shadow。

Artifact：

`models/v1/anchor_transition_v1.joblib`

SHA-256：

`4d37f9bcb341f093d4cdc87e92c041db7d582a912acdb629963039cf7b27dc55`

### Terminal-decision v1

Classes：

- `arrived`
- `boundary`
- `far`

| Split | Balanced accuracy | Macro F1 | ROC AUC |
|---|---:|---:|---:|
| train | 0.9880 | 0.9803 | 0.9994 |
| validation / EU6Fwq7SyZv | 0.6943 | 0.7165 | 0.9145 |
| test / zsNo4HB9uLZ | 0.7368 | 0.7534 | 0.9807 |

Test per-class F1：

- arrived: 0.8503
- boundary: 0.4267
- far: 0.9833

在 validation scene 上选择的 zero-false-arrived threshold 没有跨场景泛化：

- validation false-arrived：0；
- test false-arrived：16；
- 其中 true-far：13。

所以该 threshold 只是诊断产物，不能获得 stop authority。

Artifact：

`models/v1/terminal_decision_v1.joblib`

SHA-256：

`1b7bbc2fab5211c9b6422c70103735b89a8f3d75fa7c23beacfb8ea3b64cab84`

完整报告见：

- [MODEL_CARD.md](MODEL_CARD.md)
- [reports/v1/training_report.md](reports/v1/training_report.md)
- [reports/v1/training_report.json](reports/v1/training_report.json)
- [ARTIFACT_MANIFEST.sha256](ARTIFACT_MANIFEST.sha256)

## 四、运行状态与隔离边界

### Promotion-shadow 30ep

Unit：

`navila-promotion-shadow-30ep-queued-20260728.service`

2026-07-29 12:29 BST snapshot：

- service active/running；
- 完成 6/30，当前运行第 7 个 ep351；
- 5 个严格有效 result；
- ep5 缺少有效 measurement；
- 有效结果中 return success：ep88、ep268；
- return failure：ep205、ep264、ep310。

这批使用 promotion model shadow，模型不改变控制行为。

### Learned anchor/terminal prospective shadow5

Unit：

`navila-learned-anchor-terminal-shadow5-after-promotion30-20260729.service`

Episodes：

`319, 498, 295, 430, 1008`

五集不在训练 corpus。队列规则：

1. 30ep unit 和相关进程全部退出；
2. GPU free memory >= 12,000MiB；
3. 稳定等待 60 秒；
4. 30ep master completion marker 存在；
5. batch completion marker 存在；
6. frozen model、scorer、manifest、evaluator hash 通过；
7. 才启动 5ep。

Learned models 不被 evaluator import。每个 episode 完成后才从保存的 chronological
stream 做 counterfactual replay，`control_effect="none"`。

### 与对话解耦证据

两个任务均由用户级 systemd 管理：

- 30ep MainPID 40956，PPID 1859 (`systemd --user`)；
- shadow5 queue MainPID 118346，PPID 1859；
- 两者独立 SID/PGID，无 TTY；
- 各自在独立 systemd cgroup；
- `teambruce` 的 `Linger=yes`。

因此关闭 Codex 对话、terminal 或 SSH 不会停止两项任务。它们是 transient user
units，不承诺跨整机重启恢复。

冻结快照：

- [runtime_status/active50_partial_summary_20260729.tsv](runtime_status/active50_partial_summary_20260729.tsv)
- [runtime_status/promotion_shadow_30ep_partial_summary_20260729.tsv](runtime_status/promotion_shadow_30ep_partial_summary_20260729.tsv)
- [runtime_status/shadow5_queue_snapshot_20260729.log](runtime_status/shadow5_queue_snapshot_20260729.log)

## 五、代码和数据目录

```text
data/v1/                 完整压缩训练数据、episode provenance、split、audit
models/v1/               两个 frozen joblib artifact
reports/v1/              完整训练和 calibration 报告
tools/                   dataset build/audit
training/                causal features、训练、finalize
tests/                   dataset/feature tests
runtime_shadow/          30ep runner、5ep runner、postepisode scorer、queue
runtime_status/          当天停止点/运行点冻结快照
```

今天没有把新模型接入 active evaluator，也没有修改正在运行的 evaluator。
所有训练、评分和队列工作均在保存数据或隔离 shadow 路径完成。

## 六、后续入口

具体执行顺序和接受门槛见 [NEXT_STEPS.md](NEXT_STEPS.md)。

最短结论：

1. 保留 V1.1 作为 ICP observation-quality model；
2. anchor-transition model 先解决“报警后怎样恢复 identity”；
3. terminal model 先作为 arrived/boundary/far 概率传感器；
4. 两个模型均不得因单次输出获得不可逆 promotion/skip/stop authority；
5. 先完成 30ep 和 unseen 5ep shadow，再决定第二版数据和模型。
