# 估值参数卡（判断层的唯一规则来源）

原则：**事实由脚本生成，假设只给驱动，区间按规则合成。**

- 事实层由 `scripts/valuation_inputs.py` 生成，写入 `valuation/inputs.json`。分析师不手抄事实；需要改时走 §0 的 override 协议。
- 判断层写在 `valuation/assumptions.json`（`"schema": 3`），只放驱动参数。每个驱动都要标出锚、分位和证据。
- `scripts/dcf.py --inputs valuation/inputs.json --config valuation/assumptions.json` 负责生成全部路径、各方法区间、闸门、权重、综合区间、稳健性和标定行。
- 本卡标 ⚑ 的条目是待定点：先按这里写的执行，有异议在改动说明里讨论。

---

## §0 事实层与 override 协议

| 事实 | 生成规则 | 来源 |
|---|---|---|
| price, shares_outstanding | 取自 derived-inputs（W2 锚校验过）。**禁止使用 CSV 的 `shares` 列**（IAS 33 加权平均股数） | derived-inputs |
| fx | 键名 `fx_<价格币>_<报表币>`，含义是每 1 价格币兑多少报表币。每股（价格币）＝权益（报表币）÷fx。没有该键时视为同币，并打印声明 | derived-inputs |
| net_debt | 取最新资产负债表期：`interest_bearing_debt − cash`（有 `minority_equity` 列时再加上它） | csv |
| 基准日期核对 | 比较资产负债表日、股本日、股价日。股本或股价日期晚于资产负债表日 → `basis_flag` | 脚本 |
| base_revenue | CSV 有成对半年行时取 TTM＝FY＋H本期−H上期；否则取最新 FY | csv |
| op_margin_reported | 与基期同口径；历史序列引用 derived.csv 的 `om_pct`，不重算 | csv / derived |
| tax_effective | 盈利年份 1−NI/PTI 的中位数，夹在 [0, 40%]；没有盈利年份 → null | csv |
| IC, Rev/IC, ROIC | IC＝(总资产−总负债)＋有息负债−现金。逐年给出序列，并判定"是否干净"：近 5 个 FY 中 ≥3 期、IC 全部 >0、变异系数 <0.5 | csv |
| CSV 卫生 | 行长度＝表头；cash ≤ 总资产；总负债 ≤ 总资产×5；有息负债 ≤ 总负债；金额单位约定为千元 | 脚本 fail loud（exit 1，不写输出） |

**override**：写在 assumptions.json 的 `overrides[]`，格式为 `{"field","value","reason","source"}`，例如用 ledger 里的 TTM，或用 pro-forma 现金。dcf.py 会逐条打印"⚠ 事实覆盖"。只覆盖了 `base_revenue` / `base_operating_income` 时，脚本会按新口径重算 `op_margin_reported`。

**basis_flag**：存在时，必须二选一，否则 dcf.py 硬错：
- `pro_forma`：`{"cash_delta"（千元报表币，加到权益）, "shares_basis", "source"}`
- `basis_confirmed`：`{"reason"（无期后事件）, "source"}`

**生成失败**（CSV 卫生不过或缺价格/股本锚）：不要绕过。回报编排者，由编排者重派 W2 修数。

---

## §1 驱动参数卡

驱动可以写在顶层 `drivers`（三情景共用），也可以写在情景里（覆盖共用值）。值可以写成数字，也可以写成 `{"value", "anchor", "pctile", "evidence", "reason"}`；**基准情景的关键驱动一律用对象形式**。

| 参数 | 默认 / 锚的优先级 | 三情景规则 | 偏离须给 | 脚本校验 |
|---|---|---|---|---|
| `g1` 首年增速 | 公司指引中值 → 一致预期中值（reconciled 03）→ TTM 同比 | 熊 ≤ 指引下沿，且 ≤ 自身历史同比 P30；牛 ≤ 指引上沿/一致预期高值；无指引时熊/牛＝基准 ∓ 历史同比标准差 ⚑ | 基准偏离锚 >5pp：在 `g1.reason` 写结构性理由 | 打印与锚的差；违反熊规则时警告 |
| `g2` 第 2 年起点 | ＝g1（单段） | 超高增速时可显式给出 | 引用指引或订单 | — |
| `half_life` | **3 年** ⚑；限 [0.5, 5] | 可分情景 | >4：`half_life_reason`（ch3 护城河"宽"＋领先指标） | 打印 5/10 年 CAGR；10 年 CAGR >30% 必须写 `extreme_growth_reason`，否则硬错 ⚑ |
| `horizon` N | 10 | — | 7–15（长 capex 周期） | 限 [3, 30] |
| `m1` 首年经营利润率 | ＝报告口径当前利润率 | — | 常态化要用 `drivers.m1_adjustments[]` 逐项列出 `{item, amount, source}`（出处为 quality/earnings-quality.md）；直接给数且偏离报告口径 >2pp 时须用对象形式写锚和证据 | 打印调整明细；偏离未注明时警告 |
| `margin_target` | 自身近 5 年中位，或行业附录稳态区间；亏损成长股取同业成熟期中位，并写达成年数 | 熊 ≤ 自身历史 P30；牛 ≤ 最佳同业水平 | 高于自身历史最高或同业 P80：`margin_reason`（结构性理由＋同业达成年数与规模） | 打印相对历史的分位；缺理由时警告 |
| `margin_years` | 5 | 熊可更长 | <3：合同或成本证据 | ≥1 |
| `sales_to_capital` | 历史"干净"时取历史中位；否则**必须显式给值** | 一般三情景同值 | 写明来源（同业/行业资料）；偏离历史 ±30% 时写理由 ⚑（是否另建行业默认表待定） | 打印逐年隐含 ROIC；>50% 时警告 |
| `tax` | 有效税率；为 null 时按法定税率表（顶层 `market`：us 21% / hk 16.5% / cn 25%）⚑ | — | — | — |
| `nol_open` 期初可抵亏损 | 0（保守） | — | 须引用年报税项附注 | — |
| `dilution` | **0**（IFRS 经营利润已含 SBC） | — | 预期增发或未费用化激励：写理由 | — |
| `allow_capital_release` | false | — | 收缩型公司可开，累计释放 ≤ 期初 IC，写理由 | 脚本封顶 |
| `terminal.g` | min(rf, 2.5%) | 同值 | 衰退行业可取 0–1%；**> rf 硬错** | 硬校验 |
| `terminal.roiic` | ＝WACC（null） | 情景可单独给 `roiic`，牛可 >WACC | 写 `roiic_reason`（ch3 护城河"宽"＋CAP 论证）；上限 WACC+5pp ⚑ | 硬校验 |

**驱动模型**（脚本实现，见 valuation-methods.md §2）：增速分两段——g1 显式；从第 2 年起由 g2 按半衰期衰减，并归一到第 N 年恰好＝g∞。利润率从 m1 线性走到 margin_target。再投资＝ΔRev/S2C，下限为 0。亏损年不交税并累积 NOL。

**WACC**：写 `wacc` 块 `{rf, beta, erp, crp?, kd_after_tax | kd_pre_tax+marginal_tax, target_debt_weight}`，由脚本按 CAPM 和目标结构计算。各分项从 ledger 的 WACC 市场输入节逐项引用（见 cost-of-capital.md）。

---

## §2 方法参数卡

方法写在 `methods` 下，每种方法输出每股 [lo, mid, hi]（价格币）。

- **dcf**（有 `scenarios` 即启用）：mid＝概率加权；lo/hi＝中点 CDF 插值的 P25/P75。插值前，情景值先截到 0。
- **epv**（默认启用，写 `"epv": false` 可关闭）：常态化 NOPAT＝近 5 年经营利润率中位数 × 基期营收 × (1−t)，可加 `adjustments[] {item, amount, source}`。区间按 WACC±1pp 计算。
- **multiples**：写 `{"items": [...]}`。每一项 `{name, basis: equity|ev, metric: revenue|book_equity|net_income|ebitda|ebit 或 metric_value＋metric_source, peers[{name,value,source}] 或 history[{period,value}]}`。
  - 观测须 ≥3 个，由脚本算 P25/P50/P75。**不接受经验带**（写 `band` 字段硬错）⚑；观测不足 3 个时该倍数剔除。
  - 同一方法下的多个倍数先按同规则（等权插值中位数）合成，整体算一票。
  - 脚本同时打印合理倍数——P/E：(1−g/ROIIC)/(r−g)；P/B：(ROE−g)/(CoE−g)——并与市场倍数对照。
- **sum_of_parts**：`{kind: sotp|nav|asset_ladder|liquidation, parts[], deductions[], deduct_net_debt?, realization_path?}`。
  - 部件类型有三种：`value {lo,mid?,hi}`、`metric_x_multiple {metric_value, multiple{lo,mid?,hi}}`、`metric_div_rate {metric_value, rate{lo,mid?,hi}}`，每个部件都要带 `source`。
  - 资产梯的折扣：压力情形取 §3 表下沿，有序情形取上沿。
- **资产法的变现路径闸门** ⚑：`asset_ladder` / `liquidation` 只有在 `realization_path {evidence, source}` 有公告证据（控制权变更、处置、回购或分红政策、清算程序）时才进区间。否则只作为"资产底价（少数股东不可实现）"信号输出。
- **custom**：`[{name, script: "valuation/calc/<name>.py", output?}]`。脚本输出里要有 `RESULT lo=… mid=… hi=…`（每股，价格币）。非行业主方法时权重上限 0.25。

---

## §3 概率与证据

- 默认概率为 0.25 / 0.50 / 0.25；偏离默认时写 `prob_reason`。
- 每个情景 ≥0.15 ⚑。
- 非基准情景：证据中强 ≥0.30，证据强 ≥0.40。
- 基准情景：证据弱 ≤0.40。
- 违反以上规则时，脚本打印警告，checker 报 P1。概率之和 ≠1 为硬错。

---

## §4 权重与闸门

**默认权重**：行业主方法 0.5（`industry-rules.json` 的 `valuation.primary`，可用 `primary_method` 在可选列表内改选），其余适用方法均分。主方法被剔除时，所有适用方法等权。

**调整**：`weights.adjust {method_id: Δ}`，每项 |Δ| ≤0.1，超限硬错；每项都要在 `weights.reasons` 写理由。调整后归一。

**闸门**（由脚本强制执行）：

| 条件 | 处理 |
|---|---|
| 行业 `fcff_applicable=false` | dcf、epv 关闭；为 `"subtype"` 时须给 `fcff_applicable`＋`fcff_applicable_reason` |
| 基准情景每股 ≤0 | dcf 关闭，标"经营价值为负" |
| 常态化 NOPAT ≤0 | epv 关闭 |
| 倍数对应的指标 ≤0，或观测 <3 | 该倍数关闭 |
| 资产梯 / 清算没有 `realization_path` | 只作信号 |

全部方法被剔除，或 H≤0 → 标定行为"无法给出可靠估值区间" ⚑。这时 verdict 按 grade 和动作矩阵处理。

---

## §5 自检清单（开工前、交稿前各勾一遍）

- [ ] 已跑 `valuation_inputs.py`，`inputs.json` 摘要逐项看过；`basis_flag` 已用 `pro_forma` 或 `basis_confirmed` 处理
- [ ] override 逐条带 reason＋source
- [ ] 基准情景的 g1 / margin_target / sales_to_capital 都写成对象：锚、分位、证据
- [ ] 熊/牛按 §1 三情景规则设值；10 年 CAGR >30% 已写 `extreme_growth_reason`
- [ ] 概率满足 §3；偏离默认已写 `prob_reason`
- [ ] 倍数只用逐家原始倍数（≥3）或自身历史序列，没有经验带
- [ ] 资产法有变现路径证据，否则接受它只作信号
- [ ] 计算全部在 dcf.py 或 `valuation/calc/` 内完成，没有其他计算文件
- [ ] dcf.py 输出中没有未解释的 [警告]；方法分歧已在章节逐项归因
- [ ] 标定行原样引用（含"无法给出可靠估值区间"情形）

---

## 附：schema 3 骨架

```json
{
  "schema": 3,
  "market": "hk",
  "overrides": [{"field": "base_revenue", "value": 0, "reason": "", "source": ""}],
  "basis_confirmed": {"reason": "", "source": ""},
  "wacc": {"rf": 0.0, "beta": 0.0, "erp": 0.0, "crp": 0.0, "kd_after_tax": 0.0, "target_debt_weight": 0.0},
  "terminal": {"g": 0.0},
  "drivers": {"sales_to_capital": {"value": 0, "anchor": "", "evidence": ""}, "m1_adjustments": []},
  "scenarios": [
    {"name": "bear", "prob": 0.25, "evidence": "中", "g1": 0.0, "margin_target": 0.0},
    {"name": "base", "prob": 0.50, "evidence": "中", "g1": {"value": 0.0, "anchor": 0.0, "pctile": "P50", "evidence": ""},
     "margin_target": {"value": 0.0, "anchor": "", "pctile": "", "evidence": ""}},
    {"name": "bull", "prob": 0.25, "evidence": "弱", "g1": 0.0, "margin_target": 0.0}
  ],
  "methods": {"epv": {"adjustments": []}, "multiples": {"items": []}},
  "weights": {"adjust": {}, "reasons": {}},
  "montecarlo": {"n": 2000, "seed": 42}
}
```

其他可选块：`listings[] {name, price, fx}`（A/H 分市场折算）、`structure_discount {pct, basis}`（ADR/VIE 显式折价，作用于各方法区间）、`primary_method`、`sensitivity_growth: true`（强制输出 g1×margin 表）。
