# 2026-07-29：三模型 read-only shadow30 启动记录

## 状态

2026-07-29 21:44:39 BST 已启动：

```text
navila-three-model-readonly-shadow30-20260729.service
```

该 unit 是 detached user-systemd transient service，位于独立 cgroup。启动检查时：

- RTX 4090 free memory 24,018MiB，utilization 0%；
- 旧 promotion-shadow 与 learned shadow5 unit 均 inactive；
- 无遗留 `round_trip_eval.py` 或 VLM server；
- `/mnt/SSD4T` 可用空间约 2.0TB。

当前先运行 ep670 canary。只有 canary 完成后能够被四个冻结 scorer 正常评分，
且 summary 明确 `control_effect=none`，才会自动启动剩余 29 episodes。

## Cohort

- 30 个 unique physical episodes；
- 9 个 scenes；
- 与 `data/v1/episodes.jsonl` 训练 corpus 零重叠；
- 与旧 prospective 5ep（319、498、295、430、1008）零重叠；
- manifest：
  `/home/teambruce/navila-anchor-terminal-training-data-20260729/runtime_shadow/three_model_shadow30.tsv`。

Canary：

```text
670 / X7HyMhZNoso
```

## 冻结模型

| Task | Artifact SHA-256 |
|---|---|
| Anchor transition v1 | `4d37f9bcb341f093d4cdc87e92c041db7d582a912acdb629963039cf7b27dc55` |
| Terminal robust v2 | `f033696bf632134c48edf3ce1734850833c98a93bfdadc7173780ef5ebef6bbb` |
| Hint v1 high-recall comparator | `1851c727534f943396c7f74ec6b47f8da0695753cb0edc17fd957cdc532f03ca` |
| Hint binary v2 conservative comparator | `567e24aef5036e3310a36a8333ab8cc40ee467a293506973fa544fb1baa49603` |

模型不被 evaluator import。每个 episode process 退出后才从保存 capture
重建 causal features 并评分。

## 控制隔离

Evaluator 使用 2026-07-28 authoritative candidate：

```text
/home/teambruce/navila-reliability-v1_1-anchor-support-recovery-20260728/
policy_v2_live_candidate/scripts/round_trip_eval.py
```

SHA-256：

```text
fd6ef129dda486d5f93fffd3c21890524f4a89afffcb7aa397b43a004803d997
```

以下 consumer 全部为 `off`：

- V1.1 consumer；
- derived evidence；
- integrated promotion；
- integrated anchor state；
- candidate selector/controller；
- active scan plan；
- anchor support recovery。

因此学习模型输出没有 promotion、rebase、hint movement 或 STOP authority。

## 运行入口

Service：

```bash
systemctl --user status \
  navila-three-model-readonly-shadow30-20260729.service
```

Orchestrator log：

```text
/home/teambruce/navila-anchor-terminal-training-data-20260729/
runtime_shadow/runs/three_model_shadow30_20260729/orchestrator.log
```

Canary batch log：

```text
/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/
batch_logs/three_model_readonly_shadow30_canary_20260729/batch.log
```

每个可评分 result 生成：

```text
three_model_readonly_shadow_summary.json
```

该 summary 同时记录 Anchor、Terminal、Hint v1/v2、clearance 分布及
`control_effect=none`。
