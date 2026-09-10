# 论文 Online M50 的 ICP、Anchor 与 Local Map 代码审计

日期：2026-09-10

## 审计范围与版本

本文只描述论文中最终运行 matched M50 的 online 系统，不把后来的 KD-tree、ICP-yaw brute-force、确定性路径跟随或视觉双锚点改版混入结论。

论文版本来自本机冻结归档：

```text
/home/teambruce/navila_archive/staging_dirs/
  navila-reliability-v1_1-policy-v2-active50-20260725/
```

实际 evaluator 位于该归档的 `policy_v2_live_candidate/scripts`；M50 参数由 `experiments/2026-07-25-policy-v2-active-50ep/run_batch.sh` 固定。归档 runner 对关键文件执行 SHA256 校验，因此这里复制的代码可以追溯到实际运行版本。

本目录的 `code/` 保存了与本审计直接相关的完整源码快照：

- `relocalization.py`：点云提取、下采样、ICP 和 sequential-pair 匹配；
- `route_memory_agent.py`：anchor 数据结构、保存、current/next 状态与后处理；
- `round_trip_eval.py`：传感器点云读取、descriptor 构建、运行时调用链；
- `go2_matterport_vision_cfg.py`：`route_memory_lidar` 的 Isaac 配置；
- `run_batch.sh`：论文 active M50 的实际参数。

## 一、系统概览

论文 online 不是 scan-to-global-map 定位。它在 outbound 沿路线保存局部 LiDAR anchor；return 时只维护已知的 `(current, next)` 两个候选，并把当前瞬时扫描分别与这两个 anchor 做二维 ICP：

```text
outbound
  route_memory_lidar 射线交点
    -> 世界坐标转机器人 body frame
    -> 每累计约 1 m 保存一个单帧 anchor

return
  当前单帧 local map
    -> 高度过滤、XY 投影、0.10 m voxel、最多 512 点
    -> ICP(current anchor, current scan)
    -> ICP(next anchor, current scan)
    -> closure / promotion / quarantine / Reliability V1.1
    -> 距离、bearing、confidence
    -> hint / arbiter / stop gate
```

论文运行参数包括：

```text
route_relocalization_backend = sequential_pair
route_relocalization_interval_updates = 5
route_local_map_icp_objective = point_to_point
route_local_map_voxel_size_m = 0.10
route_local_map_max_points = 512
route_local_map_quality_policy = diagnostic
sequential_pair_anchor_geometry_source = accumulated
```

## 二、机器人的 Local Map

### 2.1 传感器

代码优先读取专用于路线记忆的 `route_memory_lidar`。它是 IsaacLab 的 `RayCasterCfg`，不是带有显式噪声模型的真实 LiDAR：

- 挂载点：机器人 `Head_lower`；
- 平移偏置：零；
- 旋转：单位四元数；
- 32 个垂直通道；
- 垂直视场：-15° 至 +15°；
- 水平视场：-180° 至 +180°；
- 水平角分辨率：1°；
- 最大距离：20 m；
- 射线对象：Matterport mesh；
- 更新周期：`4 * sim.dt`。

理论上一帧约有 `32 * 360 = 11,520` 条射线。实际有限交点数会略少；项目日志中见过约 11,488 点。

### 2.2 坐标变换

RayCaster 输出世界坐标交点。evaluator 使用 Isaac 中机器人的世界位姿把点变换到当前 body frame：

```text
p_body = R_robot_world^T (p_world - t_robot_world)
```

descriptor 中加入：

```python
{
    "local_map_points_body": points_body,  # N x 3, x/y/z
    "local_map_source": "isaac_sensor",
}
```

ICP 后续不直接读取 anchor metadata 中的世界位姿。不过，从 `ray_hits_w` 生成 body-frame 点云的过程使用了 Isaac 真值机器人位姿。这一点在讨论 sim-to-real 边界时必须明确：真实 LiDAR 通常直接输出 sensor/body-frame range，而这里通过仿真真值完成等价坐标变换。

### 2.3 点云预处理

进入二维 ICP 前：

1. 删除含 NaN/Inf 的点；
2. 若高度带内至少有 12 点，仅保留 `-0.20 <= z_body <= 1.80 m`；
3. 丢弃 z，只保留 `(x, y)`；
4. 将 XY 除以 0.10 m 后四舍五入生成 voxel key；
5. 每个 voxel 保留原始顺序中的第一个点；
6. 若仍超过 512 点，按等间隔索引抽样到 512 点。

这不是 occupancy grid：没有占据概率、free-space ray carving、时间衰减或地图融合。最终参加 ICP 的 local map 是当前机器人 body frame 中至多 `512 x 2` 的二维点集。

## 三、Anchor 保存的信息

`RouteAnchor` 包含：

| 字段 | 含义 |
|---|---|
| `index` | 沿 outbound 路线递增的编号 |
| `pose_from_start` | 由路线里程累计得到的 `[x, y, yaw]` |
| `distance_from_start_m` | outbound 累计路程，不是起点直线距离 |
| `route_remaining_to_start_m` | 从该 anchor 沿路线返回起点的长度；实现中等于累计 outbound 路程 |
| `descriptor` | anchor 时刻的传感器 descriptor |
| `metadata` | 事件和评估/调试信息 |
| `edge_from_previous` | 前一 anchor 到当前 anchor 的一次性 SE(2) 相对边 |
| `alias_score` | 与非相邻 anchor 的 ICP 相似程度 |

完整 descriptor 可能包含前/后 RGB、前/后 depth、相机内参、相机 body 外参、相机世界位姿、route-memory observation 和 `local_map_points_body`。但论文 M50 的 sequential-pair ICP 只读取 `local_map_points_body`；RGB、depth 和相机参数不参与这次 ICP。

### 3.1 保存频率与帧数

论文 runner 没有覆盖 `route_anchor_spacing_m`，因此使用默认 1.0 m：outbound 累计行程每增加约 1 m 保存一个 anchor，并在 outbound 结束处强制追加最后一个 anchor。

论文 M50 没有开启 multi-frame anchor、symmetric anchor accumulation 或 return frame buffer。因此：

- 普通 anchor 是触发时刻的一帧瞬时扫描；
- return local map 也是当前时刻的一帧瞬时扫描；
- 两边都不是多帧融合 submap。

### 3.2 Anchor 0 的结构性缺口

初始化时 anchor 0 通过下列逻辑创建：

```python
_append_anchor(descriptor=None, metadata={"event": "start"})
```

因此起点 anchor 0 没有 LiDAR descriptor。路线末端的 pair 变为 `(1, 0)` 时，anchor 0 不能正常参加 ICP。这是终点附近缺少 anchor-0 几何证据的结构性原因。

### 3.3 World pose 的用途

evaluator 在创建普通 anchor 后会把 Isaac world pose 写入 metadata，并标为 `isaac_oracle_for_relocalization_eval`。正常 sequential-pair ICP 不读取该字段；它用于事后真值误差、可视化和 oracle/debug 分析。

## 四、Anchor 与 Current Local Map 的 ICP

### 4.1 候选集合

return 开始时：

```text
current = 最后一个 outbound anchor
next = current - 1
```

随后按路线反向移动：

```text
(N, N-1) -> (N-1, N-2) -> ... -> (1, 0)
```

正常情况下不对全路线做 place recognition。quarantine 机制可以跳过已判定不可靠的 next anchor。

### 4.2 变换方向

实际调用为：

```python
icp_seed_sweep_2d(anchor_points, current_points, ...)
```

因此 anchor 是 source，当前扫描是 target，求解：

```text
p_current ~= R(theta) p_anchor + t
```

`t = [anchor_dx_m, anchor_dy_m]` 是 anchor 原点在当前机器人坐标系中的位置。系统据此计算：

```text
distance_to_anchor = sqrt(dx^2 + dy^2)
bearing_to_anchor = atan2(dy, dx)
```

`anchor_dtheta_rad` 表示 anchor frame 相对当前 body frame 的旋转。

### 4.3 Multi-start ICP

每个 anchor 从 24 个 yaw 初值运行 ICP：

```text
-180°, -165°, -150°, ..., 150°, 165°
```

每个 seed：

- 最多 16 次 ICP 迭代；
- correspondence threshold 为 0.45 m；
- 输入两边各至少 12 点；
- 每轮至少 8 个 inlier correspondence。

一次 relocalization 最多计算 `2 anchors * 24 seeds = 48` 个 ICP。

### 4.4 初始化、Correspondence 和更新

对每个 yaw seed，初始平移只通过质心对齐得到：

```text
t0 = mean(current) - R(seed) mean(anchor)
```

每轮将 anchor 点变换到 current frame，再为每个变换后的 anchor 点寻找 current 点云中的最近邻。距离小于 0.45 m 才是 inlier。

这个 correspondence 是单向 `anchor -> current`：

- 没有 mutual nearest-neighbor；
- 没有一对一约束；
- 多个 anchor 点可以对应同一个 current 点；
- 最近邻由 NumPy 分块暴力距离计算完成，不是 Open3D 或 KD-tree。

论文使用 point-to-point objective。每轮对 inlier 对应点计算二维刚体 SVD；若旋转矩阵 determinant 为负则修正反射，然后把增量旋转和平移组合到当前变换。相邻两轮 median residual 变化小于 `1e-4 m` 时提前停止。

### 4.5 Seed 评分与候选门槛

每个 seed 的评分为：

```text
score = overlap_ratio
        * max(0, 1 - median_residual / 0.45)
        * sqrt(inlier_count)
```

其中：

```text
overlap_ratio = inlier_count / min(num_anchor_points, num_current_points)
```

最高分 seed 成为该 anchor 的原始输出。输出置信度是：

```text
confidence = min(1,
                 overlap_ratio
                 * max(0, 1 - median_residual / 0.45)
                 * 1.5)
```

一个结果至少需要：

- `inlier_count >= 12`；
- `overlap_ratio >= 0.12`；
- `confidence >= 0.15`。

### 4.6 Basin 与退化诊断

24 个 seed 的结果按以下阈值聚成 basin：

- 变换平移差不超过 0.35 m；
- 旋转差不超过 20°。

当第二 basin 的得分达到第一 basin 的 85%，且两者平移相差至少 0.75 m 或旋转相差至少 45°时，结果标为 `high_confidence_multimodal`。

代码还计算 corridor degeneracy、correspondence localizability、yaw-score entropy、peak width、near-tie basin 和 Scan Context yaw diagnostic。

然而论文 M50 使用 `quality_policy=diagnostic`。因此这些指标主要进入日志，而不会像 strict policy 那样统一拒绝多峰或退化匹配。这解释了为什么 nominal confidence 很高的错误旋转仍可能进入下游。

## 五、Raw ICP 并不等于最终报告值

每次对 current 和 next 得到两个 raw ICP 后，还会经过：

- current/next closure consistency；
- belief fusion 或 trust-aware reconstruction；
- bounded-evidence promotion；
- 默认 5 次观察至少 3 票；
- alias-aware 时 8 次观察至少 5 票；
- short-baseline yaw disambiguation；
- quarantine；
- Reliability V1.1 / Policy V2。

论文配置关闭 temporal smoothing，因为历史调查发现它会把当前正确 ICP 和旧的错误 belief 混合，产生额外 bearing corruption。

分析结果时必须区分三个层次：

1. `relocalization.py` 的 raw single-anchor ICP；
2. current/next closure/fusion 后的 estimate；
3. promotion 和可靠性策略后最终提供给 hint 的 estimate。

历史上一部分所谓“ICP bearing error”实际发生在第 2 层：raw ICP 正确，但 closure fusion 改坏了结果；另一部分则是真正的 single-anchor ICP 收敛到错误旋转 basin。

## 六、关键结论

论文 online M50 的定位原语是一套自写的 NumPy 二维 point-to-point multi-start ICP：

- anchor 是 outbound 每约 1 m 保存的一帧 360° RayCaster 点云；
- current local map 是 return 当前时刻的一帧扫描；
- 两者都经高度过滤、XY 投影、0.10 m voxel、最多 512 点；
- 只匹配 current 和 next，不做全路线检索；
- 每个 anchor 使用 24 个 yaw 初值；
- 求解 anchor frame 到当前 robot body frame 的 SE(2) 变换；
- 平移直接被解释为 anchor 相对机器人的距离与 bearing；
- quality policy 是 diagnostic，多峰/退化结果未被全面硬拒绝；
- anchor 0 没有 descriptor，是终点附近几何链的结构性缺口；
- local map 的 body-frame 转换使用 Isaac 真值世界位姿，是仿真传感器管线需要在论文中准确说明的边界。

## 七、代码快照校验值

```text
6a5ba80cd333e690d0dd449519578bbdaf18e5b1f740683afcc766d6b48561b7  go2_matterport_vision_cfg.py
226a87b68d5727982a03763da19ec10baf7f90f8d61a66f29e288b8e6bfb09c1  relocalization.py
437f35851d93e369b5573ce62140fac09ca93d2581b32d5fbde25dae43943551  round_trip_eval.py
7120438c2bb44b3a3784a079e1c0f372af0dca265d1bcb3912a196e1c54cbc02  route_memory_agent.py
f42095ccef56cbfb56a6c88cb74fb1f7187962bc976e495912d7aaa5dad65cc5  run_batch.sh
```

