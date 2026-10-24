# 估值环节重构实施日志（2026-10-23）

依据计划：`C:\Users\joyli\.claude\plans\cozy-discovering-rose.md`（事实层脚本化 · 驱动式经营模型 · 规则化综合区间）。
本轮全链路落地：脚本、测试、references、行业表、agent 与编排文档。存档 run（`research/`）一律不动；回放只在 scratchpad 中进行。

## 改动清单

| 文件 | 内容 |
|---|---|
| `scripts/valuation_inputs.py`（新） | 事实层生成器，产出 `valuation/inputs.json`：价格/股本/fx（derived-inputs）、净债、基准日期核对（`basis_flag`）、基期营收（成对半年行 → TTM）、报告口径利润率、有效税率、IC 序列与"干净"判定、历史序列。CSV 卫生检查不过即 fail loud（exit 1，不写输出） |
| `scripts/dcf.py` | 新增 schema 3（`--inputs` + `--config`；`--demo3`）。实现驱动式 FCFF、各方法 [lo, mid, hi]、闸门、预注册权重、插值加权中位数合成、诊断、football field、驱动龙卷风、固定扰动集稳健性、情景混合 MC、EVA 恒等分解、`listings` / `structure_discount`。旧配置走原逻辑，`--demo` 输出逐字不变（有 golden 测试守护）。抽出折现内核 `_pv()`，新旧两套逻辑共用 |
| `scripts/check_research_output.py` | schema 3：读同目录 `inputs.json`，import dcf 重算区间并比对报告标签，支持"无法给出可靠估值区间"。新增检查：概率下限 P1、旧式手填路径 P2、权重调整超限 P0、g>rf P0、`basis_flag` 未处理 P1、calc/ 以外的计算文件 P2、重算失败 P0。`--financials` 增加 CSV 卫生检查（P1，与 valuation_inputs 同一实现） |
| `equity-research-orchestration/lint_contract.py` | assumptions 为 schema 3 时要求有 `valuation/inputs.json`；旧配置零影响 |
| `.github/workflows/ci.yml` | py_compile 加入 valuation_inputs/derive_metrics；demos 加 `--demo3`；设 `PYTHONUTF8=1` |
| `tests/test_dcf.py`、`tests/test_valuation_inputs.py`（新）、`tests/test_check_research_output.py`、`tests/golden/dcf_demo_legacy.txt` | 见下方"验证" |
| `references/valuation-assumptions.md`（新） | 参数卡 R1（§0 事实层＋override、§1 驱动、§2 方法、§3 概率、§4 权重与闸门、§5 自检、schema 3 骨架） |
| `references/industry-rules.json` | R6：每个行业加 `valuation {primary, fcff_applicable, note}` |
| references R2–R5、R7–R9；agents（valuation-analyst / verdict-writer / red-team）；orchestration SKILL.md | 见"文档改动"一节 |

## 与计划的出入（需要你过目）

1. **L≤H 的保证**。插值加权中位数对权重连续，但两侧各自排序时并不能保证 L≤H。随机测试中，按现实权重（主方法 0.5 ±0.1）约 0.16% 的组合出现 L>H。实现上的处理：先按计划分别计算两侧；一旦 L>H，改为"按 mid 排序、同一组插值系数同时作用于 lo/hi"，这样 L≤H 一定成立，同时打出"合成口径回退"标记。`composite_range()` 有专门测试覆盖回退分支。
2. **权重调整后归一**（按计划字面执行）：`adjust +0.1` 之后整体归一，所以实际增量会略小于 0.1。例如 demo 中 epv 由 0.25 调为 0.35/1.1＝0.318。如果希望"调多少就是多少"（从其他方法按比例扣），需要改。
3. **pro_forma 现金只作用于 EV 口径的桥**（dcf / epv / EV 口径倍数 / sotp 扣净债），不作用于 equity 口径倍数（P/B、P/E 的指标停在资产负债表日）。
4. **终值期不计剩余 NOL**：第 N+1 年按全额税率计税（保守），这一点只在文档里说明，没有做成参数。
5. **财年结束日**：derived-inputs 没有 `fiscal_year_end` 时假定为 12-31，并打印注记。建议 W2 以后转录这一项（3 月年结的公司 H1 日期会因此受影响）。
6. **`basis_flag` 几乎总会触发**（股价日一定晚于资产负债表日）。这是有意为之：逼分析师每次都写 `pro_forma` 或 `basis_confirmed`。
7. **MC** 在情景混合抽样之外，WACC 另加 ±0.5pp 均匀扰动（计划没写明，沿用旧 MC 的精神）。
8. **驱动龙卷风的"一档"**：g1/g2 ±5pp、half_life ±1、margin_target/m1 ±2pp、margin_years ±2、S2C ±30%、tax ±5pp、WACC ±1pp、永续 g ±0.5pp。
9. **行业主方法表**（子 agent 逐个核对附录 §6）与草稿不同的地方：utilities 改为 [dcf, multiples, sum_of_parts]（附录 §6 把 DCF 列第一）；industrials / hardware / healthcare-services / media-gaming 增加 sum_of_parts（附录要求多元集团做 SOTP）；insurance 仍为 `fcff_applicable=false`（健康险/经纪其实有 FCF 口径，可考虑改为 "subtype"）；banks 的剩余收益没有对应的方法名，只写进 note；reits 的 AFFO-DCF 与 mREIT P/B 写进 note。

## 验证

1. `python -m unittest discover -s tests`：**全绿**（见文末数字）。`dcf.py --demo` 与改动前逐字一致（golden 取自 HEAD 版本）；`--demo3` 输出"合理"；`check_research_output.py --demo` 通过。
2. **回放**（scratchpad，不写 research/）：

| 标的 | 存档 | schema 3 回放 | 说明 |
|---|---|---|---|
| 1388.HK | [0.15, 0.55] → 合理 | **无法给出可靠估值区间** | DCF：基准每股 −2.00（计入再投资后，牛情景也为 −1.46）→ 闸门剔除；EPV：近 5 年利润率中位 −5.7% → 剔除；倍数：同业只有都市丽人 1 家、P/B 无原始观测 → 剔除；资产梯 [0.89, 1.89] 无变现路径 → 只作信号。与计划预期分支一致 |
| 智谱 02513.HK | [60, 420] 港元 → 显著高估 | **[34.1, 148.8] 港元 → 显著高估** | 单一方法（EPV 被剔除）。稳健性翻转 0/8。区间低于存档，原因是计入了再投资和税（存档路径隐含"增长不需要资本"）。龙卷风前三：half_life、margin_years、S2C |

   回放的翻译口径：
   - **1388**：base_revenue 用 ledger 的 TTM 做 override，net_debt 用 2026-06-30 的值做 override，并写 `basis_confirmed`；m1＝剔除减值后的 −10.7%；税率按 hk 法定税率；S2C 取历史"干净"值 0.60。
   - **智谱**：存档 CSV 的 FY2022/23 两行列错位，`valuation_inputs.py` 按预期拒绝。回放时在副本里删掉这两行；**存档本身未修**（按"非本轮"）。用 `pro_forma` 计入 7-13 配售净额；S2C 1.5 为回放假设。
   - **智谱的 m1 敏感点**：如果按报告口径 m1＝−271%（TTM），基准情景为负 → "无法给出可靠估值区间"。用存档情景首年 FCF 率（−120% / −60% / −40%）作为 m1 才得到"显著高估"。这说明 m1 是这类公司的第一承重驱动，参数卡要求偏离报告口径必须写锚和证据，或逐项列出 m1_adjustments，正是为了约束这一点。
3. `lint_contract.py` 跑两个存档 workdir：输出与改动前一致（各 2 项既有的 GRADE_MISMATCH，与本轮无关）。checker `--financials` 对智谱存档 CSV 报出 2 条 CSV_ROW_LENGTH（P1）。

4. 全量：`python -m unittest discover -s tests` **115 个测试全部通过**；industry-rules.json 通过 json.tool；四个脚本 py_compile 通过。

## 文档改动

| 文件 | 改动 |
|---|---|
| `valuation-methods.md`（R2） | 原则改为"至少三种**适用**方法"并指向参数卡；§2 改成驱动式 FCFF（纯文本公式），终值三查第 3 条改由脚本默认实现，敏感性改为 WACC×margin_target（成长股加 g1×margin，ROIIC∞≠WACC 时加 WACC×g）＋龙卷风；§3 EPV 写常态化默认与闸门；§4 反向 DCF/PVGO 改为自动运行，不进区间；§5 稳健性改为固定扰动集，删除"最不利概率组合"，MC 改为情景混合抽样；§6 EVA 改为 DCF 分解；§7 写三种配置块与变现路径闸门；§8 整节替换为合成规则 ①–⑥（含 L>H 回退说明）；§9 不确定性纳入三类标记，增加"无法给出可靠估值区间"的处理 |
| `base-rates.md`（R3） | §1 写明半衰期 3 年的来历；§5 第 3 条改由参数卡熊值规则执行 |
| `cost-of-capital.md`（R4） | §1 写明由 `wacc` 块计算；§3 增加 g ≤ rf 硬校验 |
| `expectations-investing.md`（R5） | 反向 DCF/PVGO 改为自动运行；Gap 表"我的预期"列与驱动一一对应 |
| `output-format.md` §4（R7） | 估值四件（football field、方法区间表、敏感性表、稳健性表）由脚本输出、原样粘贴；示例换成脚本格式；高于现价的单元格由 agent 加粗 |
| `markets-cn-hk.md` §5–6、§8（R8） | A/H 分市场结果走 `listings`；ADR/VIE 在 `structure_discount` 和尾部概率中二选一 |
| `earnings-mode.md` §5（R9） | FV 桥按驱动组归因（逐组替换各跑一次 dcf.py）；`--bridge` 留作后续 |
| `equity-valuation-analyst.md` | 必读清单加入参数卡；输入改为 inputs.json；动作改为五步（inputs → 判断层 → dcf.py ≤3 次自修 → 粘贴脚本表并归因分歧 → thesis brief 取龙卷风前三）；新增"计算出口"条款；删除"最不利概率组合"和 range_low/high |
| `equity-verdict-writer.md` | 支持"无法给出可靠估值区间"标定行：原样引用，动作只按 grade 与否决链给出 |
| `equity-red-team.md` | 攻击面改为"驱动＋锚＋分位＋龙卷风前三"；pre-mortem 承重假设对应龙卷风前三 |
| `equity-research-orchestration/SKILL.md` | §3 W5 产物、§5 契约加入 inputs.json 与 calc/；§7 增加"inputs 生成失败 → 重派 W2 修数"的失败路径 |

## 待定（实施中暴露、计划未覆盖）

- **"无法给出可靠估值区间"＋grade A/B＋无否决项时，动作是什么？** 现在写的是"有 grade/action_cap 约束时取其约束，否则按 §9 否决项；估值不可靠本身作为动作依据"，没有钉死默认动作（例如"观望"）。
- 计划中的 ⚑ 项均已按草稿实施，并在文档中保留了 ⚑ 标记：半衰期 3 年、10 年 CAGR >30% 须写理由、S2C 行业默认表、法定税率表、ROIIC 上限 WACC+5pp、拒绝经验带、变现路径闸门、概率下限 0.15、无法估值时的动作、稳健性 margin ±2pp。
- 上文"与计划的出入"第 2、9 条需要你确认。
