# Stage 3.2：5ep Active 启动、首个结果与后台交接（2026-07-26）

## 当前结论

用户在看过 Stage 3.1 的小样本 shadow 结果后明确决定：不再因为单次可能的误触发继续调参，进入有界 Active。

Stage 3.2 已按这个决定启动，但 Active 权限被严格限制为：

- episode 仅限 `[5, 205, 491, 500, 658]`；
- 最多完成 5 个 episode；
- 只允许执行 temporary quarantine 及与其配对的 promotion suppression；
- 不修改 motor action；
- 不修改 VLM stop / stop gate；
- 不执行尚未实现的 active scan；
- 遇到 scan request 时必须回滚本次候选状态并关闭 controller；
- 每个 episode 使用独立 kill switch。

截至 2026-07-26 18:16 BST：

- ep5 已完成，严格 round trip 成功；
- ep205 正在运行；
- ep491、500、658 待运行；
- 后台运行已有独立 `PPID=1` watchdog 接管，不依赖本次 Codex 对话继续存在。

本文件是关闭对话前的冻结交接点。今晚不再调整阈值或控制逻辑，明天等 cohort 完成后统一分析。

## 权威代码位置与运行标识

本次运行使用隔离候选目录：

`/home/teambruce/navila-reliability-v1_1-v2-integrated-20260726`

运行 tag：

`reliability_v11_v2_integrated_candidate_controller_stage32_active_5ep_20260726`

batch 日志目录：

`/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/reliability_v11_v2_integrated_candidate_controller_stage32_active_5ep_20260726`

结果目录 pattern：

`/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_reliability_v11_v2_integrated_candidate_controller_stage32_active_5ep_20260726_ep{EP}`

不要使用本地其他旧 README 或旧代码副本解释这次运行。上面的隔离目录、下列 hash 和本次 GitHub investigation 共同定义 Stage 3.2 的实际运行版本。

## 本轮代码与配置修改

### 1. 独立 Active 批准 artifact

新增：

`configs/v11_integrated_candidate_controller_active_v0_stage32_5ep_approved_20260726.json`

SHA256：

`2b219f258472e233ce33d631e45da65936cb1effde256ba8739e4fd2df60ca3c`

关键约束：

- `approved=true`；
- 明确记录用户本次 Active 批准；
- exact episode allowlist 为 `[5,205,491,500,658]`；
- `max_completed_episodes=5`；
- temporary quarantine 最大 4 个 anchor；
- controller mutation 最大 12 次；
- motor/stop authority 均为 false。

它与早期 ep5 Active v0 artifact 分离，旧 artifact 没有被复用或扩大权限。

### 2. 5ep cohort runner

新增：

`experiments/2026-07-26-v2-integrated-promotion-shadow-canary/run_stage32_active_5ep.sh`

SHA256：

`fabd9bda55696b0dae3c7584730c12aa67a6c081d3d1e6a2723fed4572a68619`

固定运行顺序：

`5 -> 205 -> 491 -> 500 -> 658`

### 3. batch runner 的 Active 边界

修改：

`experiments/2026-07-26-v2-integrated-promotion-shadow-canary/run_batch.sh`

SHA256：

`3b26ed5f0e3e746bf84f2d5a54f9f3a1988c797cca516e3f49b2a62e77f619aa`

新增保护：

- 校验批准 artifact 的路径和 hash；
- exact allowlist 不匹配即拒绝启动；
- episode 不在 allowlist 中即拒绝；
- 最大完成数超过 5 即拒绝；
- kill switch 改为每个 episode 独立的 `ep${id}.stage32_active.KILL`；
- runner 依据严格 completion validation 续跑，不把 partial 结果当作完成。

### 4. 测试

修改：

`tests/test_v11_integrated_candidate_controller.py`

SHA256：

`fb6598819fec77285782e7c9aac9cf63d1204706bf993c2eff6d1ad8015b57fa`

新增测试覆盖：

- Active artifact 的 exact 5ep scope；
- 批准身份绑定；
- episode 93 等 scope 外输入必须被拒绝；
- motor/stop 权限仍关闭。

### 5. 对话无关的 watchdog

新增：

`experiments/2026-07-26-v2-integrated-promotion-shadow-canary/run_stage32_active_5ep_detached_watchdog.sh`

SHA256：

`714ded4214525ffb37cfa69d1425c11189d40b68d3edd5097eb143f072f88ff6`

行为：

1. 等待当前 supervisor 退出；
2. 如果仍有本 cohort 的 `round_trip_eval.py` 子进程，继续等待，避免重复占用 GPU、端口或结果目录；
3. 等现有 episode 完全退出后，调用 completion-aware cohort runner；
4. 已完成的 ep5 会被跳过，未完成 episode 从 cohort 队列恢复。

### 6. 实际 Active runtime hash

以下是本次运行实际引用的核心文件：

- `reliability/v11_consumer_policy_v2.py`：`3815283afc1da70c29e455519cf657d67049f708287bb14fd9213ccf5660244a`
- `reliability/v11_integrated_anchor_state.py`：`40d55111ec4335d1c5a6c6d6386f173d753524038c005536211c672f6a08c9d4`
- `reliability/v11_integrated_candidate_selector.py`：`3f29596146143fbc7628f76c740895d4e45c909dadf942e75e379ab349f9c498`
- `reliability/v11_integrated_candidate_controller.py`：`8cec196b8aa39520105ddd0f1a5ba8e0dca32189784b94c073075f7e4c504b1a`
- `policy_v2_live_candidate/scripts/round_trip_eval.py`：`9dce7ac859025f1896bcda137d454e827c2868f8fc54f978e2d20e94e55bc881`
- `policy_v2_live_candidate/scripts/route_memory_agent.py`：`585360936279be97f1530562ed0c5d8adfd5f2cb332b9d8885eddff712aa6791`

## 验证结果

启动前完成：

- targeted tests：52 passed；
- 全套相关 tests：78 passed，1 failed；
- 唯一失败是仓库中本来就缺少 fixture：
  `experiments/2026-07-23-prospective-results/prospective_v1_1.npz`；
- 5 个批准 episode 的 preflight 全部通过；
- 用 ep93 验证 scope 外启动会被拒绝；
- 启动前 GPU 无遗留测试进程。

上述缺失 fixture 不涉及 controller、runner、artifact scope 或 Active enforcement，因此未阻止本次有界 Active。

## ep5 首个 Active 结果

### Episode 结果

- start：2026-07-26 17:20:37 BST
- end：2026-07-26 18:03:51 BST
- exit code：0
- completion validation：PASS
- outbound success：True
- return success：True
- strict round-trip success：True
- 最终 distance-to-start：2.6850 m
- outbound stop distance-to-goal：0.1408 m
- trajectory records：6177
- measurement：`measurements/8.json`

日志完整性：

- consumer、shadow：各自连续、可读取；
- promotion/state/selector/controller：各 881 条，attempt sequence 连续；
- controller 没有获得 motor 或 stop 权限。

### Active controller 实际做了什么

controller 产生 5 个 effect：

- 4 次 temporary quarantine + paired promotion suppression；
- 第 5 次遇到 scan request，按设计回滚并关闭 controller；
- 总计 4 次 suppression；
- 没有 motor action mutation；
- 没有 stop decision mutation。

四次实际隔离发生在同一 return phase：

| attempt | step | current | 被隔离 next | `p_pose_bad` | world-pose truth |
|---:|---:|---:|---:|---:|---|
| 247 | 3004 | 12 | 11 | 0.9432 | pose bad |
| 250 | 3019 | 12 | 10 | 0.9575 | pose bad |
| 253 | 3034 | 12 | 9 | 0.9613 | pose bad |
| 256 | 3049 | 12 | 8 | 0.9912 | pose bad |

因此 ep5 的四次实际 quarantine 在离线 world-pose truth 下为 **4/4 正确**，没有 false quarantine。

attempt 259 / step 3064 时 next7 也是真实 pose bad，但继续跳过会要求 active scan。scan 尚未实现，因此 controller：

- 没有执行第五次隔离；
- 回滚本轮候选状态；
- 清空 controller quarantine；
- 关闭后续 Active controller；
- 没有 suppress 本轮 promotion。

episode 随后仍完成严格 round trip。这个单 episode 只能证明：

1. Active 链路确实执行了批准范围内的状态修改；
2. 实际触发都能与 world-pose truth 对齐；
3. scan 边界的 rollback/default-close 正常工作；
4. 至少在 ep5 中没有因 Active 修改破坏任务成功。

它不能单独证明 5ep cohort 的总体收益，也不会用来继续临时调参。

## 后台运行独立性证明

2026-07-26 18:16 BST 从主机 namespace 验证：

- 原 cohort supervisor：PID `1785548`，仍在运行；
- ep205 Isaac evaluation：PID `1788926`，仍在运行；
- detached watchdog：PID `1790022`；
- watchdog `PPID=1`；
- watchdog `PGID=1790022`；
- watchdog `SID=1790022`；
- watchdog 状态为 `Ss`。

watchdog 日志：

`batch_logs/reliability_v11_v2_integrated_candidate_controller_stage32_active_5ep_20260726/detached_watchdog.log`

启动记录：

`[watchdog] started=2026-07-26T18:12:05+01:00 pid=1790022 parent=1 waiting_for=1785548`

这意味着 watchdog 不属于本次对话的终端/session。关闭 Codex 对话后：

- 如果原 supervisor 保持运行，它什么都不做；
- 如果原 supervisor 被回收，它等待当前 `round_trip_eval.py` 结束；
- 然后用同一 tag、同一批准 artifact 和 completion validation 恢复剩余队列。

排查期间曾临时启动一个 tmux supervisor 来验证主机可见性；发现原进程实际上仍存活后已立即删除该重复 tmux session。主机侧确认始终只有原 ep205 `round_trip_eval.py` 在运行，没有第二个 episode evaluation 被启动。

因此这 5ep cohort 不需要本次对话保持打开，也不需要明天人工重新输入上下文才能继续。

## 当前数据冻结点

`summary.tsv` 当前只有一条完整记录：

| episode | outbound | return | round trip | distance-to-start |
|---:|---|---|---|---:|
| 5 | True | True | True | 2.6850 m |

ep205 于 18:03:52 BST 启动，冻结本文时仍运行中，因此不能提前写入成功/失败结论。ep491、500、658 尚未启动。

## 明日计划

等 5ep cohort 自然结束后再统一做以下分析：

1. 检查 `summary.tsv`、每个 completion artifact 和 watchdog handoff 日志，确认没有 partial 被误算；
2. round-trip 成功率只以 outbound-success episode 为分母，继续排除 outbound 失败；
3. 对每个 episode 校验 consumer/shadow/promotion/state/selector/controller 的 attempt 对齐、hash 和执行范围；
4. 对所有 Active quarantine 触发做 world-pose truth 对照，统计 precision、false quarantine、正确跳过数和是否真正缩短 hint starvation；
5. 对失败 episode 分解 stop、hint starvation、anchor state、locomotion/recovery 与 termination/reset；
6. 对比 Route1 原始行为与 Stage 3.2 行为，判断 temporary quarantine + paired suppression 是否改善 anchor 推进；
7. 只有完整 cohort 数据支持时，才讨论 scan 语义、扩大 episode scope 或调整阈值。

今晚明确不做：

- 不因 ep5 的单个成功继续改阈值；
- 不扩大 Active 权限；
- 不开放 motor 或 stop action；
- 不实现或启用 scan；
- 不边跑边修改 runtime。

