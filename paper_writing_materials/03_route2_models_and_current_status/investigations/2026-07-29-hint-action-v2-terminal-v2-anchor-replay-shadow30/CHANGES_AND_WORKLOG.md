# 2026-07-29 工作记录与改动清单

## 数据与标签

- 新建 Hint-action supervised dataset；
- STOP rows 排除，oracle-source rows 排除；
- oracle 只用于监督标签，不进入 inference features；
- 保存 3,991-row 压缩数据、audit、episodes 和 scene split provenance；
- 对 ep319 两处损坏采用只读、内存级兼容解析，未修改 capture。

## 模型与特征

- 训练 Hint v1 三分类模型；
- 训练 Hint robust v2 三分类模型；
- 训练 Hint binary v2 advisory 模型；
- Hint v2 加入 circular angles、gap reset、motion response、temporal agreement；
- Hint v2 移除 absolute anchor indices；
- clear-path 从方向模型中分离，保留为 execution clearance；
- 训练 Terminal v2 与 robust v2；
- Terminal robust v2 移除 absolute source/target/anchor indices；
- 用 leave-one-scene-out 预测冻结 threshold/streak。

## Anchor replay

- 实现 authoritative wider-candidate ICP replay；
- 不注入 oracle candidate；
- 支持 deterministic episode sharding；
- 增加 selection fingerprint，防止错误 resume；
- 完成九场景 pilot 与 8-episode 4-way sampled shards；
- 完成单行端到端 smoke replay。

## Scoring 与报告

- 完成旧 gate、Hint v1、Hint robust v2、Hint binary v2 的 5ep 对照；
- 完成 Terminal v2/robust v2 的 held-out 与 5ep 对照；
- 修正 Hint v1 unseen 5ep pooled recall 的算术记录为 0.6429；
- 输出 JSON 与 Markdown 双格式报告；
- 所有 scorer 明确写入 `control_effect=none`。

## 测试与校验

- 20 个 unit tests 通过；
- 所有 joblib artifact 可加载；
- 报告 strict JSON validation 通过；
- wider-candidate scorer smoke 通过；
- 未修改 active evaluator 或已有 capture。

## 在线 read-only shadow

- 构建 30-episode、9-scene cohort；
- 与训练 corpus 零 overlap；
- 与旧 prospective 5ep 零 overlap；
- 冻结 Anchor v1、Terminal robust v2、Hint v1 和 Hint binary v2；
- 使用 detached user-systemd transient service 启动；
- ep670 作为 canary；只有 scoreable、四个 scorer 成功且
  `control_effect=none` 时才继续其余 29 episodes；
- 所有 V1.1 active consumers 保持 `off`。

## 本 GitHub 归档

本目录保存本轮新增数据、模型、报告、代码、测试和启动快照。上一份 investigation
已经保存的 Anchor/Terminal v1 大型基础语料未重复复制，避免无意义扩大仓库；
它们的路径和哈希由相邻 investigation 与本轮 runtime provenance 共同固定。
