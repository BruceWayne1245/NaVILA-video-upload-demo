# 2026-07-24 进度总结

今天做的事情分四块:补上07-23遗留的收尾工作、把V1.1 decision-shadow + RGB-D采集接进线上并跑起来、对"自信的错"做了一轮系统性量化复核、把问题整理成文档发给外部调研。

---

## 1. 07-23遗留代码上传核查

用`git hash-object`逐文件比对本地`navila-reliability-v1_1`沙盒和GitHub tree的blob sha,确认: **07-23那天绝大部分工作(investigations/2026-07-23-v1_1-control-readiness-shadow-handoff、.../v1_1-evidence-synthesis-and-active-control-plan)已经通过一个中转仓库成功推送**,commit `565ff68a37`和GitHub私有仓库main分支HEAD完全一致。

但确认仍有 **7个文件只存在本地,没有上传**(全部只在`/home/teambruce/navila-reliability-v1_1`):
- `reliability/v11_portable.py`(portable runtime的源码模板)
- `tools/export_v11_portable.py`
- `tools/freeze_v11_prospective_results.py`
- `tools/replay_measurement_through_v11_shadow.py`
- `tools/validate_v11_portable_parity.py`
- `experiments/2026-07-22-prospective-shadow/chain_after_current.sh`
- `experiments/2026-07-22-prospective-shadow/run_batch.sh`

**这7个文件目前仍未上传,是产出这些已发布结果的工具脚本本身(导出器/冻结/回放/一致性校验),不影响已发布内容的完整性,但影响可复现性。** 待处理。

---

## 2. 把codex的V1.1 decision-shadow框架 + RGB-D采集merge进live代码并跑起来

07-23写好但没来得及merge的candidate代码(`/home/teambruce/navila-gating-ab-v1/candidate/round_trip_eval.py`)今天完整merge进了live的`NaVILA-Bench/scripts/round_trip_eval.py`,涉及8处改动:
- V1.1相关5个新CLI参数
- 硬化写入的原子化辅助函数(`atomic_json_dump`/`atomic_jsonl_dump`/`sha256_file`)
- `v11_posthoc_ground_truth_by_anchor`(仅用于事后日志,不参与决策)
- V1.1 shadow session初始化(加载frozen portable model + decision policy)
- relocalizer包装成`_sequential_pair_relocalizer_with_v11_shadow`,给V1.1喂原始候选做打分
- return阶段的controller快照记录
- episode结束时的shadow summary写入 + `capture_completion.json`完整性清单

**验证**:语法检查通过;V1.1新增flag全部默认关闭,确认no-model行为不变;codex的frozen preflight(哈希锁定runtime/artifact/policy/gates/scorer)全部PASS;**实际线上运行时确认V1.1 shadow成功初始化**(`features=249 decision_shadow=True enforcement=False`),VLM正常输出导航动作——不是只过了静态检查,是真的跑通了。

**发现并修复一个bug**:第一次启动时`COMMON_EXTRA`和`V11_DECISION_SHADOW_ARGS`拼接漏了空格,导致`--stuck_recovery--reliability_v11_online_shadow`被argparse当成一个无法识别的参数,第一集30秒内报错退出。及时停掉、清空了这次的假失败日志(否则resume逻辑会把它当成"已完成"跳过)、补上空格后重新launch。

**当前运行状态**(写这份总结时):
- run_tag: `reliability_v11_decision_shadow_rgbd_100ep_20260724`
- 复用07-21/07-22完全相同的100集frozen cohort(episode_manifest_sha256一致),保证可比性
- 用`systemd-run --user`挂在`user@1006.service`下持久运行(cgroup已确认正确),不会因断开连接被杀
- 已完成 **11/100**,全部exit_code=0(健康),约8分钟/集,预计还需 **~12小时**
- 日志:`NaVILA-Bench/batch_logs/reliability_v11_decision_shadow_rgbd_100ep_20260724/`

跑完之后按`CONTROL_READINESS_PROTOCOL.md`定死的post-run顺序做(哈希审计→对齐manifest→校验shadow JSONL→离线重建→跑`score_v11_control_readiness.py`→机械化过闸门,不允许看到结果后回头松闸门)。这批数据同时也是"是否要点上视觉修复"那条投资调查需要的100集新鲜RGB-D数据。

---

## 3. "自信的错"系统性复核(200ep里的30个失败案例)

对07-21 fix-ON批和07-22 v11 shadow批**两批100ep**里所有outbound成功但return失败的案例,做了逐帧真值核对(不再是抓单个崩溃帧快照)。方法、完整数据表、和已经测试过/排除掉的方向详见另一份文档(下方链接)。

核心结论:
- 两批合计outbound成功62集,真值口径下return失败 **30集**(fixon批7 + v11批23)
- 其中 **29/30(96.7%)命中"自信的错"**——比昨天口头估的~70%高不少,因为这次是逐帧核对而不是抓单帧快照;有几个昨天归类为"物理楔死"/"步数预算"/"estimate冻结bug"的案例细查后发现也命中了(多个问题在同一集里共存)
- 唯一的真正例外是ep646(锚点8那段2262次自信读数只有6%错,和昨天"ICP好,导航错"的判断吻合)
- **首次做了Type A/B细分**:Type A(一落到这个锚点就错,24集,83%)vs Type B(先有一段正确读数,中途忽然翻成自信的错,5集,17%)——举了一个逐帧验证过的例子(ep814,连续100步正常匹配后一步之内bearing误差从4°跳到79°,距离误差几乎不变,纯旋转翻转)

之后又测了你提的"outbound锚点朝向"这个先验思路,结果是负面的但发现了更关键的东西:
- 朴素的"锚点outbound朝向+180°掉头"先验去重排ICP候选,命中率20.2%,**比随机瞎选(27.3%)还差**——这个简单假设不成立
- 但顺带发现:**95.2%的"ICP选错"案例里,正确答案压根不在ICP自己存的top-4候选里**(ICP内部做的是24-seed扫描,只往下游存分数最高的4个)——这意味着任何"对已有候选重新打分"的方案(不管用朝向先验还是视觉)天花板都在~5%,除非能把候选生成本身的搜索范围扩大
- 确认了这个项目的LiDAR仿真完全没有intensity/reflectance通道,排除了"同样是LiDAR但换个读数"这条路

---

## 4. 输出给外部调研的问题文档

已整理成一份详细的英文技术简报,推到了另一个investigation文件夹:

**`investigations/2026-07-24-confidently-wrong-open-problem-summary/RESEARCH_BRIEF.md`**
https://github.com/BruceWayne1245/NaVILA-video-upload-demo/blob/main/investigations/2026-07-24-confidently-wrong-open-problem-summary/RESEARCH_BRIEF.md

包含完整背景、量化证据(含30集数据表)、已排除方向、这次的候选生成瓶颈新发现,以及给外部调研的具体问题清单(对称环境感知混淆文献、全局点云配准方法、扩大ICP候选搜索的低成本方法、视觉place recognition技术、有界短程dead-reckoning融合、纯时序自洽性完整性监测)。

---

## 待办

1. 补传07-23遗留的7个工具脚本文件(第1节)
2. 监控100ep跑批进度(~12小时后完成),跑完后按protocol跑post-run分析
3. 等外部调研结果,看有没有新方向
4. 如果调研没有更好的思路,原计划的视觉PoC(ep814/688/93/581离线验证LoFTR选basin)仍然是当前最具体可执行的下一步——但要先解决"候选生成范围太窄"这个新发现的问题,否则视觉重排也会撞到同样5%的天花板
