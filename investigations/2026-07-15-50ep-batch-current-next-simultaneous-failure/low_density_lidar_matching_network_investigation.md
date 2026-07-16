# 网络调查结论：低密度 LiDAR 下的 Current/Next 同时失效与替代匹配原语

## 1. 问题边界

本次调查严格按照 `FINDINGS(2).md` 中的要求展开：

- 不修改 `sequential_pair` 的 current/next 双锚点框架；
- 不优先重新设计 promotion、quarantine 或 VLM 提示逻辑；
- 研究对象仅限于单次“保存锚点点云—实时局部点云”之间的位姿匹配原语；
- 目标是替换或增强当前 `relocalization.py` 中的 `sequential_pair_anchor_relocalization` / `icp_rigid_transform_2d`；
- 新方法必须适应低密度点云，当前典型输入约为 512 点；
- 必须重点处理重复走廊、弱几何约束、局部极值、多峰匹配，以及同一真实位置下结果突然跳变的问题。

原始分析已经证明，剩余失败并不是机器人普遍离开已知路线，而是 ICP 在机器人真实位置几乎不变时，对同一锚点给出剧烈变化的结果；在最严重的情况下，current 和 next 两个候选锚点会同时产生错误读数。

已有两个替代方向也已经被实际测试：

1. Scan Context 在锚点选择准确率上不如当前 LiDAR/ICP 方法；
2. 后向相机 LoFTR 虽然能改善旋转估计，但平移和 bearing 明显更差，因此不再适合作为当前架构中的主要定位后端。

系统目前已经记录了以下诊断信号：

- `localizability`
- `yaw_curve`
- `icp_top_basins`
- ICP residual、overlap、confidence 等信息

但这些信号目前主要用于记录和分析，还没有真正参与匹配解的约束、拒绝或重加权。

---

## 2. 总体判断

当前问题不是一个简单的“找一个比 ICP 更强的全局描述子”问题，而是三个问题叠加：

1. 重复走廊产生多个几何上相似的局部最优解；
2. 某些 SE(2) 方向缺乏充分约束，但优化器仍然输出较大的更新；
3. 系统过早把一个多峰、不确定的匹配分布压缩成唯一的 `(dx, dy, dtheta)`。

因此，最适合当前项目的方向不是单独将 ICP 换成 GICP、NDT 或某个神经网络，而是构建一个分层匹配原语：

> **有界 SE(2) 多假设搜索 → 退化感知的局部精配准 → 多峰与方向性不确定度评分**

这一结构可以保留现有 sequential-pair 接口，同时直接针对以下两个已确认的故障现象：

- 同一真实位置下估计结果在不同 basin 之间突然跳变；
- current 和 next 两个相邻锚点同时错误。

---

# 3. 最值得优先研究的论文与开源项目

## 3.1 X-ICP：最直接对应当前故障机理

### 论文

**X-ICP: Localizability-Aware LiDAR Registration for Robust Localization in Extreme Environments**

论文链接：

- https://arxiv.org/abs/2211.16335

X-ICP 不只是根据 Hessian 的最小特征值判断当前匹配是否退化，而是分析 correspondence 对各个优化方向的约束能力，并将优化方向分成：

- 约束充分；
- 部分约束；
- 几乎无约束。

随后：

- 对约束充分的方向正常更新；
- 对弱约束方向进行限制或正则化；
- 对严重退化方向保持先验估计，不接受当前 ICP 给出的自由漂移。

这与本项目的故障高度一致。例如在长走廊中，横向位置和朝向可能被墙面很好地约束，但沿走廊方向的平移可能几乎不可观测。普通 ICP 仍然可能在该方向输出数米更新，进而产生错误 bearing。

### 开源项目

**leggedrobotics/perfectlyconstrained**

- https://github.com/leggedrobotics/perfectlyconstrained

这是后续研究 *Informed, Constrained, Aligned* 的官方代码，包含：

- X-ICP 退化检测；
- TSVD；
- soft regularization；
- hard constraints；
- nonlinear regularization；
- localizability-aware update。

该项目采用 MIT 许可证。

完整工程依赖 ROS Noetic、Open3D SLAM 和 libpointmatcher，因此不建议整体移植。更合理的做法是抽取：

- localizability 分类逻辑；
- 特征方向投影；
- constrained update；
- soft regularization。

### 对当前项目的意义

当前代码已经记录了 `localizability` 和特征值信息，因此 X-ICP 是最低成本、最高优先级的方向。

第一步甚至不需要更换 correspondence 搜索，可以直接对现有 ICP 增量进行方向投影：

\[
\Delta \xi_{\text{safe}}
=
V
\operatorname{diag}(w_1,w_2,w_3)
V^\top
\Delta \xi_{\text{ICP}}
\]

其中：

- \(V\) 为 Hessian 的特征向量；
- \(w_i\) 根据对应方向的可定位性设定；
- 约束充分方向取接近 1；
- 弱约束方向衰减；
- 严重退化方向取 0 或拉回先验。

### 局限

X-ICP 主要解决局部优化方向退化，但不能自动解决两个距离较远、得分接近的全局 basin。

因此它应与多假设粗搜索结合，而不是单独作为最终方案。

---

## 3.2 DRPM：最容易嵌入现有代码的概率化退化处理方法

### 论文

**Probabilistic Degeneracy Detection for Point-to-Plane Error Minimization**

论文链接：

- https://arxiv.org/abs/2410.10784

DRPM 不使用固定的“最小特征值低于阈值”规则，而是建模：

- 点位置噪声；
- 法向量噪声；
- 噪声如何传播到 Hessian；
- 各个优化方向发生退化的概率。

然后根据退化概率平滑地衰减相应方向的更新。

相比固定阈值，它的优势是参数可以根据传感器噪声设定，而不是为每个场景重新调节。

### 开源项目

**ntnu-arl/drpm**

- https://github.com/ntnu-arl/drpm

项目采用 MIT 许可证，核心实现集中在较小的 `degeneracy.h` 文件中，适合直接嵌入现有注册代码。

### 对当前项目的适用性

DRPM 可以作为第一个实验性补丁：

1. 输入现有 ICP Hessian；
2. 为 SE(2) 的 \(x,y,\theta\) 三个方向计算退化概率；
3. 对高退化概率方向降低更新幅度；
4. 将退化概率直接映射到 `confidence`。

### 局限

原方法主要建立在 point-to-plane error 上。如果当前实现是纯 2D point-to-point ICP，则需要：

- 改为 point-to-line ICP；或
- 重新推导 2D residual 噪声对 Hessian 的传播。

即便如此，它的概率化 confidence 思路仍然比简单特征值阈值更适合当前问题。

---

## 3.3 GenZ-ICP：最值得测试的 ICP 目标函数替代方案

### 论文

**GenZ-ICP: Generalizable and Degeneracy-Robust LiDAR Odometry Using an Adaptive Weighting**

论文链接：

- https://arxiv.org/abs/2411.06766

GenZ-ICP 的核心不是完全抛弃 ICP，而是在 point-to-plane 和 point-to-point 之间进行自适应加权。

- point-to-plane 在平面结构上精度高；
- 但在长走廊等退化场景中容易形成病态优化；
- point-to-point 精度可能较低，但平移 Hessian 更稳定；
- GenZ-ICP 根据局部 planarity 动态调整两类 residual 的权重。

论文专门在 corridor-like degenerative scenarios 中进行了验证。

### 开源项目

**cocel-postech/genz-icp**

- https://github.com/cocel-postech/genz-icp

项目特点：

- IEEE RA-L 2025；
- MIT 许可证；
- 提供 C++；
- 提供 Python；
- 支持 ROS 1；
- 支持 ROS 2；
- 提供参数调节说明和预设配置。

### 对当前项目的价值

如果锚点描述和实时局部地图保留了足够的三维结构，可以直接进行离线 replay。

如果最终匹配仍然是 2D BEV，则可以借用其思想实现：

\[
E =
\sum_i
w_i^{\text{line}} E_i^{\text{point-to-line}}
+
\lambda_i E_i^{\text{point-to-point}}
\]

在墙体和长边等线结构可靠时，提高 point-to-line 权重；当局部法向量不可靠或 Hessian 退化时，增加 point-to-point 稳定项。

### 主要风险

当前默认点数仅约 512 点。在这种密度下：

- 法向量估计可能不稳定；
- 局部协方差可能不稳定；
- planarity 估计可能失真。

因此必须进行点密度消融，而不能直接采用论文中的默认参数。

---

## 3.4 Cartographer 式 Correlative Scan Matching：解决错误 basin 的关键组件

普通 ICP 依赖初始值，并且每次只沿局部梯度迭代。当重复走廊中存在多个合理对齐时，它容易被某个错误 basin 捕获。

Google Cartographer 的 2D 匹配采用相关匹配：

1. 将参考扫描转换为概率栅格或距离变换图；
2. 在有限的 \(x,y,\theta\) 搜索窗口中评估候选位姿；
3. 使用多分辨率搜索；
4. 使用 branch-and-bound 排除不可能区域；
5. 找到一个或多个较好粗略解后，再使用连续优化精修。

相关文档：

- https://google-cartographer-ros.readthedocs.io/en/latest/algo_walkthrough.html
- https://github.com/cartographer-project/cartographer

### 为什么适合当前项目

当前每次输入最多约 512 点，最终只需要估计 SE(2)。因此，在一个有限窗口内做粗粒度 \(x,y,\theta\) 搜索并不一定昂贵。

更重要的是，相关匹配可以自然产生：

- 最优峰；
- 第二候选峰；
- 第三候选峰；
- 峰间得分差；
- basin 宽度；
- 多峰熵；
- 不同 yaw basin 的竞争关系。

这比普通 ICP 的单一 fitness score 更适合识别重复走廊中的多解。

### 不应只保留 Top-1

相关匹配同样可能在重复走廊中选择错误峰。因此不应采用：

> 找到 Top-1 → 直接作为最终解。

更合理的方案是：

> 保留 Top-K 独立 basin → 对每个 basin 分别精配准 → 综合 localizability、残差、先验一致性和峰间差进行选择或拒绝。

这可以直接利用项目已经记录的：

- `yaw_curve`
- `icp_top_basins`

---

## 3.5 CSM / Point-to-Line ICP：适合作为精修层

### 开源项目

**AndreaCensi/csm**

- https://github.com/AndreaCensi/csm

CSM 是经典的 2D Canonical Scan Matcher，实现了 Point-to-Line ICP 等方法，采用 LGPL-3.0 许可证。

### 适用性

室内走廊中的墙面通常更适合 point-to-line residual，因为它能充分利用线结构。

但它有天然局限：

- 垂直墙面的横向距离约束很强；
- 朝向约束可能较强；
- 沿走廊轴线方向的平移可能几乎没有约束。

因此，CSM 或 PLICP 最适合作为精配准层：

> Correlative Top-K → PLICP 精修 → X-ICP/DRPM 方向约束。

如果只把当前 ICP 换成 PLICP，可能减少部分噪声，但无法消除沿走廊方向滑移和重复位置 alias。

---

## 3.6 ICET：值得加入实验矩阵的分布式方法

### 论文

**Enhanced Laser-Scan Matching with Online Error Estimation for Highway and Tunnel Driving**

论文链接：

- https://arxiv.org/abs/2207.14674

ICET 是对 NDT 的改进。它将扫描划分为 voxel，在每个 voxel 中拟合局部高斯分布，并识别大平面或长墙造成的几何歧义。

其重要特征是：

- 抑制由大平面导致的错误方向更新；
- 输出位姿估计协方差；
- 专门讨论 tunnel/highway 等退化场景；
- 可以将不确定性直接传播给上层模块。

### 开源项目

**mcdermatt/ICET**

- https://github.com/mcdermatt/ICET

提供：

- ROS C++ 实现；
- Python 实现；
- Jupyter Notebook 示例。

### 优势

ICET 输出的不只是 transform，还包括误差协方差。这可以直接映射为：

- `confidence`
- `match_class`
- bearing uncertainty
- “是否应该产生精确 hint”的判断

### 风险

ICET/NDT 需要每个 voxel 中有足够点数估计均值和协方差。

当前只有约 512 点，再划分 voxel 后可能出现：

- 很多 voxel 点数不足；
- 协方差估计不稳定；
- 稳定结构数量过少。

因此 ICET 应作为重点 baseline，而不是第一版唯一后端。

---

## 3.7 SuperLoc：适合作为风险预测器

### 论文

**SuperLoc: The Key to Robust LiDAR-Inertial Localization Lies in Predicting Alignment Risks**

项目与论文方向强调：不要等配准已经失败后再看 residual，而是在优化之前预测不同方向上的 alignment risk。

### 开源项目

**superxslam/SuperOdom**

- https://github.com/superxslam/SuperOdom

项目支持：

- ROS 2 Humble；
- LiDAR-only 模式；
- alignment risk prediction；
- 6-DoF degeneracy uncertainty；
- 多种 LiDAR。

### 为什么不适合第一步整体迁移

完整系统依赖：

- ROS 2；
- PCL；
- GTSAM；
- Ceres；
- Sophus；
- 完整三维扫描。

而当前项目的核心输入是低密度局部点云和 SE(2) 匹配。

因此更合理的使用方式是：

1. 研究其用于预测 alignment risk 的几何特征；
2. 抽取相似特征到当前 512 点局部扫描；
3. 离线验证风险分数是否能预测 `bearing_error > 45°`；
4. 将其作为 confidence gate，而不是完整 SLAM 后端。

---

# 4. 适合作为 baseline、但不应作为主方案的项目

## 4.1 small_gicp

项目：

- https://github.com/koide3/small_gicp

支持：

- ICP；
- Point-to-Plane；
- GICP；
- VGICP；
- C++；
- Python；
- 输出最终 Hessian。

许可证为 MIT。

它非常适合搭建统一离线 benchmark，因为可以在相同数据上快速测试不同经典注册方法。

但 GICP/VGICP 本身不会自动解决：

- 重复走廊的多峰；
- 错误 basin；
- 弱方向上的错误高置信输出。

---

## 4.2 ndt_omp

项目：

- https://github.com/koide3/ndt_omp

提供并行 NDT 和 GICP，可作为速度和精度 baseline。

主要限制仍然是：

- 512 点下 voxel distribution 可能不稳定；
- NDT 也可能在重复走廊中产生局部极值；
- 默认输出并不等于可靠的多峰置信度。

---

## 4.3 TEASER++

项目：

- https://github.com/MIT-SPARK/TEASER-plusplus

TEASER++ 对包含大量 outlier 的 correspondence 集合具有很强鲁棒性，并且提供可认证的配准结果。

但它依赖一个基本前提：

> 必须先获得具有一定几何意义的跨点云 correspondence。

当前问题中，重复走廊可能导致 correspondence 本身系统性地落在错误结构上。因此 TEASER++ 不能直接解决候选位置的对称性和 alias。

它更适合测试：

- 已经有较可靠 feature correspondence；
- 但 correspondence 中包含大量随机外点。

---

## 4.4 KISS-Matcher

KISS-Matcher 适合粗到细的全局点云配准。

但当前问题不是任意两帧之间的全局注册，而是：

- 候选锚点已经被限制在 current/next；
- 需要在局部范围内稳定估计 SE(2)；
- 需要识别多峰和退化。

因此它不是最高优先级。

---

## 4.5 Multi-Hypothesis Scan Matching

已有研究明确采用：

- Monte Carlo 生成多个 roto-translation 假设；
- 在 SE(2) 空间聚类；
- 保留多个可能解；
- 而不是直接压缩成唯一 ICP 输出。

相关论文：

- https://arxiv.org/abs/2201.03814

这一思想与当前已有 `top_basins` 和 `yaw_curve` 数据高度一致。

主要问题是目前没有发现一个足够成熟、可直接嵌入当前代码的官方轻量实现，因此更适合作为算法设计参考。

---

# 5. 为什么这些方案可能成功，而 Scan Context 和 LoFTR 没有成功

## 5.1 Scan Context 解决的是位置检索，不是局部连续位姿退化

Scan Context 主要回答：

> 当前扫描最像整条路线中的哪个位置？

但当前 sequential-pair 已经把候选限制为 current 和 next。

实际失败发生在：

> 已经指定某个锚点后，该锚点与实时扫描之间的连续位姿估计发生跳变。

因此它解决的是：

- place recognition；
- anchor retrieval；

而当前核心问题是：

- 局部 SE(2) 多峰；
- 弱约束方向；
- 错误 basin；
- confidence 失真。

这也是 Scan Context 在先前实验中没有解决问题的原因。

---

## 5.2 LoFTR 能改善旋转，但无法稳定恢复平面平移

LoFTR 的图像 correspondence 到机器人平面平移之间存在多个不稳定因素：

- 深度未知；
- 视差；
- 遮挡；
- 近景与远景特征混合；
- 相机旋转和机器人平移耦合；
- 后向相机视角变化；
- 非平面场景。

因此它可以改善相对旋转，却不一定改善：

- `dx`
- `dy`
- bearing
- remaining distance

这与先前实验中“旋转明显更准，但平移-derived bearing 更差”的结果一致。

---

## 5.3 推荐方案的本质差异

推荐方案不尝试通过另一个全局描述子或另一个传感器直接猜出平移，而是：

1. 继续使用 LiDAR 几何估计平移；
2. 显式保留多个可能的 SE(2) 解；
3. 只在几何充分约束的方向上更新；
4. 将多峰和退化转换为低 confidence；
5. 避免输出一个错误但高置信的 transform。

---

# 6. 推荐的最终匹配原语

建议将新函数设计为：

```text
match_anchor(anchor_cloud, live_cloud, prior_transform)
    ↓
1. preprocessing / geometry extraction
    ↓
2. bounded correlative SE(2) search
    ↓
3. retain top-K separated basins
    ↓
4. refine each basin with adaptive point-to-line + point-to-point ICP
    ↓
5. X-ICP / DRPM directional degeneracy handling
    ↓
6. multi-hypothesis scoring and uncertainty estimation
    ↓
(dx, dy, dtheta, confidence, match_class, diagnostics)
```

---

## 6.1 预处理

建议同时生成两种表示：

### 点集表示

用于：

- ICP；
- PLICP；
- GICP；
- GenZ 风格精修。

### BEV occupancy / distance-transform grid

用于：

- bounded correlative search；
- 多分辨率搜索；
- Top-K basin 生成。

### 点采样不应只做均匀随机截断

当前最多保留约 512 点。如果简单均匀或随机采样，点可能主要来自两侧长墙，而缺少真正有区分度的结构。

建议优先保留：

- 墙角；
- 线段端点；
- 高曲率区域；
- 不同方位角区间中的代表点；
- 稳定垂直结构；
- 局部 occupancy 变化较大的点。

---

## 6.2 有界 SE(2) 粗搜索

以先验 transform 为中心搜索：

\[
x \in [x_0-r_x,x_0+r_x]
\]

\[
y \in [y_0-r_y,y_0+r_y]
\]

\[
\theta \in [\theta_0-r_\theta,\theta_0+r_\theta]
\]

建议采用多分辨率：

1. 粗层快速筛选；
2. 中层局部细化；
3. 非极大值抑制；
4. 保留至少 3–5 个彼此分离的 basin。

搜索范围应根据现有失败数据中的真实误差分布设定，而不是直接照搬 Cartographer 参数。

---

## 6.3 分别精修 Top-K basin

每个 basin 分别运行一个精配准器：

- PLICP；
- GenZ 风格混合 residual；
- 当前 ICP + robust kernel；
- GICP 作为对照。

这样可以避免一次错误初始化直接决定最终结果。

---

## 6.4 方向性退化处理

对每个候选解计算 SE(2) Hessian：

\[
H = J^\top WJ
\]

不能只记录 eigenvalue，而应真正作用到更新：

- well-constrained：正常更新；
- partially constrained：soft regularization；
- unconstrained：保持 prior；
- 极端退化：拒绝该候选或只返回 qualitative uncertainty。

这一层可以从以下方向借鉴：

- X-ICP；
- DRPM；
- perfectlyconstrained。

---

## 6.5 多假设 confidence

建议 confidence 至少包含：

\[
C =
f(
s_1-s_2,\;
H,\;
\text{residual},\;
\text{overlap},\;
\text{temporal consistency}
)
\]

其中：

- \(s_1-s_2\)：最佳峰和第二峰的得分差；
- \(H\)：方向可定位性；
- residual：精配准误差；
- overlap：有效重叠率；
- temporal consistency：连续 attempts 是否稳定落在同一 basin；
- basin width：最优峰是否尖锐；
- peak entropy：候选分布是否多峰。

尤其要避免：

> residual 很小，因此 confidence 很高。

在重复走廊中，错误位置也可能产生很小 residual。

必须同时检查：

- 解是否唯一；
- 各方向是否可观测；
- 解是否与短期历史一致。

---

# 7. 推荐实验顺序

## 阶段 1：先验证现有诊断信号是否已经足够

在不更换 ICP correspondence 的情况下增加三项离线实验：

1. 使用 `localizability` 对弱方向更新进行投影或衰减；
2. 使用 `yaw_curve`、`icp_top_basins` 判断是否多峰；
3. 当 Top-1 与 Top-2 接近时，不允许输出高置信位姿。

这是最高优先级，因为这些信号已经被计算并记录，不需要先引入大型依赖。

需要重点检查：

- `ep134`
- `ep367`
- `ep214`
- `ep498`
- 其他已知同时 current/next 错误的片段

目标是判断这些信号能否在 catastrophic bearing error 发生前或发生时将结果标记为 uncertain。

---

## 阶段 2：统一离线 replay

建议建立统一测试矩阵：

| 编号 | 方法 |
|---|---|
| A | 当前 ICP |
| B | 当前 ICP + X-ICP/DRPM 方向约束 |
| C | Correlative Top-K + 当前 ICP |
| D | Correlative Top-K + PLICP + DRPM |
| E | Correlative Top-K + GenZ 风格混合目标 |
| F | ICET |
| G | NDT |
| H | GICP/VGICP |

必须对所有方法使用相同：

- anchor cloud；
- live scan；
- prior；
- voxel 设置；
- max points；
- ground-truth evaluation。

---

## 阶段 3：点密度消融

每种方法至少测试：

- 256 点；
- 512 点；
- 1024 点；
- 未截断点云。

同时测试 voxel：

- 0.05 m；
- 0.10 m；
- 0.20 m。

这样可以判断某种方法失败的原因究竟是：

- 算法不适合；
- 法向量估计不稳定；
- voxel covariance 不稳定；
- 512 点不足；
- 预处理破坏了结构。

---

## 阶段 4：闭环验证

必须先在历史原始记录上证明：

- catastrophic bearing error 减少；
- current+next simultaneous bad rate 降低；
- false-safe rate 降低；
- 正常匹配没有明显退化。

之后再放回 shadow 闭环。

否则闭环轨迹改变后，很难判断成功来自：

- 匹配算法改善；
- VLM 行为偶然改变；
- 路径变化；
- 初始视角变化；
- 随机性。

---

# 8. 评价指标

不能只看 ICP fitness 或最终 round-trip success。

## 8.1 单次匹配精度

- translation error；
- yaw error；
- bearing error；
- `bearing_error > 10°` 比例；
- `bearing_error > 45°` 比例；
- remaining-distance error；
- anchor identity correctness。

---

## 8.2 稳定性

重点针对 `ep134` 一类“真实位置几乎不变、估计结果突然跳变”的故障：

- 当机器人真实位置变化小于阈值时，估计 transform 的最大跳变；
- 相邻 attempt 的 bearing jump；
- basin identity switch 次数；
- 连续错误输出长度；
- 同一锚点估计方差；
- 固定位置下的多峰占比。

---

## 8.3 Current/Next 联合指标

必须单独计算：

\[
P(\text{current bad} \land \text{next bad})
\]

因为当前真正导致系统卡死的是两个角色同时错误。

只改善平均单锚点精度，不一定解决这一结构性失败。

还应记录：

- current bad / next good；
- current good / next bad；
- current bad / next bad；
- 两者同时 high confidence but wrong；
- 两者同时 uncertain；
- 两者输出是否落在同一个错误 basin。

---

## 8.4 Confidence 校准

定义 catastrophic match，例如：

\[
\text{bearing error} > 45^\circ
\]

然后计算：

- AUROC；
- AUPRC；
- Brier score；
- Expected Calibration Error；
- false-safe rate；
- false-reject rate；
- Top-K oracle recall。

其中最重要的是：

> **false-safe rate：错误匹配却给出高 confidence 的比例。**

当前系统真正危险的不是返回 uncertain，而是 confidently wrong。

---

# 9. 最终优先级

## 第一优先级：现有 ICP + X-ICP/DRPM

理由：

- 改动最小；
- 可以直接使用已有 localizability；
- 可快速验证弱方向约束是否能消除固定位置大幅跳变；
- 不需要首先迁移大型 SLAM 框架。

---

## 第二优先级：加入 Correlative Top-K 粗搜索

理由：

- 这是处理错误 basin 和多峰歧义的核心；
- 单独做退化约束，仍可能稳定收敛到错误 basin；
- 与现有 `yaw_curve` 和 `icp_top_basins` 高度兼容。

---

## 第三优先级：GenZ 风格混合 residual

理由：

- 可以改善纯 point-to-line / point-to-plane 在走廊中的病态问题；
- 可以通过 point-to-point 项为平移提供稳定性；
- 有官方开源代码。

---

## 第四优先级：ICET

理由：

- 直接输出 covariance；
- 对 tunnel/corridor 退化有针对性；
- 适合测试 uncertainty 是否比当前 confidence 更可靠。

风险是 512 点下 voxel covariance 可能不稳定。

---

## 第五优先级：SuperLoc 风险特征

只有在确定性几何信号仍无法区分好坏匹配时，再考虑引入学习式风险预测。

不建议第一步迁移完整 SuperOdom。

---

## 仅作为 baseline

- NDT；
- GICP；
- VGICP；
- small_gicp；
- ndt_omp；
- CSM。

它们适合比较，但单独使用都没有同时解决：

- 多峰；
- 错误 basin；
- 方向退化；
- 高置信错误。

---

## 不建议优先重新尝试

- Scan Context；
- Scan Context++；
- BEVPlace；
- OverlapTransformer；
- LoFTR；
- TEASER++；
- KISS-Matcher。

这些方法主要解决：

- 全局位置检索；
- 全局 registration；
- 图像特征匹配；
- correspondence outlier；

而当前主要问题是：

- 已知相邻锚点条件下的局部 SE(2) 多解；
- 几何退化；
- basin 跳变；
- confidence 失真。

---

# 10. 最终结论

最可行的方向不是寻找一个“比 ICP 更强的单一算法”，而是将当前单解 ICP 改造成一个：

> **退化感知、多假设、带方向性不确定度的局部 SE(2) 匹配器**

最值得立即实现和验证的版本是：

> **Cartographer 式 bounded correlative Top-K 搜索**  
> **+ GenZ/PLICP 风格局部精修**  
> **+ X-ICP 或 DRPM 方向约束**  
> **+ 基于峰间差、Hessian 和时间稳定性的 confidence**

这一方案具有以下优点：

1. 与当前 `sequential_pair` 接口兼容；
2. 不需要修改 current/next 控制框架；
3. 能显式处理重复走廊中的多峰；
4. 能防止弱约束方向产生大幅错误更新；
5. 能把“无法确定”正确表达为低 confidence；
6. 能具体解释为什么它可能成功，而 Scan Context 和 LoFTR 没有成功；
7. 可以先在已有历史数据上离线验证，再进入闭环测试。

最优先的实际下一步不是立刻迁移大型算法，而是：

1. 对现有 ICP 增量加入 localizability-aware directional projection；
2. 利用现有 `yaw_curve` 和 `icp_top_basins` 构建多峰拒绝规则；
3. 离线评估这些规则能否提前识别 current/next 同时错误；
4. 随后再加入 bounded correlative Top-K 粗搜索；
5. 最后比较 PLICP、GenZ 风格目标和 ICET 作为精修后端。
