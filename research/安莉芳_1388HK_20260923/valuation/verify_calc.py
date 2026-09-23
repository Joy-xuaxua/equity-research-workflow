# -*- coding: utf-8 -*-
"""W5 估值辅助核算（与 dcf.py 同目录运行的复核脚本，非心算替代物）"""
import json, sys
sys.path.insert(0, r"C:/Users/joyli/Documents/code_repo/equity-research-workflow/.claude/skills/equity-research-skill/scripts")
import dcf

cfg = json.load(open("valuation/assumptions.json", encoding="utf-8"))
price, shares, nd, w, g = cfg["price"], cfg["shares"], cfg["net_debt"], cfg["wacc"], cfg["terminal_g"]

print("== 1. 情景每股精确值（dcf.dcf_value） ==")
for sc in cfg["scenarios"]:
    r = dcf.dcf_value(sc, w, g, shares, nd)
    print(f"  {sc['name']:<5} EV {r['ev']:>15,.0f} | 每股 {r['per_share']:>8.3f} | 终值FCF {r['terminal_fcf']:>12,.0f} | 退出P/FCF {r['exit_pfcf']:.1f}x | TV占比 {r['tv_share']:.1%}")

print("== 2. 敏感性精确值（bull，每股） ==")
bull = next(s for s in cfg["scenarios"] if s["name"]=="bull")
for ww in cfg["sensitivity"]["wacc"]:
    row=[]
    for gg in cfg["sensitivity"]["g"]:
        v=dcf.dcf_value(bull, ww, gg, shares, nd)["per_share"]
        row.append(f"g={gg:.0%}:{v:.3f}{'*' if v>price else ' '}")
    print(f"  WACC {ww:.1%}  " + "  ".join(row))
print("  （* = 高于现价 0.243）")

print("== 3. 资产梯复核（FY2025 资产负债表，千港元） ==")
orderly = [("现金",181456,1.00),("应收净额",77544,0.85),("存货",431150,0.60),("其他流动(残差)",62639,0.70),
           ("PP&E",570912,0.45),("投资物业",465702,0.90),("深圳补偿物业",325222,0.80),("使用权资产",114448,0.0),("递延税资产",81602,0.0)]
stress = [("现金",181456,1.00),("应收净额",77544,0.70),("存货",431150,0.35),("其他流动(残差)",62639,0.50),
          ("PP&E",570912,0.25),("投资物业",465702,0.70),("深圳补偿物业",325222,0.55),("使用权资产",114448,0.0),("递延税资产",81602,0.0)]
borrow, other_liab_ex_lease = 433579, 255764   # 借款(不含租赁)、其他负债(不含租赁)=775,225-476,520-42,941
for label, rows in [("有序", orderly), ("压力", stress)]:
    tot = sum(b*q for _,b,q in rows)
    eq = tot - borrow - other_liab_ex_lease
    print(f"  [{label}] 调整后资产 {tot:,.0f} − 借款 {borrow:,} − 其他负债 {other_liab_ex_lease:,} = 权益 {eq:,.0f} 千港元 → 每股 {eq*1000/shares:.2f}")
    for n,b,q in rows: print(f"      {n:<10} {b:>8,} × {q:.0%} = {b*q:>10,.0f}")

print("== 4. WACC 构建复核 ==")
rf, erp, bu, wd_ind, kd = 0.0478, 0.0518, 0.76, 0.1524, 0.041
bl = bu*(1+(1-0)*wd_ind/(1-wd_ind)); coe = rf+erp*bl
wacc = (1-wd_ind)*coe + wd_ind*kd
print(f"  再杠杆β = 0.76×(1+0.1524/0.8476) = {bl:.3f} | CoE = 4.78%+5.18%×{bl:.2f} = {coe:.2%} | WACC = 0.848×{coe:.2%}+0.152×4.1% = {wacc:.2%} → 取 8.6%")
kd_check = 15522/((323253+433579)/2)
print(f"  Kd 复核：FY2025 融资成本 15,522 / 平均借款 {(323253+433579)/2:,.0f} = {kd_check:.2%}（税后≈税前，亏损结转无税盾）")

print("== 5. 情景权益价值合成（资产/受困混合口径，判断层） ==")
bear_v, base_v, bull_v = 0.10, 0.40, 0.70
pb, pba, pbb = 0.40, 0.375, 0.225
blend = pb*bear_v+pba*base_v+pbb*bull_v
print(f"  熊 0.10（受困定价 0.05-0.08×账面 P/B 中值）| 基准 0.40（盈亏平衡+受困重估 0.10-0.11×账面）| 牛 0.70（=脚本牛情景 DCF 0.69）")
print(f"  概率加权 = 0.40×0.10+0.375×0.40+0.225×0.70 = {blend:.3f}")
worst = 0.55*0.10+0.35*0.40+0.10*0.70; best = 0.25*0.10+0.40*0.40+0.35*0.70
print(f"  稳健性：最不利概率组合(0.55/0.35/0.10) → {worst:.3f}；最有利(0.25/0.40/0.35) → {best:.3f}（区间 [0.15,0.55] 均覆盖 → 标定「合理」不翻转）")

print("== 6. 单年 EVA 与脚本 EVA 退化演示 ==")
ic, nopat = 1843919000, -124809000
eva1 = nopat - w*ic
print(f"  FY2025 单年经济利润 = NOPAT −124,809,000 − WACC 8.6%×IC 1,843,919,000 = {eva1:,.0f} 港元/年")
spread0 = nopat/ic - w
pv_frozen = sum((spread0*(1-t/10))*ic/(1+w)**t for t in range(1,11))
print(f"  [退化演示] 若 ic_t 冻结（不套用 ic_t=nopat/(wacc+spread_t) 更新式）：PV(EVA,10年衰减) = {pv_frozen:,.0f} → EV = {ic+pv_frozen:,.0f} → 每股 {(ic+pv_frozen-295064000)/shares:.2f}")
for t in [5,6,7]:
    sp = spread0*(1-t/10); den = w+sp
    ic_t = nopat/den if den>0 else ic
    print(f"    t={t}: spread {sp:.2%}, 分母 wacc+spread {den:.2%}{' >0 → ic_t 被更新为 ' + f'{ic_t:,.0f}' if den>0 else ' ≤0 → ic_t 保持'}"
          f" → EVA_t = {sp*ic_t:,.0f}{'（正号＝伪信号）' if sp*ic_t>0 else ''}")
print("  结论：脚本 EVA 的 ic_t 更新式在 NOPAT<0 且利差收敛过半后产生大额正值伪信号（4.40/股不可采信）；采信项＝ROIC −6.8%、利差 −15.4%、g=RR×ROIIC=−1.0% 自洽行与单年 EVA。")

print("== 7. 相对估值锚复核 ==")
bk_2026h1 = 1554598000/shares; bk_fy25 = 1548855000/shares
print(f"  每股账面（2026H1）{bk_2026h1:.2f} | 现价 P/B {price/bk_2026h1:.3f}× | 52周 0.240–0.440 → P/B {0.240/bk_2026h1:.3f}–{0.440/bk_2026h1:.3f}×")
print(f"  受困资产 P/B 带 0.05–0.15× → {0.05*bk_2026h1:.2f}–{0.15*bk_2026h1:.2f}/股")
mc, rev_ttm = 102647243, 1187709000
print(f"  P/S：现价 TTM {mc/rev_ttm:.4f}× | 受困带 0.05–0.12× → {(0.05*rev_ttm)/shares:.2f}–{(0.12*rev_ttm)/shares:.2f}/股 | 都市丽人 P/S≈0.18×（盈利同业，Tier 5）")
print(f"  量化锚（非分析师）：StockInvest 0.297 | AlphaSpread 0.35")
print("== 8. 标定 ==")
print(f"  calibrate(0.243, 0.15, 0.55) = {dcf.calibrate(0.243,0.15,0.55)}（0.85L=0.128 ≤ 0.243 ≤ 1.15H=0.633）")
