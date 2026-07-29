# Next steps and acceptance gates

## Phase 1：完成已运行的 30ep

1. 不修改或重启当前 promotion-shadow。
2. 完成后检查 exact 30ep coverage、invalid episodes 和 completion marker。
3. 评价 promotion model 时同时报告：
   - per-row precision/recall；
   - per-dwell transition；
   - false quarantine；
   - false promotion；
   - longest predicted intervention streak；
   - 已成功 episode 的反事实回归风险。

## Phase 2：运行 unseen prospective shadow5

Episodes：

`319, 498, 295, 430, 1008`

每集报告：

- anchor-transition balanced accuracy/macro F1；
- contiguous dwell-level error；
- oracle target 是否在 historical candidates；
- predicted rebase/rollback/skip 的时间位置；
- terminal arrived/boundary/far confusion；
- false-arrived，尤其 true-far false-arrived；
- uncertain fraction；
- 与历史 deterministic policy 的分歧；
- `control_effect=none` 证明。

五集只用于验证 runtime feature reconstruction 和初步 distribution shift，
不用于宣称模型可 active 接管。

## Phase 3：Anchor model v2 数据改进

### Wider-candidate replay

对保存的 anchors 和 replay frames 离线运行更宽候选集合，提升当前 28.2% 的
oracle-target candidate coverage。至少记录：

- current-2/current-1/current/current+1；
- quarantine 后候选；
- sequence model 提出的 rebase neighborhood；
- top-K ICP basins，而不只生产路径保留的 candidate。

### Sequence objective

从逐行分类转向：

- transition cost；
- monotonicity；
- maximum dwell；
- rollback/rebase hysteresis；
- movement-conditioned identity change；
- wrong-state duration。

### Acceptance gate

进入 advisory active 前至少满足：

1. scene-held-out balanced accuracy >=0.80；
2. 每个 held-out scene 单独报告，不只 pooled；
3. false multi-hop transition 明显低于 deterministic baseline；
4. 成功 episode 上不增加最长 hint-starvation；
5. oracle target absent 时能够 abstain/rebase，而不是强行 closed-set 选择；
6. shadow 中没有单次错误形成持续 state cascade。

## Phase 4：Terminal model v2

### 数据

- 增加 boundary 样本；
- oversample 已进入 arrived band 但没有停车的 episode；
- 加入连续 STOP、freshness、A0 evidence、motion/stationary sequence；
- 分开“到达但无 STOP”和“STOP 被 veto”；
- 保留 route distance 作为 label，不进入 runtime features。

### Policy

模型输出仅作为概率：

- high-confidence far：允许保守 reject；
- boundary/uncertain：进入 bounded verify；
- high-confidence arrived：仍需 sequence confirmation 和独立 freshness；
- stale/multi-hop evidence：无不可逆 authority。

### Acceptance gate

任何 stop authority 前至少满足：

1. 所有 held-out scenes 的 true-far false-arrived = 0；
2. prospective shadow 的 true-far false-arrived = 0；
3. arrived confirmation 需要连续多帧，不接受单帧；
4. boundary 保持 verify，不强制 accept/reject；
5. ep88 类 arrived-but-no-stop 的 recall 显著改善；
6. ep19/93/205/268 类 far case 不增加错误 STOP；
7. terminal confirmation 期间 stuck recovery 不与 STOP 意图对抗。

当前 v1 在 test scene 有 13 个 true-far false-arrived，明确不通过。

## Phase 5：分级接管

推荐顺序：

1. postepisode replay shadow；
2. online read-only shadow；
3. advisory log beside deterministic controller；
4. reversible action only：
   - hold one transition；
   - request bounded candidate expansion；
   - enter verify；
5. paired canary；
6. frozen paired 30/50ep；
7. 只有通过安全门槛后才讨论 promotion/stop authority。

Anchor 和 terminal 不应同时首次 active。先单独验证 anchor liveness，再单独验证
terminal safety，最后才做联合策略。

## Primary end-to-end metrics

最终判断不能只看 row accuracy，至少包括：

- outbound-success 后的 strict return-stop success；
- endpoint truth arrival；
- arrived-without-stop；
- false stop outside route terminal corridor；
- maximum consecutive hint starvation；
- wrong-anchor dwell duration；
- recovery success；
- invalid/infra rate；
- same-episode paired outcome；
- scene-level confidence interval。

## Stop condition

若 shadow 表明：

- anchor model 的错误会产生持续身份级联；或
- terminal model 在任何新 scene 上出现 true-far false-arrived；

则保持 shadow，回到数据/特征/校准，不启用 active authority。
