# C 部分：方法冻结时间线核查

**执行者说明**：本报告由主会话（非独立 fork）直接执行并撰写，只读操作，未修改任何代码/日志文件。

## 0. 仓库定位

- `/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench` 本身就是一个 git 仓库（`git rev-parse --is-inside-work-tree` → `true`）。
- 其父目录 `/mnt/SSD4T/teambruce/projects/navila-isaac/` **不是** git 仓库（`fatal: not a git repository`）。
- 结论：四个关键文件（`scripts/hint_action_arbiter.py`、`scripts/route_memory_agent.py`、`scripts/stop_gate.py`、`scripts/round_trip_eval.py`）位于 `NaVILA-Bench` 这一个自包含 git 仓库内。

## 1. `git log --follow` 结果（关键发现：git 历史对本次审计基本不可用）

```
$ git log --follow -1 --format='%H | %ai | %s' -- scripts/hint_action_arbiter.py
(无输出 — 该文件从未被 git 追踪)

$ git log --follow -1 --format='%H | %ai | %s' -- scripts/route_memory_agent.py
3bfdd13549a34e44278d7b504275a80d3089b917 | 2026-06-29 17:18:44 +0100 | Document direct oracle route-anchor experiments

$ git log --follow -1 --format='%H | %ai | %s' -- scripts/stop_gate.py
(无输出 — 该文件从未被 git 追踪)

$ git log --follow -1 --format='%H | %ai | %s' -- scripts/round_trip_eval.py
3bfdd13549a34e44278d7b504275a80d3089b917 | 2026-06-29 17:18:44 +0100 | Document direct oracle route-anchor experiments
```

`git status --short` 交叉核实：

```
 M scripts/round_trip_eval.py      (相对 06-29 那次提交，本地有未提交修改)
 M scripts/route_memory_agent.py   (同上)
?? scripts/hint_action_arbiter.py  (从未纳入版本控制，untracked)
?? scripts/stop_gate.py            (从未纳入版本控制，untracked)
```

`git diff --stat` 显示未提交修改的规模：`round_trip_eval.py` +3878/-249（相对06-29提交），`route_memory_agent.py` +3342（此数字含在同一 diff --stat 输出内，两文件合计 6971 行插入/249 行删除）。

**这是本部分最重要的结论**：`git log` 无法用来回答"参数在这三批实验之前还是之后被冻结"——`hint_action_arbiter.py`/`stop_gate.py` 从未提交过（git 里完全没有它们的历史），`route_memory_agent.py`/`round_trip_eval.py` 唯一的一次提交停留在 2026-06-29，之后所有改动（包括整个 08-01 到 08-16 期间文档记录的全部机制新增/修复）都只存在于工作区，从未 commit。因此本部分改用文件系统 mtime + 已有调查文档的交叉印证作为替代方法（见下）。

## 2. 三批目标 run 的实际起始时间

采用 `batch.log` 首行时间戳作为权威来源（而非目录 mtime 或内部文件最早 mtime）——原因：`batch.log` 首行是启动脚本自己写入的时间戳，直接对应"批次开始执行"这一事件本身；目录 mtime 和内部文件 mtime 会被后续任何一集的写入持续刷新，不能代表起始时刻，只能作为交叉校验（三者在本例中一致，见下表，故不构成分歧）。

| 批次 | `batch.log` 首行时间戳 | 目录内最早文件 mtime（交叉校验） |
|---|---|---|
| `pure_oracle_hint_highsuccess100ep_20260811` (oracle_hint) | **2026-08-11T23:22:06+01:00** | `ep5_vlm.log` @ 2026-08-11 22:22:14 UTC（对应+01:00即23:22，一致） |
| `pure_oracle_hint_action_highsuccess100ep_20260812` (oracle_hint_action) | **2026-08-12T14:33:53+01:00** | `ep5_vlm.log`（一致） |
| `pure_oracle_hint_action_stopgate_highsuccess100ep_20260813` (oracle_hint_action_stop) | **2026-08-13T09:10:37+01:00** | `ep5_vlm.log`（一致） |

## 3. 冻结判断：参数集在这三批实验之后仍被大幅修改

四个文件当前（撰写本报告时，2026-08-17）的 mtime：

| 文件 | 当前 mtime |
|---|---|
| `scripts/hint_action_arbiter.py` | 2026-08-16 10:21:42 +0100 |
| `scripts/route_memory_agent.py` | 2026-08-15 18:37:21 +0100 |
| `scripts/stop_gate.py` | 2026-08-15 10:36:58 +0100 |
| `scripts/round_trip_eval.py` | 2026-08-15 18:37:16 +0100 |

**四个文件的当前 mtime 全部晚于三批实验的起始时间（最晚一批 08-13 09:10）**——即从纯 mtime 角度看，参数集是在这三批实验**之后**才最后一次被修改的，不满足"实验前已冻结"。

**但需要更细致的判断**：mtime 只能证明文件"被碰过"，不能证明**这三批实验实际用到的那些参数**本身发生了变化。逐一核实：

- **`hint_action_arbiter.py`**：文件内可读到的最新改动均带有明确的日期注释，且全部属于**新增、默认关闭（`False`）的可选开关**：`stop_veto_enabled`（2026-08-03 引入，见 `hint_action_arbiter.py:57`）、`turn_override_completes_full_angle`（2026-08-15 引入，`hint_action_arbiter.py:94`）、`trend_confidence_enabled`（2026-08-15 引入，`hint_action_arbiter.py:117`，其内部逻辑 `_trend_confidence_trusts` 已于 **2026-08-16** 被硬编码 `return False` 短路禁用，见 `hint_action_arbiter.py:357`）。这些字段在三批目标实验运行时**根本不存在于代码里**（三批实验分别跑于 08-11/08-12/08-13，晚于 08-15/08-16 才引入的字段自然不可能被那三批用到）。核心判据函数 `_conflicts_with_hint`（A1 用到的冲突判定）、`_desired_kind`（A2 分箱）、`min_anchor_distance_m` 默认值 0.35（A3）等在文件里没有找到任何标注了 08-11 之后日期的修改痕迹——但由于没有 git 历史，**无法 100% 排除**这些具体常量本身在 08-13～08-16 间被静默改过又未留注释。
- **`route_memory_agent.py` / `round_trip_eval.py`**：本节审计范围内未见足够信息确定具体哪些字段在 08-11～08-16 间发生变化（本报告未逐字段比对这两个文件的历史版本，因为没有 git 历史可 diff，也没找到这两个文件在 08-11 之前的归档快照）。**标注为 NOT FOUND**：具体是否有影响到三批目标实验参数的改动，已搜索：git log（无历史）、`scripts/backup_*` 目录（见第4节，未含这两个文件 08-11 前后的快照）。

**结论（如实回答"之前还是之后"）**：**无法用严格的"冻结时间点"给出干净的之前/之后判断**——因为版本控制缺失，真正能确认的是：(a) 三批实验的 argv 配置本身（见第4节）在三批之间只有计划内的、消融链意图之内的差异，没有意外差异；(b) `hint_action_arbiter.py` 里可归因到具体日期的改动全部标注为 08-15/08-16（晚于三批实验），且全部是新增的、默认关闭的开关，不会追溯性影响已经跑完的三批；(c) 但对于**未标注日期的既有常量**（如 `forward_cone_deg=15.0`、`stop_gate` 的四个子阈值等）是否在 08-11～08-16 间发生过静默修改，本次审计**找不到可验证的证据链**（NOT FOUND，已搜索：git log --follow 对全部四个文件、`scripts/backup_*` 目录、三批各自 eval_log 的 argv dump——argv dump 只能证明 CLI 层面传参一致，不能证明 dataclass 默认值本身没变）。

## 4. 配置快照对比（三批实验的完整 argv dump）

三批各自 `ep5_eval.log` 均在 "Passing the following args to the base kit application:" 这一行完整记录了实际传给评测程序的全部 CLI 参数（这就是本次审计能找到的、最接近"config 快照"的东西——未发现独立的 `args.json` 或专门的 config dump 文件）。三批完整对比：

| flag | oracle_hint (08-11) | oracle_hint_action (08-12) | oracle_hint_action_stop (08-13) |
|---|---|---|---|
| `--route_memory` | ✓ | ✓ | ✓ |
| `--route_hint_mode=compact` | ✓ | ✓ | ✓ |
| `--route_hint_source=oracle` | ✓ | ✓ | ✓ |
| `--route_relocalization_backend=none` | ✓ | ✓ | ✓ |
| `--topdown_route_map` | ✗ | ✓（新增） | ✓ |
| `--hint_action_arbiter` | ✗ | ✓（新增） | ✓ |
| `--stop_gate` | ✗ | ✗ | ✓（新增） |
| `--stop_gate_r_in=3.0` | ✗ | ✗ | ✓ |
| `--stop_gate_r_out=3.0` | ✗ | ✗ | ✓ |
| `--stop_gate_confirm_steps=3` | ✗ | ✗ | ✓ |
| `--stop_gate_min_confidence=0.5` | ✗ | ✗ | ✓ |

三批之间**没有任何非计划内的差异**——每一步新增的 flag 都精确对应消融链的设计意图（`oracle_hint → +hint_action_arbiter/topdown_route_map → +stop_gate`），没有发现意外的参数漂移。`--oracle_align_return_yaw_to_anchor_segment` 三批均未出现（与 README 第4/7/8节的说明一致）。

原始 argv（供核对，来自各自 `ep5_eval.log:229`）：

```
oracle_hint: ['--task=go2_matterport_vision', '--num_envs=1', '--history_length=9', '--load_run=2024-09-25_23-22-02', '--headless', '--enable_cameras', '--round_trip_mode=phase_prompt', '--instruction_rewriter_provider=cache_only', '--vlm_port=54326', '--episode_idx=5', '--result_suffix=pure_oracle_hint_highsuccess100ep_20260811_ep5', '--route_memory', '--route_hint_mode=compact', '--route_hint_source=oracle', '--route_relocalization_backend=none']

oracle_hint_action: [...同上...] + '--topdown_route_map', '--hint_action_arbiter']

oracle_hint_action_stop: [...同上（含 topdown/hint_action_arbiter）...] + '--stop_gate', '--stop_gate_r_in=3.0', '--stop_gate_r_out=3.0', '--stop_gate_confirm_steps=3', '--stop_gate_min_confidence=0.5']
```

## 5. 独立的 dev/tuning 子集检查

**状态：FOUND（否定结果）**——未找到与 High-success-100（`investigations/数据补全/code/high_outbound_success_100ep_selection.tsv`，100 个 `episode_idx`）不重叠的独立调参子集。

搜索方法与结果：
- grep 全部 `scripts/*.py`（非 backup_*）查找 `dev_set`/`tuning_set`/`held_out`/`holdout`/`dev_episodes`/`calibration_set` 等命名——无匹配。
- 找到两个 08-15 冒烟测试脚本使用 `ONLY_EPISODES` 机制跑小样本验证新代码：
  - `run_line2_v11veto_turngate_trendconf_smoke_20260815.sh:106`：`ONLY_EPISODES="${ONLY_EPISODES:-264 646 484}"`（默认这3个 episode_idx）
  - `run_line2_closure_cooldown_smoke_20260815.sh`：`ONLY_EPISODES` 有定义但默认值为空（由外部传入）
- 核实这3个 episode_idx（264/646/484）**全部包含在 High-success-100 的 100 个 episode_idx 之内**（直接从 `high_outbound_success_100ep_selection.tsv` 第5列比对，三个都命中）。

**结论**：本次审计范围内，代码改动的冒烟验证用的正是 High-success-100 manifest 里的样本，不存在独立于该 manifest 之外的专用调参集。**需要提醒**：这意味着 08-15 起新增的三处修复（`v11_quarantine_veto`/`turn_override_completes_full_angle`/`trend_confidence`）是直接观察 High-success-100 manifest 本身的失败案例（如 ep646、ep889）来设计和验证的——如果论文后续要用同一份 manifest 报告这些新机制的效果，需要如实说明这一层"在同一测试集上诊断+修复"的方法论关系（不过这些新机制默认关闭，未影响本报告审计的三批 oracle 系列实验）。

## 未能完成 / 局限性说明

- 无法排除 `hint_action_arbiter.py`/`route_memory_agent.py`/`round_trip_eval.py` 中**未标注日期注释**的既有数值常量在 08-11～08-16 间被静默修改又未留痕——根本原因是这三个文件里有两个从未进入 git 版本控制、另外两个的最后一次提交停在 06-29，之后的全部修改历史只存在于当前工作区快照里，没有任何中间版本可比对。
- 未找到任何独立的 `args.json` 式结构化 config dump 文件；本报告用 eval_log 里的 argv 文本行作为"配置快照"的替代来源，这只覆盖 CLI 层面的显式 flag，不覆盖 dataclass 里未通过 CLI 暴露的默认值（例如 `hint_action_arbiter.py` 里 `forward_cone_deg`/`min_anchor_distance_m` 等这类硬编码常量）。
