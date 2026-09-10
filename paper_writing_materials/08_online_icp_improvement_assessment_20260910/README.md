# Online 与 Oracle 差距：更换匹配算法和提高点云质量能否解决 ICP 授权不足

日期：2026-09-10

## 结论摘要

更换匹配算法或提高点云质量有可能改善 online 系统，但根据项目已有实验，单纯把当前 ICP 换成更高级的单帧点云匹配算法，或者只增加同一视角的点数，基本不可能消除 online 与 oracle 的主要差距。

更有希望的方向是引入当前单帧没有的新信息：

1. 经过可靠帧间配准的运动积分多帧 submap；
2. RGB-D/LoFTR 作为独立的几何歧义复核信号；
3. 利用多时刻证据的 current/next 时序状态估计；
4. 保留完整高度结构的 3D 或 2.5D 匹配；
5. 根据转角和场景判别性选择 anchor，而不是固定每约 1 m 截取一帧。

参数微调、增加单帧点数和替换 ICP objective 可以作为工程优化，但不应被视为恢复 oracle 水平的主要方案。

## 一、先澄清“62%不可信”的含义

项目论文补充统计中的 62% 是：

> `r_bearing` 在 62% 的 Return decision steps 上选择 withholding，使 hint/action 系统不能依据该 bearing 获得授权。

对应 trusted coverage 约为 38%，并不等价于“已经证明 62% 的 raw ICP 数值一定错误”。被 withholding 的读数可能包括：

- 真正错误的 ICP；
- 数值正确但可靠性模型不敢授权的 ICP；
- current/next anchor 状态错误；
- 单帧观测证据不足；
- raw ICP 正确但 closure/fusion 后被改坏；
- 可靠性模型训练分布或近终点样本不足。

因此目标不应只定义为“让 ICP 平均误差更低”，还必须同时提高可信读数的 coverage，并控制错误授权率。

## 二、仅更换单帧匹配算法为什么不太可能根治

### 2.1 更密集的 ICP 搜索已经尝试过

历史实验将 production 的 24 个 yaw seed 扩展成 360 个 seed，并检查了接近真值的 yaw 初始化。困难 anchor 上仍会选到错误解，因为错误姿态在现有 point-to-point overlap metric 下确实可能比真值姿态得分更高。

这说明问题不只是 ICP 陷入局部极值。即使初始化更密、更接近真值，正确姿态也未必是当前单帧几何目标函数的最优解。

### 2.2 Occupancy-grid 全局相关搜索也没有稳定获益

项目实现过二维 occupancy-grid FFT correlation，对 yaw、dx、dy 做联合全局搜索。16 个困难读数上的结果为：

| 方法 | 平均角度误差 | 中位角度误差 | 优于 ICP 的读数 |
|---|---:|---:|---:|
| Production ICP | 86.0° | 85.7° | — |
| Binary occupancy correlation | 82.4° | 86.0° | 9/16 |
| Gaussian-blurred correlation | 94.9° | 94.3° | 6/16 |

两种相关匹配都没有系统性优于 ICP。这个结果支持如下解释：困难 anchor 中存在真实重复结构，从单个视角看，错误姿态对任何普通二维几何重合度量都可能同样合理。

因此，仅替换为 point-to-line ICP、GICP、NDT、TEASER++、更密集 brute-force 或单帧 learned registration，可能改善普通样本和收敛稳定性，却不太可能解决主要的旋转自相似与局部重复结构问题。

## 三、只增加同一帧的点数为什么收益有限

production pipeline 已经经历过以下改进：

- 最大匹配点数从 256 增加到 512；
- voxel size 从约 0.12 m 调整到 0.10 m；
- 增加专用 `route_memory_lidar`；
- 使用 32 通道、水平 1°分辨率的 360°扫描；
- 原始一帧约 11,500 条射线，障碍高度带内约数千点。

然而，对已确认的旋转自相似 anchor，提高同一视角的采样密度没有明显扩大正确解与错误解的得分差。

如果一个视角只看到平行墙面或重复走廊，把墙采样得更密只是更精确地描述同一个歧义，并不会引入新的判别信息。因此：

- 从 512 增加到 1,024 或 2,048 点；
- 将水平分辨率从 1°提高到 0.5°；
- 调整 voxel 或 correspondence threshold；

都可能降低普通噪声，但更像增量优化，而不是把 trusted coverage 从约 38%提高到接近 oracle 的核心方案。

## 四、完整 3D/2.5D 几何有部分希望

当前 production ICP 在高度过滤后丢弃 z，只进行二维匹配。项目曾对困难样本检查高度 residual：

- 14 个有效困难案例；
- 真值变换的高度一致性明显更好：6/14；
- 大致相同：1/14；
- 错误 ICP 变换在 z 上反而更好：5/14。

因此，现有高度带中的 3D 信息有部分判别能力，但并不稳定。

这项实验还有一个重要限制：保存的数据已经被裁剪到 `-0.20 <= z <= 1.80 m`。门框上缘、天花板、高家具等完整垂直结构在落盘前已经丢失，所以实验没有真正验证“完整 3D LiDAR 是否有用”。

值得进一步考虑的是：

- 保留完整或更宽的 z 范围；
- 真实 point-to-plane/GICP；
- 法向和平面方向；
- 对 floor、ceiling、vertical wall 分层建模；
- 利用门框、墙角和高处结构。

这可能解决一部分二维旋转歧义，但仍无法区分几何结构真正重复的走廊。

## 五、多视角、多帧 Submap 是几何方向中最有希望的路线

历史调查发现，10 个已知困难 anchor 中有 9 个在附近 0–5.3 m 内存在真实转弯，多数在 0–2 m 内，有些转弯就在 anchor 所在位置附近。

这表明环境中通常存在有判别性的几何，只是当前 anchor 使用固定里程触发的一帧瞬时扫描，可能恰好没有看到附近的转角或遮挡后的结构。

多帧 submap 的理论价值不是“点更多”，而是机器人移动后得到：

- 新视角；
- 真实视差；
- 不同遮挡关系；
- 更长空间范围的结构。

### 5.1 项目已有的多帧实现为什么没有成功

已有一次 live multi-frame 尝试中，ep319 anchor 3 出现：

| 指标 | 单帧 baseline | Multi-frame |
|---|---:|---:|
| Mean confidence | 0.505 | 0.310 |
| Mean overlap | 0.550 | 0.317 |
| `clean_full_pose` | 38 | 0 |

同时 dx/dy 在不同 attempt 之间大幅跳动。最可能的原因是多个 outbound frame 仅依据累计 dead reckoning 重投影后直接拼接，帧间位姿误差使 submap 自身变模糊。

这不能证明多帧思想无效，只能说明当前“里程计重投影 + concatenate”实现不够可靠。

### 5.2 更合理的多帧实现

如果重新设计，建议：

- 在 anchor 前后约 1–2 m 范围积累真实运动帧；
- 相邻帧先做短基线 registration；
- 使用局部 pose graph 或滑窗优化；
- 对帧间不一致和动态遮挡做剔除；
- 用稳定结构或 voxel centroid 建图，而不是简单等间隔抽样；
- return 侧也构建短时间 causal submap；
- anchor 优先放在转角和高判别性位置；
- 对 submap 内部一致性单独输出 uncertainty。

在纯几何方案中，这是最可能带来显著提升的方向。

## 六、RGB-D/视觉融合的项目证据最强，但覆盖有限

项目的 LoFTR 后置视觉检查在修复相机 yaw 轴错误，并增加 match-count margin、RANSAC residual 和 minimum translation 三层 gate 后，获得：

- 困难 ICP 样本中，vision gate 允许输出时超过 97%的 yaw 准确率；
- 全体随机样本 gate-pass accuracy 约 95.9%；
- 全体样本 gate coverage 约 30.6%；
- 对 confidently-wrong ICP disagreement trigger：precision 94.4%，recall 20.5%。

这是一种高精度、低覆盖的独立信号，最适合：

- ICP 多 basin 选择；
- ICP 高置信但视觉明显不同意时降低 confidence；
- promotion 或 forced stop 等不可逆操作前复核；
- 几何退化区域的补充观测。

它不适合无条件替代 ICP，因为：

- 距离超过约 3–4 m 后匹配 coverage 很低；
- 极短 baseline 下视觉也会被自相似结构欺骗；
- 视觉 translation 比 yaw 更不稳定；
- 视觉同样需要 abstention。

因此更合理的架构是 LiDAR 与 RGB-D 互补，而不是二选一。

## 七、建议的优先级

### 优先级 1：可靠的运动积分多帧 submap

它直接解决单帧缺少判别信息的问题，但必须采用可靠帧间配准和局部优化，不能重复简单 dead-reckoning 拼接的实现。

### 优先级 2：RGB-D 独立复核

不无条件替换 ICP，而是在 ICP 高置信、视觉高置信且两者明显冲突时介入，尤其保护 promotion、stop 等关键决策。

### 优先级 3：时序 current/next 状态估计

利用多个时刻的距离趋势、运动方向、历史置信度和合法状态转移，而不是让每个单帧 ICP 独立决定当前状态。这也是 Anchor V3 所针对的问题层次。

### 优先级 4：更完整的 3D/2.5D 匹配

保留完整高度结构，使用平面、法向和垂直结构，作为二维 ICP 的补充。

### 优先级 5：判别性 Anchor 选点

根据转角、几何变化、视觉 distinctiveness 和局部可定位性保存 anchor，而不是机械地按累计距离截取瞬时帧。

### 优先级 6：点数、voxel 与 ICP objective 调参

适合作为低成本增量优化，但不应被当成恢复 oracle 水平的主要研究假设。

## 八、最终判断

更准确的判断不是“换一个更好的 ICP 就能解决”，而是：

> 需要改变输入信息和决策粒度，而不仅是改变单帧点集的优化器。

仅换成 GICP、NDT、TEASER++ 或更密集 brute-force，可能改善普通样本，但不太可能让 online 成功率接近 oracle。更可能明显缩小差距的组合是：

```text
可靠的短时多帧几何 submap
+ RGB-D 独立复核
+ 时序 current/next 状态估计
+ 对不确定状态的安全降级
```

即使匹配完全修好，也不能假定 online 会自动达到 oracle。项目中还存在 locomotion 卡死、current/next 报告对象、anchor 0 缺失、stop gate 和 hint-action 接口等问题。ICP/可靠性 coverage 是主要瓶颈之一，但不是唯一瓶颈。

## 九、项目内依据

- `investigations/数据补全/rq3_reliability_diagnostics_20260819.md`
- `investigations/2026-07-13-icp-bearing-error-cross-batch-deep-dive/`
- `investigations/2026-07-16-matching-primitive-strategy/`
- `investigations/2026-07-19-report-next-anchor-freezing-fix/`
- `investigations/2026-07-21-icp-reliability-signal/`
- `investigations/2026-07-26-camera-yaw-fix-and-residual-confidence-gate/`

