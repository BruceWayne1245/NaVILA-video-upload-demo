# Implementation and queue safeguards

## 运行时代码（本机 canonical runtime）

根目录：`/home/teambruce/navila-route2-v11-core-20260801`

| 文件 | 本次内容 |
|---|---|
| `anchor_transition_runtime/full_active_controller.py` | 显式 `NORMAL/PAIR_SUSPECT/PROBING/COMMIT_RECOVERY/NO_LOCK` 状态与局部四 anchor 选择 |
| `runtime_candidate/scripts/route_memory_agent.py` | 接受受限 recovery pair、temporary quarantine、失锁时撤销陈旧 route consumer |
| `runtime_candidate/scripts/round_trip_eval.py` | `NO_LOCK` 时使旧 pair evidence stale，避免其继续否决 terminal；未启用 A0 visual distance 作 terminal evidence |
| `runtime_candidate/scripts/relocalization.py` | `_nearest_neighbor_2d` 的异常/非有限输入安全处理 |
| `launch/run_manifest_batch_driver.sh` | 新增每 EP cleanup fence（进程树、result suffix、VLM port、GPU 空闲量） |

recovery10 使用的固定 SHA-256：

```text
round_trip_eval.py             82aa9ad9d5b29fcbf7b03e94687a761da0481d9cadbf7db442e37e6d2fc61a56
route_memory_agent.py          52e9a2d3d327332e34e88e1a2e9571a8b22de3602e6a7cdee5b4f1187a273b5b
full_active_controller.py      6739f30bbb364ceb3bc50d51020f3e9a854d3f8edbe915060c468b5f077e0444
online.py                      1cf7804e4103a7587373b4b3504de759ea809af135a9ec62f8f38985d54bccf9
anchor_transition_v2_robust    461577a982e3cd4a551e321741cb21bf5b0ac167d83252e67fb6d8cd5877a9cd
```

## 队列实现

- runner：`/home/teambruce/run_route2_anchor_recovery10_20260804.sh`
- waiter：`/home/teambruce/wait_for_line2_stopgate30_then_run_route2_recovery10_20260804.sh`
- manifest：`manifest/route2_anchor_recovery10_20260804.tsv`
- systemd unit：`navila-route2-recovery10-after-line2-20260804.service`

### 启动前 fence

1. 只等待明确的当前上游 unit 退出；不会把 EP 间的 VLM 重启误判为 batch 完成。
2. 退出后按上游 run tag 和每个预期 VLM port 进行 TERM/KILL 清扫。
3. 等候 GPU free memory >= 22000MiB；超 10 分钟不收敛则失败退出，不启动 Route2。
4. 检查 Route2 的 run tag 不存在，避免重复 launch。

### EP 间 fence

每个 EP 的 timeout 是 3600s，timeout 后 300s kill-after。无论 exit code 是成功、fatal 或
timeout，driver 都会：

1. 杀 tracked evaluator/VLM 的进程树和 process group；
2. 再以本 EP 的 `episode_idx + result_suffix` 扫描 re-parented evaluator；
3. 以本 EP 唯一 VLM port 扫描并杀掉 VLM worker；
4. 直到这两类进程不存在且 GPU free >= 22000MiB，才进入下一个 EP；5 分钟不收敛则标记
   integrity failure，阻止抢资源继续运行。

这解决的是此前“wrapper 被 kill 但 Isaac/Kit 或 VLM child 留在 GPU 上、下一批没有正常
接上”的具体故障模式；它不通过杀未知 GPU 用户来换取启动，因此保持 fail-closed。

## 刻意未包含的项目

- 0.3m 受控 probe motion；
- 直接 A0 visual/ICP 作为 terminal distance；
- Hint、TRB、terminal 模型重训或策略重设。

这些都属于后续独立变量，不能混入 recovery10 的因果归因。
