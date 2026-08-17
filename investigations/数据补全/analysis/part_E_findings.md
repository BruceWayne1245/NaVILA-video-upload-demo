# E 部分：文献核实（NaVILA 论文 50.2% 数值）

**方法**：WebSearch 定位论文 + WebFetch 抓取 arXiv HTML 版全文 (`arxiv.org/html/2412.04453v1`)，针对性提取 Table 4 及其周边方法论文字。未能访问本地 PDF（仓库/主目录下未找到本地缓存的论文文件，已搜索 `/mnt/SSD4T/teambruce/projects/navila-isaac/` 与 `/home/teambruce/` 下的 `*.pdf`）。

## 状态：FOUND（数值定位），PARTIAL（度量定义未在本文中显式复述）

**论文**：NaVILA: Legged Robot Vision-Language-Action Model for Navigation, arXiv:2412.04453 (Cheng et al.)
**来源**：https://arxiv.org/abs/2412.04453 ｜ HTML 全文：https://arxiv.org/html/2412.04453v1

### 1. 50.2% 的确切出处

- **表号**：Table 4，caption 原文仅为 "VLN-CE-Isaac evaluation."（未展开更详细说明）
- **对应行**：`NaVILA-Go2-Vision`（即 vision 观测设定，非 GT-depth/特权信息设定）
- **平台**：Unitree **Go2**（非 H1）
- **数据集/划分**：VLN-CE-Isaac，**Val-Unseen** split
- **对应列**：`SR`（Success Rate）列，数值为 **50.2**
- **表格列头完整顺序**：`Low-level Observation | Proprio. | LiDAR | Height Scan | NE↓ | OS↑ | SR↑ | SPL↑`

→ 与用户询问的前提相符：**该 50.2% 确实对应 Go2 + vision 设定**（不是 GT depth、不是 H1 平台）。

### 2. 成功判据（NOT FULLY FOUND — 需标注为推断）

**状态：PARTIAL / NOT FOUND（精确阈值未在本文中显式给出）**

论文正文在此处仅写"For consistency, we evaluate performance using the same metrics as prior work"，引用的是 R2R-CE / VLN-CE 系列先前工作的度量定义，**未在 NaVILA 论文自身文本中重新给出成功半径的具体数值，也未明确复述是否要求 agent 主动发出 STOP**。

**已搜索**：arXiv HTML 全文中 Table 4 caption、其前后方法论段落、Related Work 中对 VLN-CE 度量的描述。均未见显式的米数阈值或"是否需要主动STOP"的复述文字。

**可推断但未经论文原文证实的背景**（标注为推断，不作为确定结论使用）：VLN-CE 系列基准（Krantz et al. 2020 等）的标准惯例是 3.0m 成功半径 + 需要 agent 主动执行 STOP（而非 oracle success）。NaVILA 的 `OS`（Oracle Success）列与 `SR`（Success Rate）列并列出现，这本身就是二者被区分对待的证据——若 SR 是 oracle 式判定，`OS` 列就没有单独存在的意义，因此 `SR` 大概率要求主动 STOP、`OS` 才是"路径上任一点进入目标区即算成功"的版本。但**这仍是基于列结构的合理推断，不是论文文本的直接引用**，请在论文中如实标注为"沿用先前工作惯例，本文未重新给出数值"，不要写成从 NaVILA 论文原文摘录的确定值。

**建议下一步**（若需要坐实这个阈值）：查该论文引用的先前工作原文（通常是 Krantz et al., "Beyond the Nav-Graph: Vision-and-Language Navigation in Continuous Environments", ECCV 2020）中的显式定义，或检查 NaVILA 官方 GitHub 仓库的 eval 代码（如果公开）里的成功半径常量。本次任务范围内未执行这一步。

### 3. 精确出处汇总

| 项目 | 值 | 来源 |
|---|---|---|
| 数值 | 50.2 (SR%) | Table 4, arXiv:2412.04453 |
| 平台 | Go2 | Table 4 行标签 "NaVILA-Go2-Vision" |
| 观测类型 | Vision（含 LiDAR + Height Scan，非纯 proprioception） | 同上 |
| Split | Val-Unseen | Table 4 caption 上下文（VLN-CE-Isaac evaluation） |
| 成功半径数值 | **NOT FOUND**（本文未显式复述，疑似沿用 VLN-CE 惯例 3.0m，未证实） | 已搜索 Table 4 周边正文、Related Work |
| 是否要求主动 STOP | **NOT FOUND**（本文未显式复述；OS/SR 并列列结构暗示 SR 需要主动STOP，但非文本直接证据） | 同上 |
