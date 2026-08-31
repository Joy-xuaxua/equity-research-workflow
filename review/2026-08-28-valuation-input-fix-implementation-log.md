# 估值输入契约修复实施日志（2026-08-31）

依据计划：`review/2026-08-28-valuation-input-fix-plan.md`（六项修复，全部落地）。
执行日：2026-08-31。本轮**纯契约修复**，未改任何 `scripts/*.py`、`collision-metrics.json`、编排 SKILL.md 波次表与 W3 输入（与计划"显式非目标"一致）。

## 改动清单（按提交）

| 提交 | 文件 | 内容 |
|---|---|---|
| `6059d37` feat: assign WACC market inputs and peer denominators to market collection line | `.claude/agents/equity-data-collector.md` | Fix 1a＋3a：02-market（full 列）加 WACC 市场输入（§2.4）＋可比倍数连 peer 分母一起采；04-industry（earnings 列）加 WACC 市场输入（data-sources.md §2.4） |
| `92398a5` feat: add data-sources section 2.4 WACC market inputs and peer denominator rule | `.claude/skills/equity-research-skill/references/data-sources.md` | Fix 1b＋3b：新增 §2.4「WACC 市场输入」（四项输入表＋未获取到纪律）；§8.2 末尾追加"可比估值锚连同分母一起采"bullet |
| `2396f8a` feat: ledger WACC baseline section and net-debt columns in financials.csv contract | `.claude/agents/equity-data-reconciler.md` | Fix 1c＋2a：ledger ①行情与股本基准节扩为含 WACC 市场输入节（rf/ERP/beta/汇率，各带来源与时间戳）；动作 5 CSV 列名追加 `cash, interest_bearing_debt, pre_tax_income`（可选 `deferred_revenue, minority_equity, goodwill`）＋新列口径句（net_debt 由估值 agent 用 interest_bearing_debt−cash 直接计算，不得从叙述拼分项重建） |
| `07b03d2` feat: valuation agent reads WACC baseline, CSV net-debt columns, output-format and secondary industry appendix | `.claude/agents/equity-valuation-analyst.md` | Fix 1d＋2b＋4＋5＋6：输入数据 ledger 行加「WACC 市场输入节 = 唯一取数来源」约束（禁"未核对"区间假设，缺项走 data-gaps＋cost-of-capital.md §2 快速档＋显式降级）；新增 financials.csv net_debt 行；必读清单插入第 7 条 output-format.md §4，原行业附录顺延为第 8 条并加次 slug 必读；输入数据追加可选锚定输入（reconciled/ 一致预期/指引线副本的「发现」与「指标登记」两节） |
| 本次 `docs:` | `review/2026-08-28-valuation-input-fix-implementation-log.md` | 本日志 |

## 验证输出摘要（计划验证清单逐项）

1. **grep 断言**（六条全过）：
   - `§2.4|WACC 市场输入` → 3 文件命中：collector :31/:33、reconciler :58、valuation-analyst :38 ✅（≥3）
   - `interest_bearing_debt` → reconciler :38、valuation-analyst :39 ✅
   - `### 2.4` → data-sources.md :84 ✅
   - `output-format.md` → valuation-analyst :33（必读清单）＋:55（动作 3）两处 ✅
   - `次slug|次 slug` → valuation-analyst :34 ✅
   - `分母` → data-sources.md :197 ✅
2. **CSV 加列冒烟**：`csv.DictReader` 按名取列，新表头 `period,revenue,cash,interest_bearing_debt,pre_tax_income` 解析正常（`OK [{'period': 'FY2025', ..., 'interest_bearing_debt': '10', 'pre_tax_income': '5'}]`）——加列不破坏检查器 ✅
3. **skill 测试套件**：`tests/` 4 个测试文件 **57 passed in 2.25s**，全绿 ✅（环境注：本机各 Python 均无 pytest，为跑本项安装了 pytest 9.1.1 到 C:\Python314；本轮未改任何 py，失败为零）
4. **markdown 表格完整性**：collector 线表（3 列×4 行）、data-sources.md §2.4 表（3 列×4 行）、reconciler 输出契约表均列数对齐；valuation-analyst 必读清单 1–8 连续编号 ✅
5. **交叉引用存在性**（追加检查）：`cost-of-capital.md` §1（构建顺序）/§2（快速档）、`output-format.md` §4（视觉件）均实际存在 ✅

## 待验证（下次研究运行的验收标准）

- [ ] W5 `valuation/valuation-notes.md` 的 WACC 构建表：rf/ERP/beta 三行全部引用 ledger 基准节值＋时间戳，不再出现"未获取到/当月值未核对"；
- [ ] `assumptions.json` 的 net_debt 可由 CSV `interest_bearing_debt−cash` 复算，红队无"不可复现"类发现；
- [ ] 相对估值表的可比分母带 peer 自身来源（不再全 Tier 5 弱锚）。
