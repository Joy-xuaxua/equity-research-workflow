# 估值 Agent 输入契约核查（2026-08-23）

- **核查对象**：`.claude/agents/equity-valuation-analyst.md` 的 [PARAMS] 输入契约与输入数据清单
- **核查方法**：把估值 agent 的产出要求逐项反推出所需原料 → 对照其声明的输入清单 → 用真实运行 `research/智谱_02513.HK_20260818` 验证症状
- **对照文件**：`equity-data-collector.md`、`equity-data-reconciler.md`、`equity-forensic-accountant.md`、`skill references/`（cost-of-capital.md、data-sources.md、valuation-methods.md、base-rates.md、expectations-investing.md）、`equity-research-orchestration/SKILL.md`、`valuation/valuation-notes.md`（v2）
- **结论**：3 个实锤缺口（均有运行证据）+ 3 个低成本改进项

---

## A. 实锤缺口（智谱运行中有直接症状）

### 1. WACC 市场输入在整条流水线里无人负责 ⚠️ 最严重

`cost-of-capital.md:7-10` 要求：无风险利率**当日 10Y 国债收益率、标时间戳**、ERP 用 **Damodaran 当月隐含值**、beta 用行业无杠杆值。但：

- 02 采集线范围是"价格/市值/倍数/52周"等（`equity-data-collector.md:31`），`data-sources.md` 全文搜不到无风险/ERP/beta——**没有任何采集线负责这三个数**；
- 估值 agent 工具只有 Read/Write/Glob/Grep/Bash，**故意无网**，自己取不了。

真实后果（`valuation/valuation-notes.md:24-27`）：

> 无风险利率 3.6%——"当日中债/HKD 10Y **未获取到**（区间假设）"；ERP 5.3%——"**未联网核对当月值**"；fx 用的还是 2026-03-06 的旧快照。

WACC 是全文同源的单一参数，它的三个输入却在靠模型记忆估值。

**修复建议**：给 02 线增加"WACC 市场输入"采集项（估值币种 10Y 收益率、Damodaran 当月 ERP/国别溢价、行业无杠杆 beta、当前汇率），并在 ledger 基准节契约里加对应行——这才符合"采集线拥有网络、下游只读文件"的架构。

### 2. `financials.csv` 缺净债务/投入资本字段 → 手工拼数被红队抓错

CSV 列清单（实测 `forensic/financials.csv` 表头）：`period, revenue, gross_profit, operating_income, net_income, cfo, capex, fcf, shares, eps, total_assets, receivables, ppe, current_assets, depreciation, sga, total_liabilities, deferred_revenue`——**没有 cash、有息负债、税前利润、少数股东权益、商誉**。

但估值 agent 的 `assumptions.json` 顶层就要 `net_debt`，EVA 要 `invested_capital`，EPV 第一层和"调整后净资产"要资产负债表分项。真实后果：智谱 run 里净现金靠**手算拼分项**（`valuation-notes.md:71`：`3,131+4,806−1,400+31,375−300=37,612−借款529`），v1 拼错（漏 2025 新增借款 4.67 亿），**被红队 F2 当场抓获**。

**修复建议**：W2 的 CSV schema 加列 `cash, interest_bearing_debt, pre_tax_income`（可选 `minority_equity, goodwill`）——对账员手里有原始采集件，填这些列成本很低。

### 3. 可比公司只采了"倍数快照"，没采分母

02 线采到 MiniMax 等可比的**价格/市值/PE/PB 快照**，但没采**可比的收入/ARR/增速**。后果（`valuation-notes.md:84` data-gaps 原文）："**可比公司收入/ARR 未采集**"——对亏损无倍数可用的标的，EV/S、EV/ARR 全部缺分母，相对估值只能给宽度惊人的区间（121–339），交叉验证力度大打折扣。

**修复建议**：02 线"可比公司估值锚"条目明确要求补 peer 收入/ARR（至少够支撑行业附录指定主倍数的分母）。

## B. 契约级小缺口（一致性问题，改动一行就好）

4. **必读清单漏了 `output-format.md` §4**——动作 3 明确要求 football field"画法按 output-format.md §4"，但开工必读清单没有它，全靠执行时想起来。
5. **次行业附录不可达**——PARAMS 允许 `industry = 主[,次]`，但必读清单第 7 条只读 `<主slug>.md`。跨界标的（如"互联网平台+半导体"）的次行业估值法被静默丢弃。
6. **指引/一致预期原文细节未列输入**——现在只能靠 ledger 登记过的数字（智谱 run 里"彭博锚"确实经 ledger 流到了估值），但公司原指引的**原文细节**在 `reconciled/03` 里，估值 agent 不读它。把 `reconciled/03-*.md` 发现节列为可选输入，基准情景锚定会更强。

## C. 看起来像缺口、其实是设计（不需要改）

- **红队的新证据（ARR 71 亿）只能等修正轮才进估值**——这是独立性设计的代价，且 v1→v2 迁移正确执行了预注册推翻条件，机制工作正常。
- **quality/ vs forensic/ 目录**——当前契约已统一为 `quality/`（`equity-forensic-accountant.md:45-46`），智谱 run 的 `forensic/grade.json` 是拆分前的旧结构，不是现行契约问题。

---

## 优先级与改动范围

**优先级**：#1 > #2 > #3（#1 影响每一份报告的 WACC 取数纪律；#2 已实际产生过一次被红队抓获的错误；#3 削弱交叉验证）。#4–#6 是顺手改。

**若实施，涉及四处**：

| 文件 | 改动 |
|---|---|
| `equity-data-collector.md` | 02 线范围加"WACC 市场输入"与可比分母要求 |
| `skill references/data-sources.md` | 采集项定义 + ledger 基准节契约加行 |
| `equity-data-reconciler.md` | CSV schema 加列（cash/有息负债/税前利润等） |
| `equity-valuation-analyst.md` | 必读清单补 output-format.md §4、次行业附录；可选输入加 reconciled/03 发现节 |
