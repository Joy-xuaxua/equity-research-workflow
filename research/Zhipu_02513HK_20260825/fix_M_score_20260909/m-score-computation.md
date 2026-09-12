# M-Score 计算留档（fix_M_score_20260909）

计算时间：2026-09-09｜执行环境：python 3（pypdf 提取＋纯 python 复算，无心算）
输入：`financials-fixed.csv`（＝0825 `forensic/financials.csv` ＋7 格补采值；7 格来源见 `collection-m-score.md` §A，Tier 1 年报）
检查器：`<skill_root>/scripts/check_research_output.py --financials financials-fixed.csv`（存档：`checker-financials-fixed.txt`）

## 1. 检查器实际输出（逐字）

```
财务/估值一致性检查发现 3 项：P0=0 P1=0 P2=2 P3=1

[P2] EPS_RECONCILIATION_MISMATCH [fix_M_score_20260909/financials-fixed.csv]: FY2025 的 EPS 与净利润/股本不一致，请确认单位。
    expected=-0.02957686396290122, provided=-12.03, net_income=-4718167.0, shares=159522220.0
[P2] FORENSIC_DSO_DIVERGENCE [fix_M_score_20260909/financials-fixed.csv]: 应收增速 233% 超收入增速 132% 逾 15pp，警惕塞货/放宽信用/提前确认。
[P3] FORENSIC_MSCORE_INFO [fix_M_score_20260909/financials-fixed.csv]: Beneish M-Score = -3.14（阈值 -1.78，未越限）。
    M=-3.14 | DSRI=1.43 GMI=1.37 AQI=1.14 SGI=2.32 DEPI=0.82 SGAI=0.74 TATA=-0.509 LVGI=1.40
```

**与原 CSV 基线对照**：原 CSV 复跑＝P0=0 P1=0 P2=2 P3=1（EPS P2、DSO P2、MSCORE_SKIPPED P3），与 `forensic/checker-financials.txt` 存档逐字一致；修复版仅第 3 项由 `FORENSIC_MSCORE_SKIPPED` 变为 `FORENSIC_MSCORE_INFO`，两项 P2 逐字复现（仅文件路径字段不同）——证明唯一变化即 M-Score 可算化。**无新增 P0/P1。**

## 2. 八分量全精度复算（python 脚本全文＋输出）

口径：t＝末行 FY2025，p＝次末行 FY2024（检查器 rows[-1]/rows[-2]）；金额人民币千元；输入行＝`financials-fixed.csv` FY2024/FY2025 行（7 格补采值来源：`collection-m-score.md` §A／原文附录 A-1/A-2/A-3）。

```python
import csv
rows = {}
with open('financials-fixed.csv', newline='', encoding='utf-8') as f:
    for r in csv.DictReader(f):
        rows[r['period']] = {k: (float(v) if k != 'period' and v not in ('', None) else v)
                             for k, v in r.items()}
t, p = rows['FY2025'], rows['FY2024']

dsri = (t['receivables']/t['revenue']) / (p['receivables']/p['revenue'])
gmi  = (p['gross_profit']/p['revenue']) / (t['gross_profit']/t['revenue'])
aqi_t = 1 - (t['current_assets']+t['ppe'])/t['total_assets']
aqi_p = 1 - (p['current_assets']+p['ppe'])/p['total_assets']
aqi  = aqi_t/aqi_p
sgi  = t['revenue']/p['revenue']
depi = (p['depreciation']/(p['depreciation']+p['ppe'])) / (t['depreciation']/(t['depreciation']+t['ppe']))
sgai = (t['sga']/t['revenue']) / (p['sga']/p['revenue'])
tata = (t['net_income']-t['cfo'])/t['total_assets']
lvgi = (t['total_liabilities']/t['total_assets']) / (p['total_liabilities']/p['total_assets'])
m = (-4.84 + 0.92*dsri + 0.528*gmi + 0.404*aqi + 0.892*sgi
     + 0.115*depi - 0.172*sgai + 4.679*tata - 0.327*lvgi)
```

输出（全精度）：

```
DSRI   = 1.434984   # (303208/724334) / (91135/312414) = 0.418602 / 0.291712
GMI    = 1.374656   # (175889/312414) / (296656/724334) = 0.563000 / 0.409557
AQI    = 1.144599   # [1-(3571411+655825)/4853861=0.129098] / [1-(3015867+866363)/4375769=0.112789]
SGI    = 2.318507   # 724334/312414
DEPI   = 0.815161   # (270252/(270252+866363)=0.237769) / (270068/(270068+655825)=0.291684)
SGAI   = 0.741833   # (896226/724334=1.237310) / (521078/312414=1.667909)
TATA   = -0.509294  # (-4718167-(-2246123))/4853861
LVGI   = 1.402948   # (12964843/4853861=2.671037) / (8330914/4375769=1.903874)

M = -4.84 + 0.92*1.4350 + 0.528*1.3747 + 0.404*1.1446 + 0.892*2.3185
    + 0.115*0.8152 - 0.172*0.7418 + 4.679*(-0.5093) - 0.327*1.4029
M = -3.1391  →  M ≤ -1.78，未越限（P3 INFO）
```

检查器四舍五入对照：M=−3.14 ✓；DSRI 1.43 ✓ GMI 1.37 ✓ AQI 1.14 ✓ SGI 2.32 ✓ DEPI 0.82 ✓ SGAI 0.74 ✓ TATA −0.509 ✓ LVGI 1.40 ✓（九项全部吻合）。

## 3. 旧可算分量回归核对（输入未变的回归校验）

| 分量 | 本轮全精度 | quality §7 L131 旧值 | 结果 |
|---|---|---|---|
| DSRI | 1.4350 | 1.435 | 一致 |
| GMI | 1.3747 | 1.3747 | 一致 |
| SGI | 2.3185 | 2.3185 | 一致 |
| TATA | −0.5093 | −0.5093 | 一致 |
| LVGI | 1.4029 | 1.4029 | 一致 |

五个旧分量逐位一致——补采只新增 AQI/DEPI/SGAI 三个分量与总分，未触碰任何既有输入。

## 4. 新增三分量判读（供 quality 修订引用）

- **AQI 1.14**（>1，轻热）：「软资产」（总资产−流动资产−物業及設備）占比 11.28%→12.91%，小幅上移；绝对水平低（~13%，主因是金融工具/联营权益等非实物资产），非典型资本化藏费形态。
- **DEPI 0.82**（<1，**良性**）：折旧率（折旧÷(折旧＋PPE净额)）由 23.78% 升至 29.17%——折旧不减反增（PPE 净额下降 24% 而折旧额持平），无「放慢折旧粉饰」迹象。
- **SGAI 0.74**（<1，**良性**）：SGA 费率由 166.8%（521,078/312,414）降至 123.7%（896,226/724,334）——费用率大幅收敛（规模效应），非「削减费用催利润」形态（本标的为亏损公司，无利润可催）。
- **总分 −3.14 的结构性解释**：M 模型的最大权重项 TATA（系数 4.679）＝−0.509，单项贡献 −2.38——深亏公司「账面亏损远大于现金消耗」的应计结构把 M-Score 深深压入「未越限」区。这是**模型在双亏结构下的已知局限**（M-Score 为盈利公司操纵检测设计），未越限**不构成**对收入质量的正面证明——与 quality §2/§3 既有结论（DSRI/DSO 红旗、KAM 点名）的关系是「模型总分不可用作否证，分量证据照常引用」。

## 5. DEPI 备选口径敏感性

主口径：现金流量表「物業及設備折舊」270,068/270,252（含使用权资产折旧，与 ppe 列同口径——见 collection-m-score.md §B.2）。备选：并入无形资产摊销 10,993/9,685（281,061/279,937）：

```
dep FY2025=281061, FY2024=279937 → DEPI = 0.8140（主口径 0.8152）
M(备选) = -3.1392（主口径 -3.1391，差 -0.0001）→ 判定不变：未越限
```

DEPI 及 M 总分对折旧口径完全不敏感（差 0.0001），主口径选择不影响任何结论。
