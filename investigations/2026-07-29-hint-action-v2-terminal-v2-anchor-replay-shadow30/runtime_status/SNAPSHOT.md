# 三模型 shadow30 运行快照

快照时间：2026-07-29 21:56:52 BST。

## Service

```text
unit=navila-three-model-readonly-shadow30-20260729.service
ActiveState=active
SubState=running
MainPID=170788
ExecMainStartTimestamp=Wed 2026-07-29 21:44:39 BST
```

## 当前进度

- ep670 / scene `X7HyMhZNoso` canary 已启动；
- VLM server 已在 port 58670 ready；
- 归档时 canary 仍在运行；
- `summary.tsv` 尚未产生已完成 episode 行；
- 因此剩余 29 episodes 尚未被 canary gate 放行；
- 不能把这一状态解释为 canary pass 或 shadow30 complete。

## GPU 快照

```text
memory.used=20607 MiB
memory.free=3464 MiB
utilization.gpu=50%
```

启动前 GPU 快照为 free 24,018MiB、utilization 0%。当前资源变化与 canary
evaluator/VLM 正在运行相符。

## 隔离

- 四个模型仅在 episode 结束后读取保存的 capture；
- evaluator 不 import 学习模型；
- V1.1 consumer、promotion、rebase、movement override、STOP authority 均关闭；
- 每个成功 summary 必须写出 `control_effect=none`；
- canary 失败会停止 batch，不会自动绕过。

## 保存的运行证据

- `provenance.txt`：模型、runner、evaluator、cohort 哈希；
- `orchestrator_at_2026-07-29T21-56-52+01-00.log`：归档时的 orchestrator
  日志快照；
- 完整 live log 仍位于训练工作区和 `/mnt/SSD4T`，本文件不伪装为终态报告。
