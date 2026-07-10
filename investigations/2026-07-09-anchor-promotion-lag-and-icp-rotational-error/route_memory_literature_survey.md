# Round-Trip LiDAR Route Memory：Failure Modes 网络调查与改进方向

> 基于 4 份项目文件，尤其是 `FINDINGS (1).md`，并结合外部文献/项目调研整理。本文不包含重新跑实验的结果；所有项目内部判断均基于已有 hard-11 批量结果、代码逻辑和文件中的分析。

---

## 0. 对当前问题的核心理解

当前系统是：outbound 阶段每隔约 1 m 存一个 LiDAR local-map anchor；return 阶段只维护 `(current, next)` 两个候选 anchor，`next = current - 1`，每次对 current 和 next 都跑 2D ICP，然后根据证据决定是否把 next 提升为 current。

`FINDINGS (1).md` 中明确指出，当前 live 配置是：

- `bounded_evidence`
- `alias_aware`
- `belief closure`
- `trust_aware_guard`

同时，ICP 的 `match_class`、`near_tie_basin_count`、`corridor_degeneracy_ratio` 等目前主要是 diagnostic，不是硬 gate。

我认为两个 open failure mode 应该分开处理：

### 问题 1：promotion timing 不是“ICP质量问题”，而是在线状态转移提交时机问题

当前的 3-of-5 sliding vote 相当于一个简化 debounce / hysteresis。它能防止 immediate promotion 一路冲过重复结构，但会产生两类相反错误：

- 过早提交导致 overshoot；
- 过晚提交导致 lag / next-behind。

文件里最关键的证据是：

- current exact 只有 55.9%；
- overshoot 21.3%；
- lag-1 13.8%；
- lag-2+ 9.0%；
- next exact 56.4%；
- next-behind 25.1%。

而且 overshoot 绝大多数是 magnitude-1，promoted anchor 的 ICP 反而更 clean、更高 overlap。因此这不是坏 ICP 数据混进来，而是 vote window 本身提前确认。

### 问题 2：bearing error 不是普通 near-tie 或 corridor degeneracy，而是“旋转维度的自信错误”

accepted readings 里 bearing error >10° 的有 39.0%；其中 69.0% 没有：

- `icp_near_tie_basin_count > 0`
- `match_class` flag
- elevated `corridor_degeneracy_ratio`

文件中最典型的例子是 `ep1040 / anchor4`：

- dx/dy 小且合理；
- dθ 稳定错到 120–170°；
- 仍然是 `clean_full_pose`；
- overlap 0.75–0.91；
- inliers 350–460。

这说明当前 ICP 质量指标能判断“点云重合得好不好”，但不能判断“旋转估计是否可信”。

代码层面也支持这个判断：`RouteMemoryAgent` 的 promotion 是在 `_select_sequential_pair_relocalization()` 里通过 `close_enough / trend_ok / quality_ok` 形成 candidate vote，再由 `_record_promotion_vote()` 做固定窗口投票；alias-aware 只是改 window/min_votes，并有 stall relief。`relocalization.py` 端则是 24 个 yaw seed 的 ICP sweep，再按 basin score ratio 判 near-tie；localizability Hessian 已经有雏形，但目前并不能解释 69% 的 clean-but-wrong bearing。

---

## 1. 网络调查结果：问题 1 应该借鉴哪些方向

### 1.1 Sequential Probability Ratio Test / SPRT：最贴近“何时 promotion”的统计框架

SPRT 本质上就是针对两个假设持续接收证据，累积 log-likelihood ratio，超过上阈值就接受 H1，低于下阈值就接受 H0，否则继续观测。阈值可以由目标 Type-I / Type-II error 设定。

这正好对应当前的 `current` vs `next`：

- H0：仍在 current；
- H1：应该切到 next。

SPRT 也被证明具有早停意义上的最优性，这比固定 3-of-5 vote 更有原则。

参考：

- Sequential probability ratio test, Wikipedia: <https://en.wikipedia.org/wiki/Sequential_probability_ratio_test>

我建议不是直接手写理论分布，而是用 offline replay 数据拟合一个校准过的 evidence model：

```math
\ell_t = \log \frac{p(e_t \mid \text{next should be current})}{p(e_t \mid \text{stay at current})}
```

其中 `e_t` 可以包括：

- `next_quality / current_quality`
- `next.distance_to_anchor_m`
- distance trend
- `overlap_ratio`, `median_residual`, `inlier_count`
- current-next closure disagreement z-score
- odometry-estimated progress within the current anchor interval
- anchor alias_score / localizability / route curvature

然后：

- promote if cumulative LLR > adaptive upper bound；
- retain if cumulative LLR < lower bound；
- otherwise keep collecting evidence；
- 加一个 truncated / max-dwell 机制，避免 episode 5 那种全程 self-similar 导致永远不 promotion。

这比 3-of-5 的好处是：强证据可以更快过阈值，弱证据需要更多帧；不会把每个 episode / anchor 都强行套同一个窗口。

---

### 1.2 Bayesian Online Change Point Detection：把 anchor boundary 当作 change point

Bayesian Online Change Point Detection 关注在线检测数据生成过程的 abrupt change。Adams & MacKay 的 BOCPD 被用于 finance、biometrics、robotics 等在线场景。机器人领域里，PLISS 用 online Bayesian change-point detection 来分割 image stream、检测 place boundary，而不是每一步做不可逆决策。

参考：

- Adams & MacKay, Bayesian Online Changepoint Detection: <https://arxiv.org/abs/0710.3742>
- PLISS, Place recognition using online Bayesian change-point detection: <https://www.roboticsproceedings.org/rss06/p24.html>

这和你的问题非常接近：promotion 本质上是在判断“机器人是否已经跨过从 current 到 next 的边界”。所以可以把每个 anchor dwell period 建成一个 run-length / hazard model：

- hazard 由 anchor spacing、机器人速度、预计 dwell time 决定；
- evidence 由 current/next ICP likelihood 决定；
- posterior 输出 `P(boundary_crossed | observations so far)`；
- 当 posterior 超过阈值才 promotion。

这个方法比 SPRT 更自然地融合“预计什么时候该跨过边界”。它能直接处理当前的 overshoot：如果 ICP 很像 next，但 odometry / dwell-time posterior 认为还没到 boundary，就不会立刻 promote。

---

### 1.3 HMM / Bayesian filter / sequence-based place recognition：不要只看一帧，也不要只看局部 vote

视觉地点识别领域已经反复证明：单帧 place recognition 容易被重复结构误导，sequence-based filtering 可以明显提升稳定性。SeqSLAM 的关键思想就是不只找当前图像最像哪个地方，而是在局部导航序列中找最一致的匹配。

参考：

- SeqSLAM: <https://ieeexplore.ieee.org/document/6224623/>
- PlaceNav: <https://arxiv.org/abs/2309.17260>

对当前系统，最小改动不是全局 SeqSLAM，而是一个单调 HMM / two-state forward filter：

- state 只允许 `current` 或 `next`；
- transition 只允许 stay 或 `current -> next`；
- transition probability 由 expected dwell / odometry progress 控制；
- emission likelihood 来自 ICP metrics；
- 输出 posterior：`P(current)`, `P(next)`；
- promotion 条件从“3-of-5 通过”改为 `P(next) > τ(anchor)`。

这能保留现在“最多推进一个 anchor、不回退、不跳跃”的结构保证，同时把固定 vote window 变成概率滤波。

---

## 2. 网络调查结果：问题 2 应该借鉴哪些方向

### 2.1 ICP uncertainty / covariance：现有 ICP metric 天然可能过度自信

文献里对 ICP 不确定性的一个共识是：ICP 的误差来源包括 wrong convergence、sensor noise、underconstrained geometry 和 local minima。Brossard 等关于 ICP covariance 的论文还特别指出，ICP uncertainty 强依赖 initialization，并且 “wrong convergence” 不是简单 covariance 公式能处理的。

参考：

- Brossard et al., ICP covariance survey / uncertainty discussion: <https://arxiv.org/pdf/1909.05722>
- Stein ICP: <https://arxiv.org/abs/2106.03287>

这与当前 69% clean-but-wrong bearing 非常一致：不是 residual 高，而是 ICP 以为自己对了。

Censi 的 ICP covariance 是经典方向，但当前失败更像“收敛到错误旋转 basin 且 basin 还很强”，所以普通 covariance / residual 不一定够。更值得借鉴的是后续的 probabilistic ICP / Stein ICP：它强调点估计不够，需要估计 transformation parameters 的多峰不确定性，尤其在 ambiguous environment 和 occlusion 下。

可落地方案：不要只输出一个 `(dx, dy, dθ)` 和 scalar score，而是至少输出一个 orientation likelihood curve：

- 固定 yaw grid，例如 24 或 72 个 yaw；
- 对每个 yaw，在局部优化 translation；
- 得到 `score(θ)`；
- 计算 circular entropy、top-1/top-2 gap、峰宽、峰偏斜；
- 如果 score curve 很平、很宽，或存在多个稳定高分区域，就标记 rotation unreliable；
- 如果 top-1 很尖但与 odometry yaw prior / adjacent-anchor edge yaw 强冲突，也标记 suspicious。

当前 `near_tie_basin_count` 只看 basin score ratio ≥0.85 和 pose delta；它抓不到“单个 basin 明显胜出但 orientation 与外部约束不一致”的情况。

---

### 2.2 Localizability-aware ICP：不要只看 anchor 自身 PCA，要看“当前 correspondences 对 yaw 的约束”

X-ICP 是非常相关的方向：它提出 fine-grained localizability detection，用 scan-to-map correspondences 分析 alignment strength 在优化主方向上的约束，并在弱约束方向上限制或冻结更新，而不是盲目相信 ICP。

LP-ICP 也沿着这个方向，把点到线/点到面约束和 localizability detection 结合，用 hard/soft constraints 处理 ill-conditioned directions。

参考：

- X-ICP: <https://arxiv.org/abs/2211.16335>
- LP-ICP: <https://arxiv.org/abs/2501.02580>

这对当前系统非常重要，因为 `corridor_degeneracy_ratio` 是 anchor point cloud 的 pre-ICP 几何分数，已经被证明不能区分 wrong-bearing；而 X-ICP 类方法看的是当前匹配 correspondences 的 Jacobian / Hessian 对每个 DoF 的信息贡献。

`relocalization.py` 里已经有 `_localizability_from_correspondences()`，它计算 normal constraint Jacobian、Hessian eigenvalues、condition number 和 weakest direction。下一步不是再调 `corridor_degeneracy_ratio`，而是把这个 correspondence-level localizability 拆到 yaw 维度：

- 计算 yaw column 的 Fisher information / Hessian contribution；
- 判断 weakest eigenvector 是否主要落在 yaw 维；
- 输出 `yaw_observability_score`；
- 当 yaw 不可观测时，不要把 `anchor_dtheta_rad` 当 clean；
- bearing hint 可以仍用 dx/dy，但 `anchor_heading_reliable=False`，或者 bearing 由短时 odometry / anchor edge 几何补充。

---

### 2.3 Correlative scan matching / Cartographer：用全局 yaw search 验证 ICP，而不是只用 ICP basin

Olson 的 real-time correlative scan matching 是 2D scan matching 的经典方法，目标是在搜索窗口内评估 pose，而不是依赖局部 ICP。Cartographer 的 FastCorrelativeScanMatcher 用 branch-and-bound 在多分辨率 grid 上加速，并被用于实时 loop closure。

参考：

- Olson, Real-time correlative scan matching: <https://april.eecs.umich.edu/pdfs/olson2009icra.pdf>
- Cartographer algorithm walkthrough: <https://github.com/googlecartographer/cartographer_ros/blob/master/docs/source/algo_walkthrough.rst>

这对 bearing error 特别有价值：不一定要替代 ICP，可以把它作为低频 verifier：

- 对 accepted ICP pose，在 yaw 附近 ±180° 或 ±90° 做 correlative occupancy scoring；
- 得到一个 yaw-score distribution；
- 如果 ICP yaw 不是 correlative score 的稳定峰，降权或拒绝 yaw；
- 对 worst anchors 或 high-risk anchors 才触发，避免实时成本太高。

相比直接切 point-to-line / NDT，这个更对症，因为文件里已经说明“同一 viewpoint 上提高点密度或换 ICP cost function 已经不值得继续投入”。

---

### 2.4 Scan Context / Scan Context++：用结构描述子做 yaw 候选或验证

Scan Context 是 LiDAR place recognition 的经典全局描述子，把 3D scan 编码成 egocentric matrix，并支持通过 column shift 搜索 yaw。Scan Context++ 进一步强调对 rotation 和 lateral variation 的鲁棒性，并在 topological retrieval 后做 1-DoF semi-metric localization。官方代码也描述 Scan Context 是为 sparse/noisy LiDAR 点云设计的全局描述子。

参考：

- Scan Context paper: <https://ieeexplore.ieee.org/document/8593953/>
- Scan Context original PDF: <https://gisbi-kim.github.io/publications/gkim-2018-iros.pdf>
- Scan Context++: <https://arxiv.org/abs/2109.13494>
- Scan Context GitHub: <https://github.com/gisbi-kim/scancontext_tro>

当前代码里已经有 `scan_context_anchor_relocalization` 路线和 fused backend。建议不要把 Scan Context 当作全局搜索 backend，而是针对 sequential_pair 做一个轻量版本：

- 只对 current/next 两个 anchor 计算 Scan Context yaw shift；
- 用它给 ICP yaw 加 prior 或 veto；
- 如果 ICP yaw 与 Scan Context yaw 差 > 某阈值，而 dx/dy 又很可信，则把 yaw 标为 unreliable；
- 对 reverse revisit 情况特别有用，因为 Scan Context 原论文也强调了 reverse revisit / corner 场景下的 loop detection。

---

### 2.5 TEASER++ / global registration：适合 offline verifier，不适合直接替代每步 ICP

TEASER++ 是 certifiably robust point cloud registration library，有 C++、Python、MATLAB binding，目标是在高 outlier correspondence 下给出 robust/certifiable registration。

参考：

- TEASER++ paper: <https://arxiv.org/abs/2001.07715>
- Open3D ICP tutorial: <https://www.open3d.org/docs/release/tutorial/pipelines/icp_registration.html>
- Open3D global registration tutorial: <https://www.open3d.org/docs/release/tutorial/pipelines/global_registration.html>

TEASER++ 很强，但当前场景是 2D local LiDAR、每 5 sim steps 频繁跑、candidate 只有两个；问题也不是 outlier correspondence 主导，而是局部几何旋转歧义。因此不建议直接替换 live ICP。

更合理的用法：

- 在 offline replay dataset 上跑 TEASER++ / Open3D global registration / correlative matching；
- 对 `ep1040 / anchor4` 这类失败组，验证是否存在另一个全局解；
- 如果全局 verifier 能抓到 yaw 错误，再把简化版 verifier 移植到 live pipeline。

Open3D 也把 ICP 明确归为 local registration，需要 rough initialization；global registration 不依赖初值但通常结果没 ICP 紧，适合作 ICP 初始化或验证。

---

### 2.6 Learned registration / uncertainty：长期方向，不是最先做

Deep Closest Point 明确指出 ICP 及其变体可能收敛到 spurious local optima，并用 learned embedding + attention + differentiable SVD 来替代传统 correspondence。GeoTransformer 则学习几何上下文特征，利用 pairwise distances 和 triplet angles 提高 low-overlap registration 的 correspondence 质量。

参考：

- Deep Closest Point: <https://openaccess.thecvf.com/content_ICCV_2019/papers/Wang_Deep_Closest_Point_Learning_Representations_for_Point_Cloud_Registration_ICCV_2019_paper.pdf>
- Deep Closest Point arXiv: <https://arxiv.org/abs/1905.03304>
- GeoTransformer: <https://arxiv.org/abs/2308.03768>

这些方向有启发，但不建议作为当前第一优先级，因为：

- 当前 failure 已经很具体，未必需要大模型；
- 训练/域适配成本高；
- Matterport indoor local-map 的 2D sparse LiDAR 与这些 3D benchmark 有 gap；
- 当前真正需要的是 yaw 可靠性诊断，而不是整体 registration SOTA。

更适合长期做成论文扩展：学习一个 `yaw_confidence / rotation ambiguity predictor`，输入 anchor/current local maps、ICP basin summaries、localizability features，输出是否信任 dθ。

---

## 3. 建议的解决路线

### 第一优先级：把 promotion 从 3-of-5 改成“单调 Bayesian / SPRT-style gate”

这是最直接对应问题 1 的改法。

当前逻辑：

```text
candidate_promote = quality_ok and (close_enough or trend_ok or current_missing)
promote = 3-of-last-5(candidate_promote)
```

建议改成：

```text
evidence_t = calibrated_logit(
    next_quality/current_quality,
    next_distance,
    distance_trend,
    closure_z,
    odom_progress_fraction,
    alias_score,
    yaw_observability,
)

S_t = clamp_decay(S_{t-1} + evidence_t)

if S_t > upper_threshold(anchor):
    promote
elif dwell_too_long and P_next_high:
    promote_with_stall_relief
else:
    retain
```

其中 threshold 应该 adaptive：

- alias_score 高：提高阈值，防止 overshoot / racing；
- localizability 差：提高阈值或需要更多 temporal consistency；
- odometry progress 已接近 boundary：降低阈值，减少 lag；
- episode 内 long stall：逐步降低阈值，但不能降到 immediate promotion。

这个方案对应文献中的 SPRT / Bayesian filtering / sequence-based place recognition，理论和工程上都比固定 vote window 更合理。

---

### 第二优先级：为 ICP 增加 yaw-specific reliability，而不是继续调 scalar ICP quality

针对问题 2，建议新增几个诊断量：

```text
yaw_score_entropy
yaw_top1_top2_gap
yaw_peak_width_deg
yaw_localizability_score
yaw_vs_odometry_prior_error_deg
yaw_vs_anchor_edge_error_deg
translation_yaw_consistency_score
```

尤其是：

1. **Yaw observability from correspondence Hessian**  
   不是看 anchor PCA，而是看当前 ICP correspondences 的 Jacobian/Hessian。代码已经有 `_localizability_from_correspondences()`，应该扩展为直接输出 yaw DoF 的约束强度。

2. **Yaw likelihood curve**  
   不只看 top basin 与 second basin，而是保存所有 yaw seeds 的 score curve。`ep1040 / anchor4` 的 raw basin count 很多，但 pipeline 的 near-tie margin 没触发；这说明当前 near-tie 定义太窄。

3. **External yaw prior check**  
   如果 dθ 与短时 odometry yaw / anchor edge yaw / reverse route segment yaw 明显冲突，即使 ICP clean，也要降权。

输出层面可以先不 reject dx/dy，只做：

```text
if yaw_unreliable:
    anchor_heading_reliable = False
    bearing source = translation only / odometry-assisted
    do not use dtheta in closure fusion
```

---

### 第三优先级：加一个 cheap yaw verifier

可选三种，从便宜到贵：

#### A. Scan Context yaw verifier

只在 current/next 两个 anchor 上做 column-shift yaw check。成本低，和现有代码路径接近。

#### B. Correlative occupancy verifier

把 anchor/current 2D points rasterize 成 occupancy grid，对 yaw 做 coarse-to-fine correlation。这个最适合 2D LiDAR local map；Cartographer / Olson 路线说明这类方法在 2D scan matching 里非常成熟。

#### C. Offline global registration verifier

用 Open3D global registration / TEASER++ / robust GMM registration 跑离线 ablation，先判断“有没有可能从单帧 geometry 中恢复正确 yaw”。如果连这些都不行，那说明必须换 viewpoint / 多帧。

---

### 第四优先级：多帧不是简单累积点密度，而是“短基线主动 disambiguation”

文件里已经说，单 viewpoint 上提高点密度不解决 rotational self-alias。所以 multi-frame 不能只是把同一个位置附近的点云堆密，而应该利用空间基线：

- 当 yaw_unreliable 触发时，不立即信 dθ；
- 等机器人再走 0.3–0.6 m 后，采第二个 scan；
- 两个 scan 的相对运动由 odometry 给出；
- 共同验证哪个 yaw 能同时解释 frame_t 和 frame_t+k；
- 如果两个 yaw 都能解释，则保持 yaw unreliable，不给 VLM 强 bearing。

这比 blind multiframe anchor accumulation 更稳，因为它只在高风险时触发，并且目标是打破旋转歧义，而不是提高点数。

---

## 4. 可执行实验计划

### Stage 1：离线复盘，不改 live pipeline

用 `--capture_icp_replay_dataset` 支持的 replay 数据做 ablation。`round_trip_eval.py` 里有 capture ICP replay dataset 的开关，会保存 anchors 和 return steps，适合无 Isaac Sim 重放。

先做 4 个离线指标：

1. 对所有 accepted ICP，保存完整 yaw seed score curve；
2. 计算 yaw entropy / top gap / peak width；
3. 计算 correspondence Hessian 的 yaw observability；
4. 计算 ICP yaw 与 odometry / anchor-edge yaw 的冲突。

目标是解释 69% unexplained bucket 中至少 40–50%。如果这几个指标能覆盖 `ep1040 / anchor4`、`ep187 / anchor8`、`ep680 / anchor5` 等 top groups，就说明方向对了。

---

### Stage 2：promotion gate A/B

在 offline replay 上比较：

- baseline：3-of-5 bounded_evidence；
- SPRT-style scalar evidence；
- two-state HMM posterior；
- BOCPD boundary posterior。

评估不要只看 exact rate，还要分开看：

- overshoot rate；
- lag / behind rate；
- promotion latency in attempts；
- episode 5 stall relief；
- false promotion chain length；
- final return success / hint bearing quality。

目标不应该是 current exact 最大，而应该是 hint 对 VLM 有用且不会早停/误导。如果 exact 提升但 bearing 错，return 仍然可能失败。

---

### Stage 3：live 小批量验证

先选 hard-11 中最有代表性的 4 类 episode：

- overshoot spread 型：`ep678 / ep680`；
- lag-stall 型：`ep5`；
- clean-but-wrong bearing 型：`ep1040 / ep187`；
- genuinely poor candidate 型：`ep4 / ep994`。

每个改动至少跑这些 episode，避免只优化某一类。

---

## 5. 最终推荐方案排序

我会按这个顺序做：

1. **先做 yaw diagnostics，不急着改 ICP。**  
   因为问题 2 的最大风险是“系统不知道自己错了”。先让系统知道 yaw unreliable。

2. **把 promotion gate 从 fixed 3-of-5 改成 adaptive SPRT / HMM posterior。**  
   这是问题 1 的正解。固定窗口已经被数据证明不适合所有 episode / anchor。

3. **加 Scan Context 或 correlative yaw verifier。**  
   只作为 verifier，不作为主重定位器，成本更可控。

4. **必要时做 short-baseline disambiguation。**  
   对单帧无法解决的旋转对称场景，用第二个 viewpoint 打破歧义。

5. **长期再考虑 learned registration / learned yaw uncertainty。**  
   DCP、GeoTransformer、Stein ICP、Bingham/von-Mises pose uncertainty 都有启发，但对当前项目来说不是最快的工程路径。

一句话总结：

> **问题 1 用 sequential decision / Bayesian filtering 解决，问题 2 用 yaw-specific uncertainty + verifier 解决；不要再把主要精力放在调全局 vote window、corridor_degeneracy_ratio、point density 或普通 ICP residual 上。**

---

## 6. 参考项目与文章清单

### Promotion timing / sequential decision

- Sequential Probability Ratio Test: <https://en.wikipedia.org/wiki/Sequential_probability_ratio_test>
- Bayesian Online Changepoint Detection: <https://arxiv.org/abs/0710.3742>
- PLISS: <https://www.roboticsproceedings.org/rss06/p24.html>
- SeqSLAM: <https://ieeexplore.ieee.org/document/6224623/>
- PlaceNav: <https://arxiv.org/abs/2309.17260>

### ICP uncertainty / localizability / yaw reliability

- ICP covariance / uncertainty discussion: <https://arxiv.org/pdf/1909.05722>
- Stein ICP: <https://arxiv.org/abs/2106.03287>
- X-ICP: <https://arxiv.org/abs/2211.16335>
- LP-ICP: <https://arxiv.org/abs/2501.02580>

### Correlative scan matching / Scan Context / robust registration

- Olson real-time correlative scan matching: <https://april.eecs.umich.edu/pdfs/olson2009icra.pdf>
- Cartographer algorithm walkthrough: <https://github.com/googlecartographer/cartographer_ros/blob/master/docs/source/algo_walkthrough.rst>
- Scan Context paper: <https://ieeexplore.ieee.org/document/8593953/>
- Scan Context PDF: <https://gisbi-kim.github.io/publications/gkim-2018-iros.pdf>
- Scan Context++: <https://arxiv.org/abs/2109.13494>
- Scan Context GitHub: <https://github.com/gisbi-kim/scancontext_tro>
- TEASER++: <https://arxiv.org/abs/2001.07715>
- Open3D ICP registration: <https://www.open3d.org/docs/release/tutorial/pipelines/icp_registration.html>
- Open3D global registration: <https://www.open3d.org/docs/release/tutorial/pipelines/global_registration.html>

### Learned registration

- Deep Closest Point: <https://openaccess.thecvf.com/content_ICCV_2019/papers/Wang_Deep_Closest_Point_Learning_Representations_for_Point_Cloud_Registration_ICCV_2019_paper.pdf>
- Deep Closest Point arXiv: <https://arxiv.org/abs/1905.03304>
- GeoTransformer: <https://arxiv.org/abs/2308.03768>
