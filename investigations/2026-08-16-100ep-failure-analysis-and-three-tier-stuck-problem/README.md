# 2026-08-16: 100ep失败分析 + 三层anchor架构与"卡死"问题

Date: 2026-08-16
Status: **进行中** — 三层架构的核心问题（卡死候选如何处理）尚未定案，v4实验仍在跑，本文档记录到目前为止的完整证据链。

## 本次会话两条并行线索

1. **[100EP_FAILURE_ANALYSIS_AND_MANIFEST_DIFFICULTY.md](100EP_FAILURE_ANALYSIS_AND_MANIFEST_DIFFICULTY.md)** —
   调查`line2_v11veto_turngate_trendconf_100ep_20260815`批次(34.1% round-trip)为何明显低于历史50ep(55.6%)/30ep(70%)批次，最终定位到是**配置/代码差异**（对照批次带oracle yaw矫正+Route2的Policy V2学习控制器），不是episode本身更难；顺带完成了对Route2历史上"最好成绩"说法的核实、66%代码的完整考古与复现批次的launch。

2. **[THREE_TIER_ARCHITECTURE_AND_STUCK_PROBLEM.md](THREE_TIER_ARCHITECTURE_AND_STUCK_PROBLEM.md)** —
   三层anchor架构（current/next/candidate）设计、offline replay验证方法、"卡死"问题的根因诊断（ICP精度随距离断崖式下滑）、强制晋升(v3)被证伪、真实拉黑修复(v4)进行中、以及一路上发现并修正的两个方法论错误。

## TL;DR

- **100ep批次的34.1%不是因为这100集比历史批次难**——路线长度实测更短；同一批episode在66%那批(Policy V2主动学习控制器+oracle yaw矫正)里能拿到66%，在当前这批(纯heuristic+无yaw矫正+一个已知有害的trend_confidence开关)里只有24%。已经把66%那份代码完整找回（归档目录`navila_archive/staging_dirs/navila-reliability-v1_1-policy-v2-active50-20260725`，验证自包含、未被覆盖），并launch了用这份代码跑当前100ep manifest的复现批次（systemd unit `navila-policyv2-highsuccess100ep-20260816`，进行中）。

- **三层架构的"卡死"问题**（next已就绪但候选既没confirmed也没quarantined）根因是**ICP匹配精度随距离断崖式下滑**（10个独立批次、38万+真实数据验证：0-1m准确率41-68.5%，一过1m直接腰斩到16-41%，2m以后基本归零），而next的晋升触发半径(0.75m)恰好比候选所在的典型距离(1-2m)提前，导致候选在被要求"表态"的那一刻几乎必然处在读不准的区间——这不是候选本身是坏锚点（历史good_fraction并不比confirmed候选差），是判定时机跟ICP可信窗口没对齐。

- **强制晋升(v3)已被数据证伪**：n=50集验证，触发率76.4%，mean/p75/尾部全面劣于baseline和不强制晋升的v2。真实拉黑修复(v4)还在跑，用来回答"v2漏加拉黑到底是好事还是坏事"。

- **两处方法论纠错**（过程记录，供以后避坑）：①offline replay里机器人的物理轨迹是历史录制的固定数据，不会响应我们模拟出的current/next决策，不存在"状态会自我修正/机器人会追上来"这回事；②ep4曾被错误当作"强制晋升后错误持续"的例证，后来发现这一集机器人在真实录制里本身就物理卡墙、提前停止移动，这个例证作废，需要换一集干净的episode重新验证。
