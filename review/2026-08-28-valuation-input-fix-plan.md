# 估值输入契约修复计划（2026-08-28）

> **执行者须知**：本计划自包含，可独立 session 执行，无需研究运行上下文。
> 依据：`review/2026-08-23-valuation-agent-input-audit.md`（六项发现，已全部核验为真）。
> 核验补充（2026-08-28）：审查引用的 `research/智谱_02513.HK_20260818` 已删除，不可逐字复核；
> 但其后继运行 `research/Zhipu_02513HK_20260825` **复发了同类症状**——
> `valuation/valuation-notes.md:26-27`（无风险利率"中债 10Y 当日值未获取到（采集线无利率行情）"、ERP"当月值未核对"）、
> 红队 R1（净现金叙述 10 倍单位错、不可复现）、EV/ARR 全 Tier 5 弱锚降权。六条修复均未落地。

## 改动总览

| # | 修复 | 文件 | 性质 |
|---|---|---|---|
| 1 | WACC 市场输入采集职责 | `.claude/agents/equity-data-collector.md`、skill `references/data-sources.md`、`.claude/agents/equity-data-reconciler.md` | 主修复 |
| 2 | financials.csv 加净债务/税前列 | `.claude/agents/equity-data-reconciler.md` | 主修复 |
| 3 | 可比公司分母采集要求 | `.claude/agents/equity-data-collector.md`、skill `references/data-sources.md` | 主修复 |
| 4 | 必读清单补 output-format.md §4 | `.claude/agents/equity-valuation-analyst.md` | 一行 |
| 5 | 次行业附录可达 | `.claude/agents/equity-valuation-analyst.md` | 一行 |
| 6 | 一致预期/指引副本列入可选输入 | `.claude/agents/equity-valuation-analyst.md` | 一行 |

skill 路径约定：本仓库唯一拷贝在 `.claude/skills/equity-research-skill/`（repo 根无第二份，已确认）。

---

## Fix 1 · WACC 市场输入（rf / ERP / beta / 汇率）有了唯一负责采集线

**问题**：`cost-of-capital.md` §1 要求当日 10Y（标时间戳）、Damodaran 当月隐含 ERP、行业无杠杆 beta，
但 02 线范围（collector body 第 31 行）与 `data-sources.md` 全文均无此三项，估值 agent 故意无网 → 只能靠记忆假设。

### 1a. `.claude/agents/equity-data-collector.md` — 采集线职责表（第 31、33 行）

02-market 单元格（full 列），现文：

```
| 02-market | 行情、股本与估值锚：价格/市值/倍数/52 周等（data-sources.md §2、§8.2） | 预期线：财报前一致预期、公司原指引、主要卖方分歧 |
```

改为：

```
| 02-market | 行情、股本与估值锚：价格/市值/倍数/52 周等（data-sources.md §2、§8.2）＋ WACC 市场输入（§2.4：估值币种 10Y 国债收益率、Damodaran 当月隐含 ERP 与国别溢价、行业无杠杆 beta、报告涉及币种间汇率） | 预期线：财报前一致预期、公司原指引、主要卖方分歧 |
```

04 行 earnings 单元格（第 33 行），现文：

```
| 04-industry | 行业、宏观与替代数据（data-sources.md §5、§9） | 市场线：盘前/盘后、首个完整交易日与报告时点价格；同日指数与核心同行对照 |
```

改为（earnings 模式 ch08 公允价值变动桥同样需要 WACC 输入）：

```
| 04-industry | 行业、宏观与替代数据（data-sources.md §5、§9） | 市场线：盘前/盘后、首个完整交易日与报告时点价格；同日指数与核心同行对照；WACC 市场输入（data-sources.md §2.4） |
```

### 1b. skill `references/data-sources.md` — 新增 §2.4（插在 §2.3 之后、§3 之前）

```markdown
### 2.4 WACC 市场输入（市场线职责，02-market / 04-market）

按 `cost-of-capital.md` §1 的构建需求，市场线必须采集以下四项（每项带值、来源/Tier、URL、时间戳）：

| 输入 | 定义 | 参考源 |
|---|---|---|
| 无风险利率 | 估值币种对应 10 年期国债收益率，当日值 | 中债/UST/港府债务工具中央结算系统；联系汇率制下 HKD 报表可用 UST 10Y 并注明 |
| ERP | Damodaran 当月隐含 ERP＋国别风险溢价（按业务地域收入加权，非上市地） | Damodaran 每月更新页 |
| 行业无杠杆 beta | Damodaran 行业页（按 G1 主行业附录选行业） | Damodaran data 页 |
| 汇率 | 报告涉及币种间即期汇率（估值币种 ↔ 报表币种 ↔ 可比口径币种），当日 | 央行中间价/PBoC、Wise 等公开报价 |

纪律：采不到时按「未获取到」落档（已尝试＋原因），禁止沿用记忆值或训练先验充当数据；
估值 agent 无网络工具，本节是这三项进入报告的唯一通道。
```

### 1c. `.claude/agents/equity-data-reconciler.md` — ledger 基准节契约（输出契约表，第 58 行）

现文（节选）：`①行情与股本基准节（现价/币种/时间戳/交易所/股本口径/市值——估值 agent 的锚）`

改为：`①行情与股本基准节（现价/币种/时间戳/交易所/股本口径/市值＋WACC 市场输入节：10Y 无风险利率/Damodaran 当月 ERP 与国别溢价/行业无杠杆 beta/涉及币种汇率，各带来源与时间戳——估值 agent 的锚）`

### 1d. `.claude/agents/equity-valuation-analyst.md` — 输入数据（第 37 行）

现文（节选）：`` `forensic/ledger.md`（**行情与股本基准节** = 你的 price/shares/市值锚） ``

改为：`` `forensic/ledger.md`（**行情与股本基准节** = 你的 price/shares/市值锚；**WACC 市场输入节** = rf/ERP/beta/汇率的唯一取数来源，WACC 构建表逐项引用其值与时间戳，禁止"未核对"的区间假设——缺项按 data-gaps 标注并走 cost-of-capital.md §2 快速档＋显式降级标注） ``

---

## Fix 2 · financials.csv 增列：cash / interest_bearing_debt / pre_tax_income

**问题**：`dcf.py` 顶层强制 `net_debt`（:284）、EVA 块强制 `invested_capital`（:160 且必须为正），
CSV 却没有对应列 → 净现金靠手工拼分项，0825 运行红队 R1 抓获 10 倍单位错、叙述不可复现。

### 2a. `.claude/agents/equity-data-reconciler.md` — 动作第 5 步（第 38 行）

现文（列名部分）：

```
`period, revenue, gross_profit, operating_income, net_income, cfo, capex, fcf, shares, eps, total_assets, receivables, ppe, current_assets, depreciation, sga, total_liabilities`（可加 `deferred_revenue`）
```

改为：

```
`period, revenue, gross_profit, operating_income, net_income, cfo, capex, fcf, shares, eps, total_assets, receivables, ppe, current_assets, depreciation, sga, total_liabilities, cash, interest_bearing_debt, pre_tax_income`（可加 `deferred_revenue, minority_equity, goodwill`）
```

同一步骤末尾追加一句（净债务是估值模型直接输入，不再允许叙述重建）：

```
新列口径：cash=现金及现金等价物（含可自由支配短期投资时在 ledger 注明口径）；interest_bearing_debt=有息负债合计（短+长借、租赁负债、应付债券）；pre_tax_income=税前利润。net_debt 由估值 agent 用 interest_bearing_debt−cash 直接计算，不得从叙述拼分项重建。
```

### 2b. `.claude/agents/equity-valuation-analyst.md` — 输入数据（第 37 行附近追加一行）

```
- `forensic/financials.csv` 的 `cash/interest_bearing_debt`（最新期）直接给出 net_debt；`minority_equity`（若有）用于 EV→equity 桥；列缺失时按 data-gaps 标注，禁止手工重建资产负债表分项。
```

**兼容性已核验**：`check_research_output.py` 用 `csv.DictReader`＋按名取列（`load_csv`/`pick`，:242-250），加列不破坏任何现有检查；`collision_check.py`/`derive_metrics.py` 不读 CSV 列名。

---

## Fix 3 · 可比公司分母（收入/ARR）随倍数快照一起采

### 3a. `.claude/agents/equity-data-collector.md` — 02-market 单元格（与 Fix 1a 同一处编辑，合并为）

```
| 02-market | 行情、股本与估值锚：价格/市值/倍数/52 周等（data-sources.md §2、§8.2，可比倍数必须连同 peer 分母一起采，见 §8.2）＋ WACC 市场输入（§2.4：估值币种 10Y 国债收益率、Damodaran 当月隐含 ERP 与国别溢价、行业无杠杆 beta、报告涉及币种间汇率） | 预期线：财报前一致预期、公司原指引、主要卖方分歧 |
```

### 3b. skill `references/data-sources.md` — §8.2 末尾追加一条 bullet

```markdown
- 可比公司估值锚必须**连同分母**一起采：peer 的收入/ARR/订阅额等（至少覆盖行业附录主倍数所需分母），同期间、同币种、注明口径（GAAP/Non-GAAP、财年错位）。只有倍数快照而无分母的按「未获取到」登记并说明，禁止用标的自身分母冒充 peer 分母。
```

---

## Fix 4 · 必读清单补 output-format.md §4

`.claude/agents/equity-valuation-analyst.md` 必读清单（第 27–33 行），在第 7 条（行业附录）之前插入：

```
7. `<skill_root>/references/output-format.md` **§4**（football field 文本图画法——动作 3 直接依赖）。
```

（原第 7 条顺延为第 8 条。）

## Fix 5 · 次行业附录可达

同文件必读清单第 7 条（现文：``7. 行业附录 `<skill_root>/industries/<主slug>.md` 的主估值方法与必备 KPI。``），改为：

```
8. 行业附录 `<skill_root>/industries/<主slug>.md` 的主估值方法与必备 KPI；PARAMS `industry` 含次 slug 时，`<次slug>.md` 同样必读（次估值法与 KPI 一并纳入）。
```

## Fix 6 · 一致预期/指引副本列为可选输入

同文件「输入数据」节（第 37–40 行）追加：

```
- 可选锚定输入：`reconciled/` 中一致预期/指引线副本的「发现」与「指标登记」节（full 读 `03-*.md`，earnings 读 `02-*.md`）——指引原文细节与多锚区间用于基准情景锚定；只读该两节，不读全文。
```

---

## 显式非目标（不要改）

| 不改 | 理由 |
|---|---|
| `references/collision-metrics.json` | WACC 输入是市场级单线参数，无跨线对撞语义；走「02/04 线发现节 → reconciler 转录 ledger 基准节」即现有 fx 通道，与登记块机制职责不同 |
| 任何 `scripts/*.py` | 本轮纯契约修复；检查器对 CSV 加列已验证兼容 |
| `equity-research-orchestration/SKILL.md` 波次表 | 编排者的一行式 line 描述不是操作定义，agent body 才是 |
| W3 forensic-accountant 输入 | 新列对 W3 只是多数据，五项检查不受影响（未来可选用 pre_tax_income 做税项检查，另行立项） |

## 验证（执行完必做）

1. **grep 断言**（每条应命中）：
   - `grep -n "§2.4\|WACC 市场输入" .claude/agents/equity-data-collector.md .claude/agents/equity-data-reconciler.md .claude/agents/equity-valuation-analyst.md`（≥3 文件命中）
   - `grep -n "interest_bearing_debt" .claude/agents/equity-data-reconciler.md .claude/agents/equity-valuation-analyst.md`
   - `grep -n "### 2.4" .claude/skills/equity-research-skill/references/data-sources.md`
   - `grep -n "output-format.md" .claude/agents/equity-valuation-analyst.md`（必读清单＋动作 3 两处）
   - `grep -n "次slug\|次 slug" .claude/agents/equity-valuation-analyst.md`
   - `grep -n "分母" .claude/skills/equity-research-skill/references/data-sources.md`
2. **检查器冒烟**（证明 CSV 加列兼容）：
   ```bash
   cd <repo> && PYTHONUTF8=1 python .claude/skills/equity-research-skill/scripts/check_research_output.py \
     --financials <(printf 'period,revenue,cash,interest_bearing_debt,pre_tax_income\nFY2025,100,60,10,5\n') 2>/dev/null \
     || PYTHONUTF8=1 python -c "import csv,io; r=list(csv.DictReader(io.StringIO('period,revenue,cash,interest_bearing_debt,pre_tax_income\nFY2025,100,60,10,5'))); print('OK', r)"
   ```
   （Windows Git Bash 下 `<(...)` 若不可用，用后半句 python 一行版即可——DictReader 按名取列即兼容证明。）
3. **skill 测试套件**（纯确认无意外耦合）：`cd <repo>/.claude/skills/equity-research-skill && PYTHONUTF8=1 python -m pytest tests/ -q`（应全绿；本轮未改任何 py，失败须查明是否既有问题）。
4. **markdown 表格完整性**：目测四处 agent body 表格与 data-sources.md 新 §2.4 表格列数对齐（编辑后 Read 一遍确认）。

## 下次研究运行的验收标准（写入 implementation log 的"待验证"节）

- W5 `valuation-notes.md` 的 WACC 构建表：rf/ERP/beta 三行全部引用 ledger 基准节值＋时间戳，不再出现"未获取到/当月值未核对"；
- `assumptions.json` 的 net_debt 可由 CSV `interest_bearing_debt−cash` 复算，红队无"不可复现"类发现；
- 相对估值表的可比分母带 peer 自身来源（不再全 Tier 5 弱锚）。

## 实施顺序与提交

1. Fix 1a+3a（collector 线表）→ 2. Fix 1b+3b（data-sources.md）→ 3. Fix 1c+2a（reconciler）→ 4. Fix 1d+2b+4+5+6（valuation agent）→ 5. 验证清单 → 6. 写 `review/2026-08-28-valuation-input-fix-implementation-log.md`（改动清单＋验证输出摘要＋下次运行验收标准）。
- 每完成一个文件提交一次，类型 `feat:`（契约能力新增），如 `feat: assign WACC market inputs to market collection line`；最后一个提交为 implementation log（`docs:`）。
