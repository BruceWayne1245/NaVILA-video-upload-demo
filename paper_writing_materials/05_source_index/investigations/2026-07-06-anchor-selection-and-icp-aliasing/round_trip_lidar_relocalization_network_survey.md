# Round-Trip LiDAR Relocalization：网络调查与解决方案建议

我仔细读完了这 7 个文件，并做了一轮面向论文/开源项目的调查。我的结论比较明确：

**你们现在的问题，不适合继续靠“换一个 ICP objective / 调阈值”解决。更合适的方向是：在 `{current, next}` 约束不变的前提下，加一个“跨位置可分性评分 + 有界多帧证据”的 relocalization/promotion 层。**

也就是说，ICP 仍然可以保留做局部位姿估计，但不能让单帧 ICP 的 `distance_to_anchor_m` 或 `confidence * sqrt(inlier_count)` 直接决定 anchor promotion。

---

## 1. 我对当前问题的理解

现在的系统是 return 阶段的 `sequential_pair` shadow relocalizer：真实导航由 oracle hint 控制，shadow pipeline 只是尝试用 LiDAR local-map ICP 在 outbound 记录的 route anchors 中判断自己在哪，目标是未来替代 oracle。`FINDINGS.md` 里也明确说，当前 return motion 本身不受 shadow 影响，shadow 是独立研究目标。

核心症状不是“卡住不动”的旧 death spiral，而是新的 **lead-lock cascade**：

- 旧的 odometry consistency gate 删除后，永久 reject / permanent-lock 基本消失；
- 但现在 raw `target_anchor_index` 会 **跑到机器人真实位置前面**；
- 多个 anchor 在短窗口内被连续 promotion，真实机器人几乎没怎么移动；
- 出错的 ICP 不是低置信度噪声，而是 **confidently wrong**：错误 anchor 的 point cloud 也能给出高 overlap / 低 residual；
- `point_to_line` 相比 `point_to_point` 还明显加剧了 cascade 和 severe error；
- 你们自己的统计也说明，主因不是 corridor degeneracy，而是 **scene-level perceptual aliasing / self-similarity**：不同位置的局部 LiDAR 结构太像，导致 ICP 在错误位置也能“看起来很对”。

这和我读代码后看到的 promotion 逻辑是吻合的：`next` 只要自报距离小于约 0.75m，或者质量接近/超过 current，就可能 promotion；而 closure check 在 belief 模式下不会硬拒绝，并且对“current 和 next 同时错得自洽”的情况天然无能为力。

所以问题可以概括成一句话：

> **不是 ICP 没收敛，而是当前系统缺少“这个局部结构是否在 route 上具有唯一性”的判断。**

---

## 2. 最推荐的方向：有界多帧 HMM / SeqSLAM-lite，而不是无界 odometry gate

我认为最值得优先做的是一个 **bounded temporal disambiguation layer**，类似 SeqSLAM / HMM，但只用最近 3–5 帧，不重新引入旧的无界累计 odometry consistency gate。

原因是你们的问题本质上是单帧 aliasing。单个 live scan 可以和多个 anchor 都像，但连续几帧的变化趋势通常更难同时伪装。LiDAR place recognition survey 里也把 trajectory / sequence-based methods 单独列为一类，并指出 SeqSLAM 的核心思想就是在时间上整合相似度，而不是只看单帧。

很贴合你们场景的一篇 2024 Sensors 文章用了 **HMM 多帧 descriptor matching** 来解决单帧 place recognition 易受相似环境误匹配的问题。它明确说，单 keyframe descriptor matching 在相似环境中会导致 error matching，而 HMM 把 descriptor similarity 和连续帧的 pose transformation / spatial consistency 结合，实验中比单帧 Scan Context 平均提升 5.8%，最高提升 15.3%。

你们可以做一个极简版：

```text
state_t ∈ {current, next}
emission(state) =
    a * descriptor_similarity(state)
  + b * log(icp_confidence(state) * sqrt(inliers))
  - c * icp_multibasin_ambiguity
  - d * closure_disagreement_penalty

transition:
  current -> current: high
  current -> next: allowed only if evidence persists
  next -> current: allowed if promotion was not committed yet
  jump more than one anchor: forbidden
```

关键是：

- fixed window，例如 `W=4` 或 `W=5`；
- 不保留无限历史；
- ambiguous 时 **hold belief / do not promote**，而不是 hard reject；
- promotion 只在 `P(next) > 0.75 or 0.8` 连续出现 `K=2/3` 次后提交；
- 每次最多推进一个 anchor；
- 已 promotion 后也保留一个短暂 rollback grace window，防止刚 promotion 就发现错了。

这正好避开旧 death spiral：旧问题是无界累计 gate 一旦错了会永远锁死；新方案是 **固定窗口、会遗忘、只影响 promotion，不硬否定所有 relocalization**。

---

## 3. 第二推荐：MapClosures-style BEV density map + self-similarity pruning

这次网络调查里，我觉得最贴近你们“scene-level aliasing”的开源项目是 **PRBonn/MapClosures**。

它不是传统 Scan Context，而是把 local map 做成 **density-preserving BEV projection**，再用 ORB 特征做 place recognition。更关键的是，它论文/README 里明确提到：使用 **self-similarity pruning** 来缓解 repetitive environments 里的 perceptual aliasing。这几乎直接对应你们现在的 “多个几米外 anchor 对同一个 scan 都 overlap 0.5–1.0+” 的问题。

MapClosures 的开源实现也很成熟，有 C++ 和 Python API，并且 `pip install map-closures`，项目说明里说它是 “Effectively Detecting Loop Closures using Point Cloud Density Maps”。

我建议不要直接拿它做完整 loop closure，而是抽其中的思想做一个 **two-anchor verifier**：

对 `{current, next}` 两个 anchor 分别计算：

```text
density_bev_similarity_current
density_bev_similarity_next
descriptor_margin = score_next - score_current
self_similarity_penalty = how non-unique this anchor looks among nearby outbound anchors
```

然后 promotion 不再只看 `next_est.distance_to_anchor_m <= 0.75`，而是要求：

```text
next_icp_close == true
AND descriptor_margin_next_over_current > τ
AND self_similarity_penalty_next is low
AND temporal evidence persists for K frames
```

如果 `next` 和 `current` 都很像，或者 `next` 很像但它在 outbound route 上也和很多别的 anchor 很像，那就进入 **pending/hold**，不 promotion。

这一步不违反 `{current,next}` 约束，因为 live 阶段仍然只比较 current 和 next。全 route 的 self-similarity 可以在 outbound 结束后离线/预计算一次，用于给每个 anchor 一个 “distinctiveness prior”。

---

## 4. 第三推荐：改造 Scan Context，而不是继续只用现在这版

你们已经有 `scan_context.py`，而且已经从 binary occupancy 改回了 max-height-per-cell，并加了 connected agreement region。这是正确方向。但就现在的问题看，当前 Scan Context 还不够，因为它仍然容易受局部 footprint 太小、点太稀、重复结构太像的影响。

Scan Context/Scan Context++ 本身是非常值得保留的 baseline。官方实现说明它是为 sparse/noisy outdoor point cloud 设计的 global descriptor，并且 C++ 版本 20×60 descriptor、10 candidates 可以跑到 10–15Hz。Scan Context++ 进一步强调 rotation 和 lateral variation robustness，并提供 topological retrieval + 1-DOF semi-metric localization。

但你们的 case 和标准 Scan Context 不完全一样：

- 标准 SC 常用于更大范围/更完整 scan；
- 你们是局部 local map，约 500 points；
- route 上相邻/近邻 anchor 的结构可能高度重复；
- live 不做全库检索，只比较 `{current,next}`。

所以我建议做三项小改造：

1. **多尺度 SC**：例如同时算 `(rings,sectors) = (10,36), (20,60), (30,90)`，如果高分只出现在粗尺度但细尺度无差异，则判为 alias-prone。

2. **descriptor uniqueness prior**：outbound 后预计算每个 anchor 与邻近 anchor 的 SC similarity。如果某个 anchor 与前后 3–5 个 anchor 都高度相似，则 promotion 需要更严格 temporal evidence。

3. **margin-first，不是 score-first**：不要问 “next score 是否高”，而是问 “next 是否显著高于 current，以及显著高于它自己的 alias set”。这和你们当前的失败正好相反：当前是 next 只要自己看起来不错就能晋级。

---

## 5. SOLiD 值得试，尤其因为你们是局部/FOV受限 LiDAR

另一个很值得试的 handcrafted descriptor 是 **SOLiD**。它的定位是 “FOV-constrained LiDAR Place Recognition”，开源仓库明确说它面向视场受限、被遮挡、solid-state LiDAR 等不完整观测场景，并提供 Python/C++ 版本。

这和你们的 local map 更像：虽然你们不是 solid-state LiDAR，但你们的问题也是 **局部可见结构不足 + scan 不完整 + anchor 间相似**。

我会把 SOLiD 排在 Scan Context++ / MapClosures 之后，作为一个低成本 descriptor baseline：

```text
candidate_score =
  ICP_quality
  + λ1 * SOLiD_similarity
  + λ2 * SC_similarity
  - λ3 * anchor_self_similarity
```

如果 SOLiD 对 ep4 / ep368 这种 cascade 窗口能把 current 和 next 拉开，那它就很有价值。如果也拉不开，说明局部几何确实需要多帧。

---

## 6. 深度学习类方法：有潜力，但不建议作为第一步

我调查到的深度 LiDAR place recognition 项目很多，包括：

- **OverlapNet**：Siamese 网络，从 LiDAR range image 预测 overlap 和 relative yaw。
- **OverlapTransformer**：更轻量，range-image based，官方称 Python 小于 4ms/C++ 小于 2ms 做 LiDAR similarity，且是 yaw-invariant。
- **SeqOT**：OverlapTransformer 的 sequence-enhanced 版本，使用 sequential LiDAR data 做 spatial-temporal transformer。
- **BEVPlace / BEVPlace++**：把点云投影到 BEV image，再用 rotation-equivariant module + NetVLAD 做 place recognition 和 pose estimation。BEVPlace++ 官方说它先做 place recognition 再做 pose estimation，用于 complete global localization。
- **LoGG3D-Net**：用 sparse point-voxel convolution 和 local consistency loss 学 global descriptor。
- **PointNetVLAD**：经典 point cloud retrieval baseline，但原始设置通常用 4096 点左右的 submap，且是 20m trajectory submap。

这些方法的共同问题是：大多默认更完整、更密的车载 LiDAR scan/range image，而你们现在是局部 local map，downsample 后约 500 点，且 domain 是 VLN-CE/室内模拟。直接套 pretrained model 可能会 domain mismatch。

所以我不建议第一步就上 OverlapTransformer / BEVPlace++ 作为主方案。更现实的做法是：

1. 先用 `capture_icp_replay_dataset` 生成的 offline point clouds 做 pairwise benchmark；
2. 把每个 current scan 和 `{current,next,hard-negative anchors}` 做正负样本；
3. 训练一个 **很小的 BEV Siamese / NetVLAD-lite**，输入就是你们自己的 6m local BEV density/height image；
4. loss 用 hard negative：真实 anchor vs route 上结构相似但位置错的 anchor；
5. 输出只作为 promotion margin，不直接替代 ICP pose。

这会比直接搬 KITTI-trained OverlapTransformer 更稳。

---

## 7. STD / BoW3D / BTC / triangle descriptors：可以做 verifier，但不一定适合你们的 500 点局部图

**STD** 和 **BoW3D** 都很有意思。

STD 用 stable triangle descriptor 做 3D place recognition，三角形边长天然 rigid-transform invariant，并且匹配出来的 correspondences 可以用于 geometric verification。官方 README 也强调它可处理小 FOV LiDAR、反向移动、低 overlap 和大 viewpoint change。

BoW3D 则基于 LinK3D feature 建 bag-of-words，既能 loop detection，也能估计 full 6-DoF relative pose，官方说可用于 real-time relocalization。

但我对它们在你们这里的优先级比较谨慎：

- 你们每帧只有约 500 个 downsampled local-map points；
- 局部 indoor/Matterport 结构里稳定 3D keypoints 可能不足；
- 你们的主要问题不是“大视角低 overlap”，而是“小范围重复结构高 overlap 假匹配”；
- triangle / BoW 如果只看局部几何，也可能被重复走廊/门框骗过。

所以我建议把它们作为 **secondary verifier**：

```text
if ICP says next is close:
    run STD/Bow3D-style geometric verification
    if too few stable keypoints or multiple pose hypotheses tie:
        do not promote
```

不要把它们作为主 relocalizer。

---

## 8. TEASER++ / PointDSC / robust registration：适合验证 correspondences，不适合单独解决 aliasing

TEASER++ 和 PointDSC 这类方法解决的是 “outlier correspondences 下的 robust registration”。TEASER++ 用 truncated least squares、maximum clique 等思想，在大量 outliers 存在时仍可做 certifiable registration。PointDSC 则显式利用 spatial consistency 做 outlier pruning。

它们可以帮助你们避免某些“ICP 对错点收敛”的情况，但不能根治 scene-level aliasing。因为如果两个不同位置的结构本来就几何相似，那么错误 match 也可能具有很强 spatial consistency。

所以它们的正确位置是：

```text
ICP / descriptor 认为 next 可能成立
→ 用 TEASER++ / PointDSC / clique consistency 做 sanity check
→ 如果 spatial consistency 差，拒绝
→ 如果 spatial consistency 好，但 descriptor margin/temporal evidence 不够，仍然 hold
```

也就是说，robust registration 是 **必要但不充分**。

---

## 9. 我给你们的优先级排序

### Tier 1：最应该马上做

**A. 回退到 `point_to_point` 作为默认 ICP objective。**  
你们自己的 A/B 已经说明 `point_to_line` 让 cascade events 从 7 变 18，severe-error rate 从 58.0% 到 75.5%。这已经足够说明它不适合作为当前默认。KISS-ICP 这类近期成功系统也说明，在工程处理正确时 point-to-point ICP 仍然可以非常强，而不是必须追 point-to-plane/line。

**B. promotion 改成 two-stage：`candidate_next` 和 `committed_next` 分开。**  
单次 `next.distance_to_anchor_m <= 0.75` 只能进入 pending，不能直接 promotion。

**C. 加 fixed-window HMM / Viterbi-lite。**  
窗口 3–5 帧，状态只允许 `{current,next}`，最多扩成 `{current,next,next_next}` 用于诊断，但 live 不做全 anchor search。

**D. 加 descriptor margin。**  
先用你们已有 Scan Context，再加一个 MapClosures-style BEV density descriptor。promotion 必须要求 next 相比 current 有显著 margin。

---

### Tier 2：很值得做的增强

**E. outbound 后预计算 anchor distinctiveness。**

每个 anchor 计算：

```text
alias_score_i = max similarity(anchor_i, anchor_j)
for j in local neighborhood or all route anchors, j != i
```

如果 `alias_score_i` 高，说明这个 anchor 本来就不唯一。这样的 anchor promotion 要求更长 temporal evidence。

**F. multi-frame mini-submap。**

每次 return 不只用当前一帧 local map，而是用最近 3 帧合成一个小 submap。注意这是 **bounded**，不是旧的 unbounded odometry accumulator。MapClosures、SeqOT、HMM 多帧论文都支持“多帧比单帧更能打破 aliasing”这个方向。

**G. 尝试 SOLiD。**

它专门面向 FOV-constrained LiDAR place recognition，可能比标准 Scan Context 更适合你们的 local-map 场景。

---

### Tier 3：中长期研究方向

**H. 训练你们自己的 tiny BEV descriptor。**

不要直接拿大模型 pretrained 权重当主力。用 `icp_replay_dataset` 里的真实 failure cases 构造 hard negatives：

```text
positive: current scan ↔ true nearest anchor
hard negative: current scan ↔ wrong anchor with high ICP overlap/residual score
```

目标不是端到端替代 ICP，而是学一个：

```text
is_this_anchor_distinctively_the_right_place?
```

这个任务和你们论文目标更贴合。

**I. TEASER++ / PointDSC / STD / BoW3D 做 verifier。**

用它们减少假几何匹配，但不要指望它们单独解决重复结构 aliasing。

---

## 10. 具体落地方案：我建议按这个顺序改

### Step 0：建立 offline benchmark

利用你们 `round_trip_eval.py` 新加的 `--capture_icp_replay_dataset`，它会 dump anchors 的 raw local-map points + ground-truth pose，以及 return 每步的 raw local-map points + ground-truth pose。`FINDINGS.md` 也说明，这让新 ICP/matching 方法可以在不重跑 Isaac Sim 的情况下 offline 评估。

先做一个脚本：

```text
for each return step:
    for anchor in all anchors:        # offline only
        compute:
          ICP score
          Scan Context score
          BEV density score
          SOLiD score if available
          true distance to anchor from metadata.world_pose
```

指标：

```text
1. correct anchor rank
2. current-vs-next margin
3. severe-error rate > 1m
4. false-promotion trigger rate
5. cascade count
6. silent-gap count
```

重点看 ep4、ep368、ep994。

---

### Step 1：先加一个 MapClosures-style BEV density score

在 `relocalization.py` 或新文件里加：

```text
build_bev_density_image(points_xyz or xy)
compare_bev_density(anchor, current)
```

最简单版甚至可以先不用 ORB：

```text
- grid resolution: 0.10m or 0.15m
- range: same as local map, e.g. 6m
- channels:
  1. occupancy / density
  2. max height
  3. maybe free-space ray evidence if available
- score:
  normalized cross correlation over yaw shifts
```

然后再加 ORB/SIFT 特征。MapClosures 的亮点就是 density-preserving BEV + ORB + self-similarity pruning，所以你们可以先实现轻量版，再决定是否直接接它的 Python API。

---

### Step 2：改 `_select_sequential_pair_relocalization`

现在逻辑大致是：

```text
if next distance close OR trend ok:
    promote
```

建议改成：

```text
if next_est exists:
    next_evidence = combine(
        icp_quality,
        descriptor_margin_next_over_current,
        anchor_distinctiveness_prior,
        temporal_posterior
    )

if next_evidence enters pending:
    pending_next = next_idx

if pending evidence persists for K of last W frames:
    commit promotion
else:
    retain current
```

关键规则：

```text
单帧 next_close 不能 promotion
descriptor tie 不能 promotion
anchor self-similar 不能快速 promotion
candidate_count=2 且两者都高分时，默认 hold 而不是选 next
```

这会直接压制 lead-lock cascade。

---

### Step 3：加 bounded HMM

最小实现：

```python
W = 5
states = [current_idx, next_idx]

emission_current = score(current_est, current_desc_score)
emission_next = score(next_est, next_desc_score)

transition = {
    current -> current: 0.85,
    current -> next: 0.15 if next_close_or_trend else 0.02,
    next -> next: 0.90,
    next -> current: 0.10 during pending only,
}
```

只保存最近 W 帧。每次更新 posterior。只有当：

```text
posterior(next) > 0.8 for 2 or 3 observations
```

才 promotion。

这个不是旧的 odometry gate，因为它：

- 不累计全程误差；
- 不用 `distance_since_sequence_observation_m` 做永久一致性；
- 不会因为一次 bad ICP 永久拒绝；
- ambiguity 时只是延迟 promotion。

---

## 11. 最终推荐组合

我建议你们的下一版叫：

```text
sequential_pair_v2 =
    point_to_point ICP
  + ScanContext/SOLiD/BEV-density descriptor margin
  + anchor self-similarity prior
  + fixed-window HMM promotion
  + optional robust registration verifier
```

其中最关键的是 **descriptor margin + bounded temporal promotion**。

如果只能做一个，我会先做：

> **fixed-window HMM promotion + 禁止单帧 next_close 直接 promotion。**

如果能做两个，再加：

> **MapClosures-style BEV density descriptor + self-similarity pruning。**

这两个组合最直接针对你们的 failure：重复结构导致单帧 ICP 高置信假匹配，而 promotion 太快，quarantine 来不及积累证据。

我的判断是：继续在 `point_to_line` / `ndt_2d` / residual threshold 上调参，最多只能减少一部分 bad read，但不会解决 “错误 anchor 也能高 overlap” 的主因。真正要解决的是 **anchor identity 的可分性和 promotion 的时间证据**。

---

## 参考链接

- LiDAR place recognition survey: https://arxiv.org/html/2306.10561v3
- HMM multi-frame descriptor matching for LiDAR place recognition: https://www.mdpi.com/1424-8220/24/11/3611
- MapClosures paper: https://arxiv.org/html/2501.07399v2
- MapClosures GitHub: https://github.com/PRBonn/MapClosures
- Scan Context GitHub: https://github.com/gisbi-kim/scancontext_tro
- Scan Context++ paper: https://arxiv.org/abs/2109.13494
- SOLiD GitHub: https://github.com/sparolab/solid
- OverlapNet GitHub: https://github.com/PRBonn/OverlapNet
- OverlapTransformer GitHub: https://github.com/haomo-ai/overlaptransformer
- SeqOT GitHub: https://github.com/BIT-MJY/SeqOT
- BEVPlace GitHub: https://github.com/zjuluolun/BEVPlace
- LoGG3D-Net GitHub: https://github.com/csiro-robotics/LoGG3D-Net
- PointNetVLAD GitHub: https://github.com/mikacuy/pointnetvlad
- STD GitHub: https://github.com/hku-mars/STD
- BoW3D GitHub: https://github.com/YungeCui/BoW3D
- TEASER++ paper: https://arxiv.org/abs/2001.07715
- PointDSC GitHub: https://github.com/XuyangBai/PointDSC
- KISS-ICP GitHub: https://github.com/PRBonn/kiss-icp
