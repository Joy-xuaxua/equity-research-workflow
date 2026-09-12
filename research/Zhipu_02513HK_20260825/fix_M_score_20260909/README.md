# fix_M_score_20260909｜Beneish M-Score 缺口修复轮

**标的**：智谱 / Z.AI Co., Ltd.（02513.HK）｜**基准 run**：0825（`research/Zhipu_02513HK_20260825`）
**执行日**：2026-09-09｜**范围**：补采 → 重算 → 重跑质检 → 重写 ch05 §5.2；其余不动
**产物目录**：本目录（仓库现有文件零改动——`git status` 验证；`quality/grade.json` 未改）

## 一句话结论

M-Score 缺口已闭合：**M＝−3.14（阈值 −1.78，未越限，P3 INFO）**，`FORENSIC_MSCORE_SKIPPED` 消除，无新增 P0/P1，两项既有 P2 逐字复现；但「未越限」系双亏结构下 TATA 主导的模型局限（TATA 系数 4.679×−0.509 单项贡献 −2.38，剔除该项 M＝−0.76 呈越限形态），不构成收入质量的正面证明；**财报可信度等级 C 不变、veto_action「观望」不变**（C 由 DSO 背离＋经常性 SBC 两项实质触发支撑，M-Score 自始至终不是触发项）。

## 修复链（六步）

| 步骤 | 产物 | 说明 |
|---|---|---|
| 1 补采 | `collection-m-score.md`（＋证据存档 `annual-report-2025.pdf`，19MB，未 commit） | curl 直下 2025 年报 PDF（Tier 1）成功，未走降级链；pypdf 文本层提取；7 个数字全部带页码＋URL＋时间戳＋原文附录逐字引用 |
| 2 修复版 CSV | `financials-fixed.csv` | ＝原 `forensic/financials.csv` ＋仅 7 格（python 逐格 diff 验证＝7，其余逐字） |
| 3 重算 | `checker-financials-fixed.txt`＋`m-score-computation.md` | 检查器：P3 SKIPPED→INFO；八分量全精度复算与脚本九项全吻合；旧 5 分量逐位回归一致；DEPI 备选口径敏感性（差 0.0001，判定不变） |
| 4 重跑质检 | `quality-m-score-revised.md` | `equity-forensic-accountant` agent（maker–checker 分离）：第 2 项按新数据重做，第 1/3/5 项逐字沿用＋输入未受影响确认，第 4 项 capex 检验可算化，§6 等级影响评估＝C 不变 |
| 5 新 §5.2 | `ch05-5.2-revised.md` | `### 5.2` 全节替换文本（L84-167 同结构）；行级验证：修订版独有行恰 11 行、全落计划触点，其余与原文逐字一致 |
| 6 本说明 | `README.md` | 变更清单＋来源页码表＋差异摘要＋等级影响 |

## 7 个新数字及来源（均 Tier 1：2025 年报，人民币千元）

URL：https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0419/2026041900086_c.pdf（呈交日 2026-04-19；本地存档 sha256 bad87a6c…ed6ca3；抓取 2026-09-09 18:30）

| CSV 列×行 | 数值 | 年报位置（PDF 页/印刷页） | 原文附录 |
|---|---|---|---|
| ppe × FY2025 | 655,825 | 綜合財務狀況表 79/78 | A-1 |
| ppe × FY2024 | 866,363 | 同上 | A-1 |
| current_assets × FY2025 | 3,571,411 | 同上（流動資產合計） | A-1 |
| current_assets × FY2024 | 3,015,867 | 同上 | A-1 |
| depreciation × FY2025 | 270,068 | 綜合現金流量表「物業及設備折舊」83/82 | A-3 |
| depreciation × FY2024 | 270,252 | 同上 | A-3 |
| sga × FY2024 | 521,078（＝387,475＋133,603） | 綜合損益表「銷售及營銷開支」＋「一般及行政開支」77/76 | A-2 |

**口径**：ppe/depreciation 同为「物業及設備」行口径（该行含使用权资产——附注 11(a) 第三列勾稽闭合）；sga＝销售及营销＋一般及行政两行加总（FY2025 加总 896,226 与 CSV 既有值逐位复现，口径回归通过）。
**勾稽**：11/11 精确闭合（含 0901 Tier 1 锚 ppe 655,825、current_assets 3,571,411 完全一致；总资产/总负债/现金流量表 CFO 加总全对），明细见 collection-m-score.md §C。

## 新旧 §5.2 差异摘要（触点 7 处，其余逐字沿用）

| # | 位置（原 ch05 行号） | 旧 | 新 |
|---|---|---|---|
| 1 | L84 节首 | — | 新增〔修复轮 2026-09-09〕说明块（变更范围、M 结果、等级不变、L86 例外声明继续有效） |
| 2 | L86 引文声明 | 逐字引自 quality（例外 1 项：G3 PS 双口径） | 例外扩为 3 项（＋修复轮第 2 项/第 4 项一行/等级表 C 行；＋「我的判断」末句） |
| 3 | L99-106 M-Score 块 | `FORENSIC_MSCORE_SKIPPED`；五分量展示（AQI/DEPI/SGAI 缺）；小结「八变量中五缺三，模型不可判定」 | `FORENSIC_MSCORE_INFO` M＝−3.14；八分量全模型；小结三重限制（TATA 主导模型局限／与 DSO·KAM 同向不可否证／单窗口口径边界）＋旧分量回归注 |
| 4 | L127 capex 检验行 | 「depreciation 列全空｜不可算/未获取到」（C02 双值注） | 「不触发（现金口径 4.3%／MD&A 13.8%／FY2024 24.6%）｜可算化：无 capex 藏费迹象（正面）」（C02 双值注保留） |
| 5 | L133 §4 小结 | …两项无法验证（D&A 明细…） | 同句＋〔修复轮注：D&A 明细范围收窄（FY2024/25 已入档，仍缺 FY2022–23 与残差分解）〕 |
| 6 | L156 等级表 C 行 | 辅证：**M-Score 不可算**＋财年深度 4<5＋残差… | 辅证：**M-Score＝−3.14 未越限但受双亏结构局限**（TATA 贡献 −2.38、剔除后 −0.76 越限形态、DSRI>1 与 DSO 同向）＋财年深度 4<5＋残差… |
| 7 | L165 我的判断末句＋L167 data-gaps | 「与 M-Score 不可算的缺口结构」；data-gaps 含「M-Score 全模型不可算」项 | 「M-Score 可算化后的证据结构（未越限系模型局限而非清白证明，总分与分量分层引用）」；data-gaps 移除该项（另收窄 FY2024 SGA 与 FY2024/25 折旧摊销两项的范围注） |

## 等级影响结论

**C 不变（veto_action「观望」不变）**——checker 独立判据核对（非迁就预期）：①C 由 DSO 背离＋经常性「非经常」SBC 两项实质触发支撑（判据「任一」），该两项输入经逐项「输入未受影响」确认零接触；②「M-Score 越限」判据 0825 时不可算（不满足）、现在可算且未越限（仍不满足）——自始至终不是 C 的触发项，仅辅证层措辞更新；③M-Score INFO 不构成 §3 红旗的「合理解释」（B 级判据依旧不满足）；④检查器无新增 P0/P1（D 级判据依旧不满足）。`quality/grade.json` 按约束未改动。

## 验证清单（计划 §验证 5 项）

1. ✅ checker 输出：`FORENSIC_MSCORE_SKIPPED` 消除→`FORENSIC_MSCORE_INFO`；P0=0 P1=0（M＝−3.14≤−1.78，非越限故无 P1）；两项既有 P2 逐字复现
2. ✅ 全部新数字可复算：m-score-computation.md 输入全部指向 collection-m-score.md 原文附录 A-1/A-2/A-3
3. ✅ FY2025 ppe/current_assets 与 0901 Tier 1 锚一致（655,825 / 3,571,411）
4. ✅ 旧可算分量（DSRI 1.4350/GMI 1.3747/SGI 2.3185/TATA −0.5093/LVGI 1.4029）与 quality §7 L131 逐位一致
5. ✅ `git status`：仓库现有文件零改动；新增仅本目录文件；PDF 未 commit（`quality-m-score-revised.md` 已由 W3 agent 按全局增量提交规范单独 commit 0a2d7c7——如需回退该 commit 请示下）

## 后续处置建议（供编排者/用户决策）

1. 是否将本目录其余文件（collection/CSV/checker/computation/ch05-revised/README，除 PDF）commit 入库
2. 是否将 `ch05-5.2-revised.md` 替换进 `chapters/ch05-financials.md` 并触发下游（draft/final 重排）——本轮按约束未动现有文件
3. 开放缺口维持：招股章程 FY2021 序列（财年深度 4<5）、FY2023 应收（DSO 持续性）、附注 32 逐项、应收账龄表——2026-08-31 中报再校验点安排不变（注：0901 run 已实采 2026H1 中报，属另一 run 的事）
