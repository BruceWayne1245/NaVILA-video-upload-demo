# 2026-07-29 changes and work log

## Analysis

1. 读取 GitHub 最新 `main` 和 7/28 primary handoff。
2. 检查 Active-50 实际 summary、measurement 和 trajectory truth。
3. 统计 stopped Active-50：
   - 12 valid completions；
   - 11 outbound successes；
   - 3 return successes；
   - 8 return failures。
4. 按 oracle return-route distance 将八个失败分为 7 个 never-arrived 和
   1 个 arrived-but-no-stop。
5. 配对复算旧 Route2 在相同 Active-50 前缀上的结果，确认 20% 前缀与
   55.6% 全批可以由同一系统产生。
6. 区分：
   - V1.1 reliability prediction；
   - anchor state mutation；
   - route-hint consumer；
   - terminal stop policy；
   - batch/cohort/metric effects。

## Runtime operations

1. Active-50 在 ep344 第二次 attempt 确认不可逆后停止。
2. 放行原先排队的 promotion-shadow 30ep。
3. 30ep 继续使用 detached user-systemd service。
4. 创建 learned anchor/terminal shadow5 队列，严格排在 30ep 后。
5. 验证两项任务：
   - PPID 为 `systemd --user`；
   - 独立 SID/PGID；
   - 无 TTY；
   - 独立 cgroup；
   - user linger enabled。

## Dataset implementation

新增：

- `tools/build_training_datasets.py`
- `tools/audit_training_datasets.py`
- `tests/test_build_training_datasets.py`
- `tests/test_model_features.py`

主要实现：

- 自动发现保存的 evaluator captures；
- SHA-256 trajectory dedup；
- episode/scene provenance；
- attempt 到 trajectory step 的 exact 或显式 approximate alignment；
- return path polyline 的 temporal dynamic-programming alignment；
- oracle current/next anchor 和 route-distance labels；
- scene-disjoint splits；
- runtime-safe input 与 supervision-only truth 分离；
- oracle/Isaac source 输入审计；
- class balance、candidate coverage、corruption exclusions。

## Model implementation

新增：

- `training/model_features.py`
- `training/train_models.py`
- `training/finalize_training.py`
- `training/run_training.sh`

主要实现：

- causal feature state；
- 明确禁止 label/oracle fields 进入 runtime feature；
- HistGradientBoosting 多分类模型；
- sample/class weighting；
- temperature calibration；
- scene-level metrics；
- weighted confusion matrices；
- artifact dataset-hash binding；
- joblib reload/feature-count validation；
- terminal diagnostic threshold evaluation。

## Prospective shadow implementation

新增：

- `runtime_shadow/prospective_5ep.tsv`
- `runtime_shadow/score_episode.py`
- `runtime_shadow/run_prospective_shadow_5ep.sh`
- `runtime_shadow/wait_for_promotion30_then_shadow5.sh`

行为边界：

- 5 个 episode 不在训练 corpus；
- evaluator 不 import learned model；
- 每集完成后才评分；
- prediction 记录 `control_effect="none"`；
- terminal threshold 没有 stop authority；
- frozen hashes fail closed；
- 30ep completion markers 和 GPU settle window fail closed。

## Files deliberately not copied

- 数 GB 的 raw simulator/VLM/evaluator logs；
- RGB、depth、point-cloud arrays；
- Python `__pycache__`；
- transient systemd unit files；
- 任何 GitHub credential/token。

训练行保留 source path 和 SHA-256，可回到原始 capture 复核。
