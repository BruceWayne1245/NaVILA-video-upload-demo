# 2026-07-23 — 自信错(confidently-wrong)收敛诊断 + 视觉根治路线

本文件沉淀 2026-07-22/23 两个 100ep 批次(昨天 fix-ON `reliability_fixon_100ep_20260721`
= 63% 基线;今天 v11 shadow `reliability_v11_prospective_capture_shadow_100ep_20260722`)
的真值级失败机制诊断。核心结论:**回程失败的压倒性主因收敛到一个物理问题——ICP 在旋转
对称的环境里自信地锁到错误的旋转解(confidently-wrong),它绕开所有 scalar 监督信号,以
多种表现形式击穿整个系统。几何内部无解,唯一根治手段是视觉。** 全部结论基于从 trajectory
真值坐标、`icp_replay_dataset` 点云 live 重放、以及第一视角 RGB 的直接核对,不用系统自报数。

---

## 0. TL;DR

1. **真值回程率**:昨天 fix-ON = 12/19 ≈ **63%**(新改动前基线,见 `2026-07-22-best-result-63pct`);
   今天 v11(A+B+C+trend_budget+stuck_recovery)截至快照 ≈ 10/23 ≈ 43%(+near-miss 57%)。
   **两批 episode 集完全不同、非配对、样本小,差异不能做因果归因**;逐集根因显示今天失败全是
   老问题,昨天两个新改动 do-no-harm(成功集零触发)。
2. **今天 13 个失败/near-miss 的机制分类:自信错变体 9 个(~70%),其余 4 个是独立的次要问题。**
3. **自信错有三种表现形式,根都是"ICP 旋转 basin 选错":**
   - **全链旋转锁错**(814,688,18,490):机器人朝向对整条 anchor 链一致锁错。
   - **骗停**(93,581,427):promote 被整条链的错误 close 匹配骗着雪崩超前 → forced-stop 误触发。
   - **bearing 锁反**(264,205):next 的 hint 方位锁到反方向。
4. **判别实验证明:不是点云坏、也不是 anchor 坏** —— 真值位姿下机器人点云与 anchor 点云
   overlap 88%/87%、中位距 1cm,**信息完整**,纯粹是 ICP 在几何对称下选错旋转 basin。
5. **几何内部一切信号都被同一个对称一起骗过**(scalar AUC 0.84 天花板、多视角 0.737、多帧、
   多 anchor 静态一致性)。**要打破对称必须引入正交信息:视觉外观,或运动积分。里程已否决 → 视觉是唯一出路。**
6. **RGB 可分性已用现有 video 肉眼验证(路 B):崩溃点是几何对称的多门掉头区,但 RGB 上门通向
   的不同房间、镜子、植物、墙面材质极其不对称,压倒性可分。视觉数据运行时完全可得(双 RGBD 相机)。**
7. **修复:视觉旋转验证(根治,接 promote/forced-stop 两个不可逆决策点)+ 动态异常止损(廉价,
   不用视觉/里程)。** 顺手修 ep1062 的 estimate 冻结 bug。

---

## 1. 两个 100ep 的真值结果

真值口径:每集 return 结束时机器人真实世界坐标到真实起点(step0)的距离 <3.0m(`success_radius`)
记成功。**不用** `summary.tsv`/measurement 的 `distance_to_start` 字段(大量未落盘写成 0.0、
末帧被下一集 reset 帧污染)。崩溃/confirm 阶段就终止的排除。

| 批次 | 新改动 | outbound 率 | 真值 return |
|---|---|---|---|
| 昨天 fix-ON(73集) | OFF | 19/66=29% | **12/19 = 63%**(+near 68%) |
| 今天 v11(进行中) | ON | ≈44% | 10/23≈43%(+near 57%) |

昨天 6 个 FAIL(5,134,187,491,669,678)也全是老问题(楔死/自信错/VLM 转圈/tracking 偏),
与新改动无关。详见 `investigations/2026-07-22-best-result-63pct/`。

---

## 2. 今天 13 个失败/near-miss 的完整机制分类

| 大类 | 集数 | episodes | 性质 |
|---|---|---|---|
| **自信错·全链旋转锁错** | 4 | 814, 688, 18, 490 | 物理(几何对称),需视觉 |
| **自信错·骗停(promote 雪崩超前)** | 3 | 93, 581, 427 | 物理(同源),需视觉 |
| **自信错·bearing 锁反** | 2 | 264, 205 | 物理(同源),需视觉 |
| 物理楔死(cmd 前进 speed≈0) | 1–2 | 764,(18) | 控制/导航层 |
| 导航走错方向(ICP 好) | 1 | 646 | 导航/VLM 层 |
| **estimate 冻结 bug**(可修) | 1 | 1062 | 实现 bug(report_next staleness) |
| return 步数/停早(ICP 好) | 1 | 784 | 步数预算 |

**自信错变体合计 9/13 ≈ 70%。** 这是唯一的物理天花板;其余都是可修 bug 或工程问题,不是物理不可解。

---

## 3. 自信错的三种变体 — 深度机制

### 3.1 全链旋转锁错 —— 判别:不是点云坏,不是 anchor 坏,是几何对称让 ICP 选错 basin

崩溃帧对整条下游 anchor 链跑 live ICP(ep814,current=5):

```
anchor 5(cur): ambiguous, bErr 139-179°   |  4: bErr 114-135°  3: 119-133°  2: 121-126°  1: 116-127°
```

整条链一致锁到偏 ~120° 的错误旋转,且所有 anchor 的 reported bearing 都聚在 -20~-50°
(真值散布 75-140°)。ep688 同样,整条链 bErr 147-178°(近乎反向 180°),且大多自报 `clean_full_pose`。

**判别实验(真值位姿下点云 overlap):**
- ep814 current anchor:真值位姿 overlap **88%**、中位距 **0.01m**,但 ICP bErr 141°。
- ep688 current anchor:真值 overlap **87%**、0.01m,ICP bErr 166°。

→ **点云信息完整、能匹配,ICP 的 24-yaw-seed 搜索却收敛到错误的旋转 basin。** 机器人点云 PCA
轴比仅 1.3-1.6(非简单直走廊单轴),对称性来源更微妙(掉头点的近似对称布局)。错误一旦发生在
**机器人自身朝向**,它对整条 anchor 链都用同一片朝向已错的点云去匹配 → 全链 bErr 一致偏移。
换 anchor/skip 无用 —— 错在机器人朝向,对所有 anchor 一致。

### 3.2 骗停 —— promote 被错误 close 匹配骗着雪崩超前

`stop_gate` 的 believed distance 来自 `route_agent.progress()._anchor_progress_from_estimate`:
```python
estimate = self._latest_next_candidate_relocalization   # report_next 优先用 next
distance_to_start = estimate.distance_to_anchor_m + anchor.route_remaining_to_start_m
```
即 believed **完全由 next estimate 指向哪个 anchor 决定**,stop_gate 没有独立机制。

ep93 believed(stop_gate) vs 真值时序:
```
step 2801: believed 19.7 真值 14.6 (+5, 先滞后)
step 3276: believed  7.8 真值 11.6 (开始超前)
step 3501: believed  3.0 真值  9.9
step 3651: believed  2.6 真值  8.7 → forced stop
```
believed 在掉头区从 7.8 砸到 2.6(下降速率是真值两倍多)= **tracking identity 雪崩式 promote 超前**。
停止帧对全 anchor 跑 ICP:机器人真在 anchor 10/11(对 anchor 10 是 bErr 0°/clean/conf 1.0 的真匹配),
**但点云同时对整条近家 anchor 链(2,3,4)也自信错误匹配 estDist-close + clean**(anchor 2:
route_rem 2m,estDist 1.3m,clean,真值却离 7.2m,bErr 154°)。

根因链:掉头区机器人点云对整条链(含近家 anchor)都 confidently-wrong 匹配 estDist-close →
`bounded_evidence` 的 close_enough(estDist)和 quality(clean)**两个判据都被骗** → promote 雪崩
超前到 anchor 2 → believed 崩到 2.6 → `anchor_corroboration` 的两个"证据"(anchor route_remaining +
ICP reading)其实**同源于同一个错误 identity,自我印证** → forced stop 在真值 8.7m。
**骗停的根因在 promote 层,不在 stop_gate。**

### 3.3 deferred 三集 —— 只有 1 个是自信错

- **ep264 = 自信错**:next hint bearing 锁到 151-179°(指后方,真值前方),hintErr 126-172°;机器人被
  误导、缓慢接近但没走够,deferred 在 5.85m。
- **ep1062 = estimate 冻结 bug(非自信错,可修)**:believed 死卡 4.0、hint bearing 死卡 11° 完全不更新
  (`_latest_next_candidate_relocalization` 停止刷新,`suppress_if_stale` 没覆盖到 progress 层),机器人
  靠 VLM 自己摸到 3.5m near-miss。
- **ep784 = 步数/停早(非自信错)**:ICP/hint 全程正常,机器人正常接近到 4.28m,但 return 只 377 步就结束。

---

## 4. 收敛结论:自信错是唯一的主要对手

**"回程失败的对手 = 一个压倒性主导的物理难题(自信错,~70%,需视觉)+ 3-4 个独立的次要工程问题。"**
次要问题中 ep1062 是明确可修 bug,764 楔死 / 646 走错是导航层,784 是步数——**都不是物理天花板**。
所以主攻自信错(视觉)是对的,同时可顺手清掉 1062 冻结 bug 这种低垂果实。

关键逻辑(为什么几何内部无解):
```
自信错 = 环境几何旋转对称 → 正确解与错误解在点云几何上近乎等价(inlier/overlap/residual 一样好)
   → scalar / near_tie / 多视角散布 / 多帧子图 / 多 anchor 静态一致性 全在几何内部, 被同一对称一起骗
   → 必须引入与几何正交的信息: 视觉外观, 或运动积分
   → 里程/dead-reckoning 已否决(累积漂移不可信)
   → 视觉是根治的唯一出路
```

---

## 5. RGB 可分性证据(路 B 肉眼预览,已通过)

`icp_replay` capture 没存 RGB(只写点云+位姿),但 **RGB 运行时完全可得**:前视 `rgbd_camera` +
后视 `rear_rgbd_camera`,`descriptor["rgb"]`/`["rear_rgb"]` 运行时都填了;`videos/output_*.mp4`
右半就是第一视角 RGB(512×512,10fps);项目已有 LoFTR backend。补 RGB capture 只需在
`capture_icp_replay_step`/`_anchors` 各加一行写 `descriptor["rgb"]`。

ep814 崩溃区三帧第一视角 RGB(见附图 `ep814_rgb_compare.png`):
- 崩溃点是**几何对称的多门掉头区**(LiDAR 上几个方向门框/墙相似 → ICP 锁错 ~120°)。
- 但 RGB 上每个朝向外观**完全不同**:一门通向有人影/画的房间、一个方向是蓝色反光镜面浴室、
  一个是植物+楼梯,墙面还在瓷砖/石纹间变。**这些(镜子蓝反光、植物、画、材质)全是 LiDAR 看不到、
  唯一能定向的信息。旋转 120° 看到彻底不同的画面,视觉不可能混淆。**

→ **结论:不是勉强可分,是压倒性可分。** LiDAR 丢掉的恰好是定向所需的外观信息,RGB 完整保留。

---

## 6. 修复方案

### 6.1 根治:视觉旋转验证(主攻)
- ICP 的 24-seed sweep 保留 **top-K 候选 basin**(而非只取最高分),对这 K 个用**当前帧 RGB vs
  该 anchor 建立时的 RGB** 做 LoFTR 匹配估相对旋转,**选与视觉一致的 basin,否决与视觉矛盾的**。
- 成本控制:LoFTR 贵,**只在 promote next→current 和 forced-stop 这两个不可逆决策点触发**,不是每帧。
- 一举修三种表现:选对朝向 basin(全链)、promote 前否决错误 identity(骗停)、选对方向(bearing 锁反)。

### 6.2 立即止损:动态异常检测 + 保守化(不用视觉/里程)
静态对称不可分,但**突变/雪崩在时间序列上可见**:bearing 单步突变 >90°、identity 单位 attempt
前进速率异常、believed 下降速率远超正常步频 → 判"疑似锁错" → **不 forced stop、不 promote、hint
降权**(退回保守/deferred)。不选对解,只**阻止自信错触发不可逆动作**,堵住骗停/雪崩超前/被反向
hint 带偏这几条击穿路径。代价是偶尔拖慢正常推进(保守方向,不制造新错误)。

### 6.3 明确不要做(基于实证,省得走弯路)
- ❌ 继续加 scalar 可靠性特征 / 提 HGB 容量 —— AUC 0.84 是对称本身天花板。
- ❌ 多视角散布 / 多帧运动子图 / 多 anchor 静态一致性 —— 全在几何内部,被同一对称骗。
- ❌ 任何形式里程/dead-reckoning 位置积分 —— 已否决,累积漂移引入新失败。

---

## 7. 待办与下一步

1. **路 A(视觉定量 PoC)**:补 RGB capture(改几行,存 PNG),重跑 ep814/688/93/581;离线验证
   "top-K basin + LoFTR 选 basin"能否把这几个崩溃帧的 bErr 从 100-180° 降到 <30°。通过则视觉根治
   正式排开发。
2. **动态异常止损**:纯控制层,几周内可验证,先把自信错对 forced-stop/promote 的击穿堵住(可直接
   救回骗停类 93/581/427、缓解全链类)。
3. **修 ep1062 estimate 冻结 bug**:`suppress_if_stale` 覆盖到 progress/believed 层(低垂果实)。
4. 视觉验证一旦证明能选对 basin,它就是这 70% 自信错的根治,整体成功率上限随之打开。
