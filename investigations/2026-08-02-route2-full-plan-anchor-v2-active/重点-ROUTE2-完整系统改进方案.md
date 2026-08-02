# 【重点】Route 2 完整系统改进方案

日期：2026-08-02

> 本文是 Route 2 后续工作的长期基准方案。除非项目负责人明确批准变更，后续实现、训练、测试和上线都必须按本文的顺序和边界进行；不得因为短期指标或单次失败而跳过阶段、同时改动多个模型，或重新启用已否决的设计。

## 总体目标

在保持可解释安全边界、自动监督和可回滚能力的前提下，逐步提高 return 成功率、anchor 状态正确率、有效数据采集率和整条路线的连续运行稳定性。所有学习模型都必须通过因果 replay、独立 locked cohort 和小规模 active canary，不能仅凭离线数值直接替换生产逻辑。

## 固定架构

```text
ICP / A0 / VLM / action-integrated motion
              ↓
Reliability V1.1 + dependency health
       pose / bearing / distance
              ↓
Temporal Route Belief (TRB)
 anchor/home posterior, age, contradiction,
 motion, OOD and abstention state
        ↙          ↓          ↘
Anchor V2 active  Hint split  Terminal sequence
              ↓
       deterministic safety executor
```

### 不可改变的权责边界

- Reliability V1.1 保持冻结，是唯一的 ICP-derived reliability authority。Pose 只能授权 Anchor evidence，bearing 只能授权 Hint evidence，distance 只能授权 Terminal evidence。
- 原始 ICP quality/confidence 不得绕过 V1.1 直接授权下游动作。
- Anchor V2 full-active 自己决定 promotion、hold 和 recovery；确定性代码只负责索引/拓扑合法性、schema/artifact 完整性、有限恢复、振荡保护、kill-switch 和安全失败。
- Hint 在重建完成前继续使用重训前的 Hint Core V1；重训后的 Hint V2 不上线。
- Terminal V2 保持 shadow-only；确定性 Terminal state machine 保留 STOP 权限，Terminal 最后激活。

## 分阶段执行顺序

### 阶段 0：基础设施和监督（持续执行）

统一 3600 秒 episode timeout；卡死后按监督策略 kill 并继续队列。记录 OOD、missing、stale、head contradiction、abstention reason、候选耗尽、最长 dwell、恢复耗时和进程衔接状态。每次 active 改动都必须有显式 activation switch、counterfactual 日志、自动回滚和 kill-switch。

### 阶段 1：Anchor V2 full-active（当前阶段）

先只启用 Anchor V2，不同时改 TRB、Hint、Terminal。用小规模 wiring canary 和随后独立 prospective cohort 验证：return 成功率、anchor exact/off-by-one/off-by-two、false advance/rollback、harmful catch、safe delay、dwell/freeze、recovery、oscillation、Anchor0 reach、outbound 完成率和数据完整性。

只有当 active 结果稳定优于现有 hard-coding，且没有不可接受的恢复/衔接风险时，才能进入下一阶段。locked cohort 只用于评估，不得反向选阈值。

### 阶段 2：Temporal Route Belief（TRB）

在 Anchor active 的行为和日志稳定后，引入显式的时间路线信念层，融合 anchor/home posterior、证据年龄、矛盾头、运动状态、OOD 和依赖健康。先 shadow，再小规模 active；不得与 Hint/Terminal 同批首发。

### 阶段 3：Hint 重建

围绕最终 stateful hint event 重新标注，拆成 `direction_supported` 与 `action_beneficial` 两个模型。碰撞/clearance、动作预算、冷却和执行门仍由确定性代码控制。验收同时要求高 precision 和有用 coverage，零动作 abstainer 不算通过；逐步与旧 Hint Core V1 对照。

### 阶段 4：Terminal 重建（最后激活）

从逐行 arrival threshold 改为序列状态：`far → approaching → boundary → verify_home → arrived`，并显式处理 `overshot`、`moved_away`、`safe_fail`。数据集必须包含 matched arrived/boundary/far controls 和可执行 motion；在 prospective 数据上同时达到 zero true-far false arrivals 与有用 arrived recall 后，才可取得 STOP 之外的权限。

## 变更纪律和验收

每个阶段必须单变量、保留 baseline/control、先 replay 后 canary；报告总体和 per-scene 最坏情况，并区分模型决策直接造成的成功/失败。任何阶段若出现安全边界、进程监督、队列衔接或数据完整性问题，立即停止该阶段并使用 kill-switch/回滚，不得顺手修改其他模型掩盖问题。

