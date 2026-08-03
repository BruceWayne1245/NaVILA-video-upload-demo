# 2026-07-29 findings

## 1. 主要模型没有“从 60% 训练坏到 20%”

历史成功率是系统级、不同 cohort、不同停止定义下的结果，不是 V1.1
分类准确率。今天完成的配对复算说明：

- Route2 在当前 Active-50 前缀上为 2/10=20%；
- 同一 Route2 完整有效 batch 为 20/36=55.6%；
- 当前 Active-50 前缀为 3/11=27.3%。

所以批次顺序和小分母可以让同一系统先显示 20%，最后显示约 56%。

但这不表示系统没有真实退化。真实退化集中在模型输出怎样被 consumer 使用。

## 2. 已证实的控制层失配

### Detector 被当成 negative classifier

`jointly_trusted=false` 包含 uncertain/abstain，不等于确定 bad。早期 integrated
controller 曾将其累计为 quarantine 负票，造成 false quarantine。后续改成
`p_pose_bad>=0.90` 的三值逻辑后，ep5 的 anchor12 误杀消失。

### Raw candidate 与 stateful hint 语义错位

Active V2 使用 latest raw candidate 的可靠性封禁 Route1 已时序融合的 route-memory
hint。ep5 中 29 个被拒绝的 usable hints 里，仅 7 个 raw candidate 也正确，
另外 22 个是 raw candidate 错但 stateful hint 对。

这说明必须分别建模：

1. raw ICP candidate reliability；
2. stateful integrated hint reliability；
3. derived one-hop hint reliability。

### 只会拒绝，不能恢复

V1.1 正确发现 current/next 都坏时，旧 active path 请求 scan；scan executor
不存在，controller 随即 disabled。之后 legacy state 继续冻结/跳过，形成
hint starvation。

### Correlated evidence 被当成独立 corroboration

错误 anchor identity 同时影响 promotion、bearing hint、route distance 和 stop。
这不是多份独立证据，而是同一个错误源在多个 consumer 上重复出现。

## 3. Terminal 失败不是一个阈值问题

已观察到至少四类：

1. `deferred` 被 caller 当作 pass-through，导致远处 STOP 穿透；
2. `accepted` 路径绕过 V2，模型已报警也无法拦截；
3. stale/multi-hop derived evidence 无限 veto 正确 STOP；
4. 进入 terminal 区域时没有 latch，机器人到家后再次漂走。

7/28 terminal state machine 已修复这些已知 wiring 问题，并增加：

- current/rear support 与 next/forward guidance 分离；
- bounded alternating support recovery；
- pre-STOP 和 post-STOP terminal blindness budget；
- freshness、hop 和 source 约束；
- `safe_fail` 而不是不确定 STOP 穿透。

今天没有再次修改这套 active evaluator。今天的工作是在其保存数据上建立监督集和
learned shadow。

## 4. 当前 Active-50 的 7+1 分类

严格以 oracle return-route distance 复算：

- 7 个失败从未进入 arrived band；
- ep88 进入 arrived band，但 terminal state 最终为 safe_fail；
- ep88 说明“减少错误停止”已经转化为“缺少可靠正证据时不停车”的 liveness 风险。

这正是 terminal model 的目标，但 terminal v1 尚不能接管：

- boundary 样本只有 365 行；
- validation 选出的 zero-FP threshold 在 test scene 产生 16 false arrived；
- 13 个 false arrived 实际为 far。

## 5. 两个新模型的真实含义

### Anchor-transition model

它不是直接挑选任意 anchor 的完整 selector。当前历史 candidate coverage 只有
28.2%，因此它首先是一个：

- hold/advance/rollback/rebase state transition model；
- “当前身份需要恢复”检测器；
- 后续 wider-candidate selector 的前置状态模型。

### Terminal-decision model

它首先输出 `arrived/boundary/far` probabilities。`accept/reject/verify/continue`
仍应由外部 policy 结合 freshness、sequence confirmation 和几何安全边界决定。

## 6. 当前最可信的总体架构

```text
raw ICP / vision / motion
        │
        ▼
V1.1 observation-quality model
        │
        ▼
anchor-transition sequence model
        │
        ├── trusted stateful route hint
        ├── bounded candidate expansion/rebase
        └── abstain / safe recovery

independent A0 / route-distance / VLM STOP / freshness
        │
        ▼
terminal arrived-boundary-far model
        │
        ▼
deterministic accept / verify / reject policy
```

任何单个模型的一次预测都不应同时控制 anchor identity、导航方向和停车。
