# 数据补全 —— oracle_hint / oracle_hint_action 系列消融配置记录

**目的**：为论文补齐缺失的数据点，在 NaVILA(navila-llama3-8b-8f)这条主线上，逐步跑不同配置的 round-trip 批次。本文档记录 2026-08-11/12 围绕 `oracle_hint` → `oracle_hint_action` 消融设计所做的调查和最终决定。

## ⚠️ 默认策略（2026-08-12 起，必须遵守）：数据补全用途的100ep批次默认一律使用高成功率100集

**除非用户就某一批次给出明确的特殊说明，否则往后所有为"数据补全"这个论文数据目的运行的100ep批次，episode manifest 一律默认使用 [第6节](#6-canonical-100-的低-outbound-成功率是历史常态另挑了一份高成功率的-100-集样本) 里挑出的高成功率100集（`code/high_outbound_success_100ep_selection.tsv`，历史加权 outbound 成功率 884/932=94.85%），不再默认使用 7/20 起的 canonical-100 老 manifest。**

**这条规则被明确写在这里，是因为一次真实发生过的代价**：`pure_oracle_hint_action_100ep_20260812` 这一批当初用的是 canonical-100（老manifest），而不是已经在08-11就选好、且已经证明能大幅提高单集有效数据产出率的高成功率100集——结果这份 canonical-100 manifest 本身 outbound 成功率只有 26-43%（这批实测 37/98≈38%），意味着100集里超过六成的 GPU 时间花在 outbound 阶段就失败、根本产不出任何 return-phase 数据的集次上。这批从 2026-08-12 09:11 跑到 14:33 停止，耗时 **约5小时22分钟**，跑完98/100集，但只换来37个 outbound-success（进而只有23个真正可比的 round-trip 结果）——同样的GPU时间如果一开始就用高成功率100集，预期能拿到约94个有效 outbound-success 集，返程阶段的有效样本量会是这批的2.5倍以上。这批被用户在08-12下午发现问题后手动叫停（详见第4节），换成高成功率100集重跑（第7节）。**往后每一批数据补全的默认选集必须直接是高成功率100集，不要重蹈这个覆辙。**

（唯一的例外场景：如果某次调查目的就是"canonical-100 这份老manifest本身的特性"，或用户明确要求要跟 `pure_navila_baseline_100ep_20260810`/`pure_oracle_hint_100ep_20260811` 等历史 canonical-100 批次做逐集对照，才使用 canonical-100——这种情况下必须由用户明确指出，不能默认。）

## 1. 最初跑的批次：`pure_oracle_hint_100ep_20260811`（canonical-100，历史批次）

脚本：`scripts/run_pure_oracle_hint_100ep_20260811.sh`（`RUN_TAG=pure_oracle_hint_100ep_20260811`）

核心 flag：
```
--round_trip_mode=phase_prompt --instruction_rewriter_provider=cache_only
--route_memory --route_hint_mode=compact --route_hint_source=oracle
--route_relocalization_backend=none
```

明确不开：
- `--stop_gate`：oracle hint 的 `relocalization_confidence` 恒为 1.0，`stop_gate.py` 的 `_extract_d_and_conf` 会把任何 oracle 来源的置信度视为满分，一旦距离连续 `confirm_steps` 次落在 `r_in` 内就会被 `FORCED` 路径直接判定返程成功——这样测出来的是 stop_gate 自己的判断，不是 VLM 自己的停止决策。
- `--oracle_align_return_yaw_to_anchor_segment`：会用 ground truth 直接改写机器人返程朝向，是比 hint 文本更强的一层 oracle 介入。
- `--hint_action_arbiter`：这是本篇要讨论的主角，故意留到下一批再加。

这批复现的是 2026-06-29 `direct_oracle_hard_fresh_20260629` 批次的 route-memory flag 组合（已核对该批次自己 eval_log 里的真实 argv），只是把测试集从原来的 hard-11 换成了本项目 7/20 起统一使用的 100-episode canonical set。

**更新（2026-08-11 22:50 BST，批次已跑完）**：100/100集全部完成。本批原始数据：`outbound_success=30/100`，`return_success=9/100`，`round_trip_success=5/100`。按项目既定的 return-rate 分母约定（`round_trip_success` / `outbound_success`——见 `feedback_return_rate_denominator` 记忆），本批原始 return-success 率为 **5/30 ≈ 16.7%**。

这个 30% 的 outbound 成功率经核实是这份 100集 canonical manifest 的历史常态（不是这次配置特有的问题）——见第6节的完整调查。**这份 canonical-100 outbound 成功率长期偏低这件事，正是第0节新增默认策略的直接动机。**

## 2. "4.3%/97%"结论的真实来源（2026-06-30 / 07-01）

项目 README 里反复引用的"hint_action_arbiter 只在 4.3% 的返程决策上介入，却把返程成功率从约50%拉到97%"这个结论，来自两批加总的结果，**都是 NaVILA 本身跑的**，不是后来 08-08 拿来测试跨backbone泛化性的那批 StreamVLN 数据（那批是另一条独立支线，用的是完全不同的VLM/policy，不能跟本项目主线混着比）：

- `stop_gate_r3_hint_arbiter_hard11_20260630`：hard-11 集合，7/7
- `oracle_shadow_loftr_v4_30_return_anchor_fix_20260701`：30集，10/11

两者相加 17/18 = 94.4%（配合同期不开 hint_action_arbiter 的三批 14/28=50% 基线做对照）。30ep 那批 return 阶段一共 348 次决策，180 次已经跟 hint 一致、153 次被 clear-path 检查挡下，**只有15次真正替换了 VLM 输出，15/348≈4.31%≈4.3%**。

**真实 flag 组合**（直接从 `stop_gate_r3_hint_arbiter_hard11_20260630` 的 `ep368_eval.log` 里 `Passing the following args to the base kit application` 这行原始 argv 核对得到，不是凭记忆/文档推测）：

```
--route_memory --route_hint_mode=compact --route_hint_source=oracle
--route_relocalization_backend=none
--oracle_align_return_yaw_to_anchor_segment
--stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0
--stop_gate_confirm_steps=3 --stop_gate_min_confidence=0.5
--topdown_route_map
--hint_action_arbiter
```

30ep 那半（`run_oracle_shadow_loftr_v4_30_batch_20260701.sh`）唯一的差异是 `--route_relocalization_backend=loftr_depth`（而不是 none）——但因为 `route_hint_source=oracle`，真正喂给 VLM 的 hint 数值仍然来自 oracle，这个 backend 只是跑一份非oracle的LoFTR影子重定位做诊断记录（脚本自己的注释写的是"non-oracle LoFTR shadow telemetry"），不影响实际驱动机器人的信号，因此不算一个真正的配置差异。

**结论：历史上 `--hint_action_arbiter` 从未单独跑过**，每一个用到它的历史批次（逐个 grep 过所有同时含 `route_hint_source=oracle` 和 `hint_action_arbiter` 的脚本确认），都是跟 `--oracle_align_return_yaw_to_anchor_segment` + `--stop_gate`(+四个子参数) + `--topdown_route_map` 打包一起出现的。

## 3. `oracle_hint` 批次 vs 4.3%历史来源：完整差异表

| flag | pure_oracle_hint_100ep_20260811 | 4.3%/97%历史来源（06-30/07-01） | 功能说明 |
|---|---|---|---|
| `--route_hint_source=oracle` | 有 | 有 | 相同 |
| `--route_relocalization_backend` | none | none（hard11半）/ loftr_depth（30ep半，仅影子诊断，不影响驱动信号） | 基本相同 |
| `--hint_action_arbiter` | 无 | 有 | 返程时若 VLM 输出的方向与 route hint（记录路线上到下个锚点的方位角）方向性冲突、且 hint 方向经清路检查确认无障碍，就临时替换掉那一步的 VLM 输出（一次一步，不持续接管）|
| `--oracle_align_return_yaw_to_anchor_segment` | 无 | 有 | 直接用 ground truth 改写机器人返程朝向——是对机器人姿态本身的强oracle介入，跟 hint_action_arbiter 不是一回事 |
| `--stop_gate`(+r_in=3.0/r_out=3.0/confirm_steps=3/min_confidence=0.5) | 无 | 有 | 独立判断"什么时候该停/算不算返程成功"的仲裁机制，跟"往哪走"完全正交；oracle恒定置信度1.0会让它绕过VLM自己的停止决策直接判成功，这也是当前 `oracle_hint` 批次一开始就不开它的原因 |
| `--topdown_route_map` | 无 | 有 | 不是独立决策逻辑，只是给 hint_action_arbiter 自己已有的清路检查提供一个俯视地图作为备用数据源（优先用机器人自己的LiDAR局部地图，查不到才退回用这张图）|

## 4. `pure_oracle_hint_action_100ep_20260812`（canonical-100版，已手动停止于98/100，未采纳为最终数据）

脚本：`scripts/run_pure_oracle_hint_action_100ep_20260812.sh`（`RUN_TAG=pure_oracle_hint_action_100ep_20260812`），跟 `pure_oracle_hint_100ep_20260811` 逐行 diff 确认，eval 命令里只多了两行：

```diff
 --route_relocalization_backend=none \
+--topdown_route_map \
+--hint_action_arbiter \
```

**采纳**：`--hint_action_arbiter`（本批要测的核心机制）、`--topdown_route_map`（不是独立机制，只是让 arbiter 的清路检查数据源跟历史批次一样完整，避免因为地图数据缺失而低估 arbiter 的介入率）。

**明确不采纳**：
- `--oracle_align_return_yaw_to_anchor_segment`——跟 hint_action_arbiter 不是同一类机制，混进来会让测不出 hint_action_arbiter 单独的贡献。
- `--stop_gate`（+四个子参数）——同样是独立机制，且历史上排除它的理由（oracle 恒定置信度会让 stop_gate 抢着自己判定成功）在这里同样成立。

episode manifest 用的是 7/20 起的 canonical-100（跟 `pure_oracle_hint_100ep_20260811`/`pure_navila_baseline_100ep_20260810` 完全一致，逐行核对过）——**这是本批的问题所在**，见第0节。

**运行记录**：2026-08-12 09:11 通过 `systemd-run --user` 启动（cgroup 确认在 `user@1006.service/app.slice` 下），到当天 14:33 被用户明确指示手动停止，共运行约5小时22分钟，跑到98/100集（第99集 `episode_idx=290` 被中断，未写入summary.tsv，故有效数据98集）。

**停止前的原始数据（98/100，仅供记录，不建议作为论文最终数字，因未跑满且样本本身低效）**：`outbound_success=37/98`，`round_trip_success`(分母为outbound成功)=**23/37 ≈ 62.2%**。

**停止原因**：用户于08-12下午指出，08-11已经选好且验证过的高成功率100集本应作为这次消融链批次的默认选集，本批却仍沿用了低效的 canonical-100，导致约5.5小时GPU时间里只产出37个有效outbound-success样本（而非预期的约94个）。经用户明确指示（"现在直接把正在跑的这100ep停下来，换成高成功率100ep重新跑，剩下的什么都不变"），该批次被停止，改为第7节的高成功率版本重跑。

## 5. 下下批计划：在此基础上再加 `--stop_gate`

2026-08-12 已确认的下一步计划：等当前批次（第7节，高成功率版 `pure_oracle_hint_action_highsuccess100ep_20260812`）跑完，**在它的基础上再叠加一个变量 `--stop_gate`**（预计沿用历史配置的四个子参数：`--stop_gate_r_in=3.0 --stop_gate_r_out=3.0 --stop_gate_confirm_steps=3 --stop_gate_min_confidence=0.5`），也就是说三批将构成一条逐步叠加的消融链：

```
oracle_hint  →  oracle_hint_action(=oracle_hint + hint_action_arbiter + topdown_route_map)  →  oracle_hint_action + stop_gate
```

`--oracle_align_return_yaw_to_anchor_segment` 目前不在这条链的计划内，暂不添加。**按第0节的新默认策略，这第三批同样应该默认使用高成功率100集，除非用户特别说明要换回 canonical-100。** 第三批已于 2026-08-13 启动，见第8节。

## 6. canonical-100 的低 outbound 成功率是历史常态；另挑了一份高成功率的 100 集样本

`pure_oracle_hint_100ep_20260811` 跑完后 outbound_success 只有 30/100，用户怀疑这份 manifest 是不是本来就难。逐一核对了用同一份 7/20 canonical-100 manifest 跑过的所有历史批次：

| 批次 | outbound_success |
|---|---|
| `canonical_report_next_stopgate_100ep_20260720` | 28/100 = 28% |
| `reliability_fixon_100ep_20260721` | 19/73 = 26%（只完成73集） |
| `reliability_v11_prospective_capture_shadow_100ep_20260722` | 43/100 = 43% |
| `reliability_v11_decision_shadow_rgbd_100ep_20260724` | 38/104 = 36.5% |
| `pure_navila_baseline_100ep_20260810` | 34/100 = 34% |
| `pure_oracle_hint_100ep_20260811` | 30/100 = 30% |
| `pure_oracle_hint_action_100ep_20260812`（第4节，98/100完成） | 37/98 ≈ 38% |

**结论：canonical-100 这份 manifest 从建立以来 outbound 成功率就一直在 26%-43% 区间**，不是配置或hint机制的问题，是这份 episode 采样对 NaVILA 这个 VLM 来说 outbound 阶段本身偏难。**这正是第0节把高成功率100集定为数据补全默认选集的根本原因——用同样的GPU时间，canonical-100只能产出约30-40个有效return-phase样本，高成功率100集能产出约90+个。**

同时确认了项目历史上确实专门挑过高 outbound 成功率的样本——Route2（Codex 那条线）2026-07-25 的 `reliability_v11_policy_v2_active_50ep_outbound_top_20260725`（50集，非100集），实测 outbound_success=36/50=72%。另有两次未竟的类似尝试：`reliable100`（2026-07-30，想选100集"未训练过+可靠"的池子，扫描全部221个候选后发现这个规模下根本不存在这样的池子，被用户叫停，只跑了1集没有真实数据）、`reliable30v3`（2026-07-31，30集，挑选标准是"历史最常完整跑到返程阶段"而非纯outbound率，实测15/34=44%）。

### 新挑选的高 outbound 成功率 100 集样本（2026-08-11）

用户要求"在现有的所有测试中尽可能统计成功率高的"，挑出一份新的 100 集。方法论：

1. 扫描项目 `batch_logs/` 下全部196个批次的 `summary.tsv`（137个有可用的 `episode_id`+`outbound_success` 数据；排除掉 StreamVLN 等没有 `episode_id` 字段的旧格式日志，以及 VLM 启动失败/超时这类 infra 失败行）。
2. 以 `episode_id`（而非 `episode_idx`）为跨批次拼接键——这是项目一直沿用的约定，因为不同批次脚本里 `episode_idx` 只是"这个脚本manifest里的第几个"，不是稳定标识符。额外验证：全部297个出现过的 `episode_id`，其对应的 `episode_idx` 在所有历史批次里**零冲突**——因为 `round_trip_eval.py` 的 `read_episodes()`（定义于 `run_benchmark.py`）只是对固定不变的 `vln_ce_isaac_v1.json.gz`（自6月3日起未变过）做一次性 gzip+json 读取，不做任何打乱/过滤，所以历史 `episode_idx` 可以放心复用来拼新脚本。
3. 按每个 `episode_id` 的历史 outbound 成功率从高到低排序（同分按历史尝试次数排序，优先选证据更充分的），取前100个。

**结果**：264个有历史数据的 episode_id 中选出的这100个，加权历史成功率 **884/932 = 94.85%**（对比 canonical-100 的 26-43%，以及 outbound_top-50 的 72%）。证据强度构成：52个有≥5次历史尝试支撑，20个有2-4次，28个只有1次历史尝试（100%但样本量=1，统计上偏弱，如实标注不隐藏）。跟原 canonical-100 只重叠30个，跟 outbound_top-50 重叠46个（互相印证）。场景分布覆盖项目全部8个场景中的7个，不算集中。

完整100行数据（含 `episode_idx`/`scene`/`neighbor` 等字段，可直接用于拼batch脚本）：[`code/high_outbound_success_100ep_selection.tsv`](code/high_outbound_success_100ep_selection.tsv)。

### 用这份新样本重跑的 oracle_hint 批次

脚本：`scripts/run_pure_oracle_hint_highsuccess100ep_20260811.sh`（`RUN_TAG=pure_oracle_hint_highsuccess100ep_20260811`）。跟 `pure_oracle_hint_100ep_20260811` 的 eval 命令逐字节核对过——flag 完全相同（`--route_memory --route_hint_mode=compact --route_hint_source=oracle --route_relocalization_backend=none`，同样不开 stop_gate/oracle_align_yaw/hint_action_arbiter），**唯一变量是换成了上面这份高成功率的100集**。

2026-08-11 23:22 BST 通过 `systemd-run --user`（`--unit=navila-oracle-hint-highsuccess100ep-20260811`）启动，cgroup 确认在 `user@1006.service/app.slice` 下（非 `session-*.scope`），配合已开启的 `loginctl enable-linger`，SSH断开/对话结束都不影响运行。结果落在 `NaVILA-Bench/batch_logs/pure_oracle_hint_highsuccess100ep_20260811/summary.tsv`。

**注意：这批数据因为换了 episode 样本，跟 canonical-100 系列（baseline / oracle_hint / oracle_hint_action）不能做逐集比较**，只能单独作为"同样的oracle_hint配置，在更容易outbound成功的样本上表现如何"来看。

## 7. 当前正在跑的批次：`pure_oracle_hint_action_highsuccess100ep_20260812`（第4节canonical-100版的替代批次）

脚本：`scripts/run_pure_oracle_hint_action_highsuccess100ep_20260812.sh`（`RUN_TAG=pure_oracle_hint_action_highsuccess100ep_20260812`）。

**这批 = 第6节的高成功率100集manifest + 第4节 `pure_oracle_hint_action_100ep_20260812` 的eval flag**，两者跟各自的来源逐行diff确认过完全一致，只有 `RUN_TAG` 和 episode 列表不同：

核心 flag（跟第4节canonical-100版完全相同）：
```
--route_memory --route_hint_mode=compact --route_hint_source=oracle
--route_relocalization_backend=none
--topdown_route_map --hint_action_arbiter
```
同样明确不开 `--stop_gate`、`--oracle_align_return_yaw_to_anchor_segment`（理由同第4节）。

episode manifest：跟 `pure_oracle_hint_highsuccess100ep_20260811`（第6节）完全一致的100集列表，未做任何改动。

**由来**：第4节的 canonical-100 版批次于08-12 09:11启动、跑到14:33（98/100集），用户发现本应默认使用高成功率100集却误用了canonical-100（详见第0节、第4节），于14:33明确指示停止该批次并换用高成功率100集重跑其余条件不变，本批即为该指示的执行结果。

**运行记录**：2026-08-12 14:33:53 BST 通过 `systemd-run --user`（`--unit=navila-oracle-hint-action-highsuccess100ep-20260812`）启动，cgroup 确认在 `user@1006.service/app.slice` 下，SSH断开/对话结束不影响运行。结果落在 `NaVILA-Bench/batch_logs/pure_oracle_hint_action_highsuccess100ep_20260812/summary.tsv`。

**注意：这批数据因为换了 episode 样本，跟 canonical-100 系列（baseline / oracle_hint / 第4节的oracle_hint_action）不能做逐集比较**——第4节canonical-100版已产出的23/37=62.2%（98/100，未跑满）仍然是有效数据，只是样本效率低，不建议作为最终论文数字；本批（第7节）预期能在同样甚至更短GPU时间内产出远多于37个的outbound-success样本，是接下来消融链默认要用的数据来源。

## 8. 第三批（消融链最后一步）：`pure_oracle_hint_action_stopgate_highsuccess100ep_20260813`，已完成

脚本：`scripts/run_pure_oracle_hint_action_stopgate_highsuccess100ep_20260813.sh`（`RUN_TAG=pure_oracle_hint_action_stopgate_highsuccess100ep_20260813`）。

**这批 = 第7节 `pure_oracle_hint_action_highsuccess100ep_20260812`（52/86≈60.5% return-rate）的基础上只加一个变量。** 跟第7节脚本逐行 diff 确认：episode manifest（同一份高成功率100集，完全未改动）、`RUN_TAG` 之外的所有其他行为完全一致，唯一新增的是 eval 命令里的：

```
--stop_gate --stop_gate_r_in=3.0 --stop_gate_r_out=3.0 --stop_gate_confirm_steps=3 --stop_gate_min_confidence=0.5
```

四个子参数取值跟历史所有含 `--stop_gate` 的批次一致（核对自 `run_stop_gate_r3_oracle_hard_batch_20260630.sh`）。`--oracle_align_return_yaw_to_anchor_segment` 依旧不加，理由同第4/7节。

**启动记录**：2026-08-13 09:10:37 BST 通过 `systemd-run --user --unit=navila-oracle-hint-action-stopgate-highsuccess100ep-20260813` 启动。启动前确认 GPU 完全空闲（0%利用率）。已核实完全独立于 SSH/对话会话：
- `loginctl show-user teambruce -p Linger` → `Linger=yes`
- 该 unit 的 cgroup 路径为 `/user.slice/user-1006.slice/user@1006.service/app.slice/navila-oracle-hint-action-stopgate-highsuccess100ep-20260813.service`——挂在 `user@1006.service`（该服务自身已独立运行超过2天，不依赖任何登录session）下的 `app.slice`，不是 `session-*.scope`，因此关闭 SSH 连接或结束当前对话都不会终止该批次。

结果落在 `NaVILA-Bench/batch_logs/pure_oracle_hint_action_stopgate_highsuccess100ep_20260813/summary.tsv`；master log `/home/teambruce/run_pure_oracle_hint_action_stopgate_highsuccess100ep_20260813_master.log`。启动后确认第一集（`episode_idx=5`）VLM server 已就绪、Isaac Sim 评估进程已起来。

**这是消融链的最后一步**，完成后三批（oracle_hint → oracle_hint_action → oracle_hint_action+stop_gate）在同一份高成功率100集manifest上构成一条完整、逐步叠加、互相可比的数据点。

**2026-08-13 18:05:27 BST 完成**：outbound_success=87/100，return_success=73/100，round_trip_success=71/100，1个infra failure（episode_idx=539，exit_code=124）。**return-rate = 71/87 ≈ 81.6%**。三步消融链完整结果：

| 步骤 | 配置 | return-rate |
|---|---|---|
| 1（第6节） | oracle_hint only | 32/86 ≈ 37.2% |
| 2（第7节） | + hint_action_arbiter | 52/86 ≈ 60.5% |
| 3（本节） | + stop_gate | **71/87 ≈ 81.6%** |

已推送 `final_data/pure_oracle_hint_action_stopgate_highsuccess100ep_20260813_README.md` + `..._full_results.tsv`（含完整三步对比表）。

## 9. 非oracle对照批次（Route1 70%配置）：`line2_stopgate_redesign_no_yaw_align_highsuccess100ep_20260813`，已于51/100手动叫停（诊断出问题后被第10节的修复批次取代）

上面三步消融链全部是 `route_hint_source=oracle` 的**oracle侧**结果。这一节是为了给整条链找一个**非oracle侧**的对照点：Route1当前主线的 hard-coded 架构（`stop_gate` v2 + `route_memory_agent` 6项修复，不依赖任何controller模型），历史上唯一一次在当前代码上验证过、且return-rate ≥55%的配置——`line2_stopgate_redesign_30ep_20260804`批次，n=10时70.0%（7/10），后来在n=29的更大样本上复测得58.6%（17/29，`line2_50ep_historical_outbound_20260805`，未曾写过报告）。完整候选调查过程见本会话对话记录，未单独写投稿folder。

**配置**：脚本 `NaVILA-Bench/scripts/run_line2_stopgate_redesign_no_yaw_align_highsuccess100ep_20260813.sh`（`RUN_TAG=line2_stopgate_redesign_no_yaw_align_highsuccess100ep_20260813`）。逐行diff确认：
- `COMMON_EXTRA`（stop_gate/route_memory_agent/hint_action_arbiter相关的全部flag）与08-04原始批次逐行一致，仅一处注释文字差异，无功能影响
- 基础调用参数（`--route_memory --route_hint_mode=compact --route_hint_source=integrated --route_relocalization_backend=sequential_pair`）与08-04 driver的默认值一致
- Episode manifest 与第6-8节oracle链完全相同的高成功率100集，逐行diff100条`run_episode`确认一致（同一份manifest，直接episode-for-episode可比）

**与08-04原批次唯一的刻意差异**：`--oracle_align_return_yaw_to_anchor_segment` 未启用（08-04原批次通过driver的隐式默认值`ORACLE_ALIGN_RETURN_YAW_TO_ANCHOR_SEGMENT:-1`带上了这个flag——本会话审计发现这其实是全项目自07-12以来几乎所有"非oracle"批次的隐性惯例，从未被专门标注过，见下方背景）。本批次**也没有**启用同一会话新实现的 `--icp_align_return_yaw_to_anchor_segment`（ICP自驱动版本，见 `investigations/2026-08-13-icp-return-yaw-alignment/FINDINGS.md`）——两个yaw对齐机制都不用，return阶段朝向不做任何修正，confirm结束时是什么朝向就是什么朝向。按本会话审计，这是全项目历史上第一次在批量规模（n=100）上跑这种配置。

**代码完整性核实**（启动前）：
- `stop_gate.py`（08-04 11:26）、`route_memory_agent.py`（08-04 11:24）、`hint_action_arbiter.py`（08-03 11:37）自那以后未再改动
- `round_trip_eval.py` 当天早些时候被本会话修改过（新增 `--icp_align_return_yaw_to_anchor_segment` 机制，见第8节旁的ICP investigations folder），但直接核对了运行时guard逻辑：由于本批次两个yaw flag都不传，`entering_icp_yaw_align` 保持 `False`，代码原样走到未经改动的原始return-entry尾段——即本批次实际执行的逻辑与ICP机制加入之前完全一致

**启动记录**：2026-08-13 20:18:47 BST 通过 `systemd-run --user --unit=navila-line2-stopgate-noyaw-highsuccess100ep-20260813` 启动，PORT_BASE=62000（避开同日更早一次已停止批次的端口范围）。已核实完全独立于SSH/对话会话：主进程SID与当前shell SID不同，PPID挂在systemd --user daemon（PID 1668）下，cgroup路径 `/user.slice/user-1006.slice/user@1006.service/app.slice/navila-line2-stopgate-noyaw-highsuccess100ep-20260813.service`（`app.slice`，非`session-*.scope`），`loginctl show-user teambruce -p Linger` → `Linger=yes`。

结果落在 `NaVILA-Bench/batch_logs/line2_stopgate_redesign_no_yaw_align_highsuccess100ep_20260813/summary.tsv`；master log `/home/teambruce/run_line2_stopgate_redesign_no_yaw_align_highsuccess100ep_20260813_master.log`。

**GPU资源注意**：本批次与一个不相关的RL训练任务（`scripts/rsl_rl/train_multi.py`，G1 dribbling，已跑20+小时）并行跑在同一块GPU上，按用户明确指示不等待其结束。启动时显存占用约23.3GB/24.6GB（约95%），空闲margin很薄（~1.2GB）。截至本次更新未观察到OOM相关的infra failure，但后续如果episode的exit_code异常增多，需要检查是否与显存争用有关。

**上一次尝试**（同日更早，`line2_stopgate_redesign_highsuccess100ep_20260813`，保留`--oracle_align_return_yaw_to_anchor_segment`）被用户两次叫停、从未跑完——那批脚本仍在 `NaVILA-Bench/scripts/` 下，如果之后需要"非oracle但保留yaw-oracle"这个变体做三方对比，可以直接复用。

**结果（2026-08-14，用户手动叫停于51/100，未跑完，不作为最终数据）**：outbound_success=44/51，round_trip_success=12/44≈27.3%。停止原因：这批数据里出现了大量"current锚点长期卡死不动、next被quarantine跳过好几个anchor"的模式（后续第10节整条调查链的直接起点），继续跑同一份代码意义不大，于是先停下来诊断根因，再带着修复重跑。

## 10. quarantine跳跃根因链 + 三处修复：`line2_closure_off_cooldown_kdtree_100ep_20260815`，已完成

上一节`line2_stopgate_redesign_no_yaw_align_highsuccess100ep_20260813`51/100时叫停后，先做了两处直接代码修复（关闭`sequential_pair_closure_check`、新增`sequential_pair_closure_cooldown_attempts`冷却机制、ICP最近邻搜索换成`scipy.spatial.cKDTree`加速），重排了同一份高成功率100集manifest（把20个高风险episode调到批次最前面，episode集合本身不变），跑出这批。之后在这批真实数据上做了一整天的逐集根因排查，详见：

- `investigations/2026-08-15-v11-quarantine-veto/FINDINGS.md`
- `investigations/2026-08-15-hint-action-turn-gate-fix/FINDINGS.md`
- `investigations/2026-08-15-hint-confidence-collapse-patterns/FINDINGS.md`

**配置**：脚本 `NaVILA-Bench/scripts/run_line2_closure_off_cooldown_kdtree_100ep_20260815.sh`（`RUN_TAG=line2_closure_off_cooldown_kdtree_100ep_20260815`）。与第9节`line2_stopgate_redesign_no_yaw_align_highsuccess100ep_20260813`的差异：
- 移除 `--sequential_pair_closure_check`（+ `--sequential_pair_closure_reconciliation_signal=bearing`）
- 新增 `--sequential_pair_closure_cooldown_attempts=20`
- ICP最近邻搜索内部实现换用 cKDTree（数值等价，仅加速，非行为改动）
- episode顺序重排（同一份100集，20个高风险episode移到批次最前）

**结果（2026-08-15 13:38 完成，100/100）**：outbound_success=67/100，return_success（分母=outbound成功）=27/67≈**40.3%**。

**当天完整的根因排查链**（详见上述三份FINDINGS + 会话记录）：
1. quarantine跳过机制在current长期卡死时会让next越跳越远，撞上`reliability_quarantine_max_chain=4`的共享预算上限，被迫落地在可能仍是坏anchor的位置——真实数据验证跳跃≥4时落地误判率明显上升（15%→57%）。
2. 从零尝试4种自建信号（训练模型、alias_score、视觉朝向检查、corridor退化度）改善quarantine误判，全部无效（AUC卡在~0.75-0.76）。
3. 改用路线2现成的V1.1可靠性模型（`/home/teambruce/navila-reliability-v1_1`）distance头，194条真实样本外测试：confidently-好的判断100%精确（0/54错），作为quarantine上的一层否决权（只否决不替代），offline模拟能让47%的误判quarantine被救回、0次误救坏anchor。**→ 已实现为`--sequential_pair_v11_quarantine_veto`（默认关闭），离线验证预计覆盖37个return失败中的7个。**
4. 追"机器人为什么会走偏"发现更上游问题：`hint_action_arbiter`算出的方向本身是准的（真值验证误差<12°），但转向类override被一个只该用于前进类动作的clear-path闸门误挡，导致连续~125步不敢再纠正。**→ 已实现为`--hint_arbiter_turn_override_completes_full_angle`（默认关闭），离线确认覆盖约5-6个。**
5. 剩余的置信度崩溃案例查出两个子病根：真实持续的ICP朝向歧义（无法通过滑动窗口解决）、以及读数其实准确但置信度噪声性低于0.90阈值（可以用滑动窗口趋势平滑解决，直接复用本会话早前给`stop_gate.py`实现的`trend_confidence`机制）。**→ 已实现为`--hint_arbiter_trend_confidence`（默认关闭），离线确认②b这一类约9个（与V1.1有2个重叠）。**

三处改动合计离线确认覆盖37个return失败中的19-20个；15个完全未被触及（7个真实ICP歧义、5个尚未查明原因、1个confidently-wrong-stop、1个边缘案例、1个待查）。三处改动均默认关闭、纯加性、449个单元测试全过、无回归。**尚未做live batch验证**——下一步计划：开一个smoke测试验证这三处改动在真实运行环境下不报错、行为符合预期，再决定是否值得投入一次完整100ep批次做实测对比。

## 相关文件

- `scripts/run_pure_oracle_hint_100ep_20260811.sh`（第1节，canonical-100，已跑完，30/100 outbound）
- `scripts/run_pure_oracle_hint_action_100ep_20260812.sh`（第4节，canonical-100，已手动停止于98/100，37/98 outbound，未采纳为最终数据）
- `scripts/run_pure_oracle_hint_highsuccess100ep_20260811.sh`（第6节，高成功率100集变体，纯oracle_hint，已跑完）
- `scripts/run_pure_oracle_hint_action_highsuccess100ep_20260812.sh`（第7节，高成功率100集 + hint_action_arbiter，已跑完，52/86≈60.5% return-rate）
- `scripts/run_pure_oracle_hint_action_stopgate_highsuccess100ep_20260813.sh`（第8节，高成功率100集 + hint_action_arbiter + stop_gate，消融链最后一步，**已完成，71/87≈81.6%**）
- `scripts/run_line2_stopgate_redesign_no_yaw_align_highsuccess100ep_20260813.sh`（第9节，非oracle Route1 70%配置，同一份高成功率100集，不带任何yaw对齐，**51/100手动叫停，12/44≈27.3%，未采纳**）
- `scripts/run_line2_closure_off_cooldown_kdtree_100ep_20260815.sh`（第10节，第9节的修复重跑版本，**已完成，27/67≈40.3% return-rate**）
- `scripts/run_line2_stopgate_redesign_highsuccess100ep_20260813.sh`（第9节提到的"上一次尝试"，保留oracle yaw对齐，被停止两次未跑完，留作备用）
- `investigations/2026-08-11-pure-oracle-hint-100ep-and-stopgate-audit/README.md`（oracle_hint 批次的完整背景、stop_gate审计、hint文本机制对比）
- `investigations/2026-08-13-icp-return-yaw-alignment/FINDINGS.md`（第9节提到的ICP自驱动yaw对齐机制，新flag `--icp_align_return_yaw_to_anchor_segment`，已实现+冒烟测试，未跑批量）
- `code/run_pure_oracle_hint_100ep_20260811.sh`、`code/run_pure_oracle_hint_action_100ep_20260812.sh`、`code/run_pure_oracle_hint_highsuccess100ep_20260811.sh`、`code/run_pure_oracle_hint_action_highsuccess100ep_20260812.sh`、`code/run_pure_oracle_hint_action_stopgate_highsuccess100ep_20260813.sh`、`code/run_line2_stopgate_redesign_no_yaw_align_highsuccess100ep_20260813.sh`（本文件夹内脚本快照，供对照）
- `code/high_outbound_success_100ep_selection.tsv`（高成功率100集的完整选择数据：episode_id/历史尝试次数/成功次数/成功率/episode_idx/scene/neighbor等字段）
