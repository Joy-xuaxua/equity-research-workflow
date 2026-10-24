#!/usr/bin/env python3
"""equity-research skill · 估值计算器 v2（禁止心算的替代物）

用法：
    python dcf.py --inputs valuation/inputs.json --config valuation/assumptions.json   # schema 3（现行）
    python dcf.py --config assumptions.json        # 旧配置（无 "schema": 3，存档 run 复跑）
    python dcf.py --demo                           # 旧配置内置示例自检
    python dcf.py --demo3                          # schema 3 内置示例自检

schema 3：事实层由 scripts/valuation_inputs.py 生成（inputs.json），判断层只给驱动参数
（g1/g2/half_life/m1/margin_target/sales_to_capital/…，见 references/valuation-assumptions.md），
脚本生成全部路径、各方法 [lo, mid, hi]、闸门、预注册权重、插值加权中位数综合区间、
稳健性固定扰动集、驱动龙卷风、情景混合 MC 与标定行。

模块：三阶段情景 DCF、概率加权、WACC×g 敏感性、反向 DCF、EPV/三要素、
EVA/剩余收益、PVGO 分解、蒙特卡洛、仓位思维（EV/不对称比/Kelly-lite）、
预注册标定标签。所有输入校验用显式异常（python -O 下依然生效）。

config JSON 顶层字段：price, shares, net_debt, wacc, terminal_g,
scenarios[], sensitivity{}, reverse{}, epv{}, eva{}, pvgo{}, montecarlo{},
range_low, range_high
"""
import argparse, json, math, random, re, sys

LABELS = ["显著低估", "低估", "合理", "高估", "显著高估"]

def die(msg):
    raise ValueError(f"[配置错误] {msg}")

def need(d, key, ctx):
    if key not in d:
        die(f"{ctx} 缺少必需字段 `{key}`")
    return d[key]

# ---------- 核心计算 ----------

def _pv(fcfs, wacc):
    """显性期折现内核（schema 2 情景 DCF 与 schema 3 驱动模型共用）。"""
    return sum(f / (1 + wacc) ** (i + 1) for i, f in enumerate(fcfs))

def scenario_fcfs(sc, terminal_g):
    """显式期+衰减期完整 FCF 序列与末年营收。"""
    name = sc.get("name", "?")
    if "fcf" in sc:
        if not isinstance(sc["fcf"], list) or not sc["fcf"]:
            die(f"情景 {name}: fcf 必须是非空数组")
        fcfs = list(sc["fcf"]); rev = None
    else:
        rev_path, m = need(sc, "revenue", f"情景 {name}"), need(sc, "fcf_margin", f"情景 {name}")
        if len(rev_path) != len(m):
            die(f"情景 {name}: revenue({len(rev_path)}) 与 fcf_margin({len(m)}) 长度不等")
        fcfs = [r * mm for r, mm in zip(rev_path, m)]
        rev = rev_path[-1]
    fade, g0 = sc.get("fade_years", 0), sc.get("fade_g_start", terminal_g)
    mm_last = sc["fcf_margin"][-1] if "fcf_margin" in sc else None
    for k in range(fade):
        gr = g0 + (terminal_g - g0) * (k + 1) / fade
        if rev is not None:
            rev *= (1 + gr); fcfs.append(rev * mm_last)
        else:
            fcfs.append(fcfs[-1] * (1 + gr))
    return fcfs, rev

def dcf_value(sc, wacc, g, shares, net_debt):
    if wacc <= g:
        die(f"WACC({wacc}) 必须大于永续增长 g({g})")
    if shares <= 0:
        die(f"股本必须为正（shares={shares}）")
    fcfs, _ = scenario_fcfs(sc, g)
    n = len(fcfs)
    pv = _pv(fcfs, wacc)
    tv = fcfs[-1] * (1 + g) / (wacc - g)
    ev = pv + tv / (1 + wacc) ** n
    explicit_years = len(sc.get("fcf", sc.get("revenue", [])))
    sh = shares * (1 + sc.get("annual_dilution", 0.0)) ** explicit_years
    tv_share = (tv / (1 + wacc) ** n) / ev if ev else float("nan")
    return {"ev": ev, "equity": ev - net_debt, "per_share": (ev - net_debt) / sh,
            "shares_end": sh, "terminal_fcf": fcfs[-1],
            "exit_pfcf": tv / fcfs[-1] if fcfs[-1] else float("nan"),
            "tv_share": tv_share}

def reverse_dcf(price, shares, net_debt, wacc, g, interim_fcf, steady_margins, base_revenue):
    if wacc <= g:
        die(f"反向 DCF: WACC({wacc}) 必须大于 g({g})")
    ev = price * shares + net_debt
    n = len(interim_fcf)
    pv_interim = sum(f / (1 + wacc) ** (i + 1) for i, f in enumerate(interim_fcf))
    tv_needed = (ev - pv_interim) * (1 + wacc) ** n
    fcf_req = tv_needed * (wacc - g)
    rows = []
    for m in steady_margins:
        if m <= 0:
            die(f"反向 DCF: steady_margin 必须为正（{m}）")
        rev_req = fcf_req / m
        cagr = (rev_req / base_revenue) ** (1 / n) - 1 if base_revenue else None
        rows.append({"margin": m, "revenue_required": rev_req, "implied_cagr": cagr})
    return {"ev": ev, "pv_interim": pv_interim, "fcf_required": fcf_req, "rows": rows}

def calibrate(price, lo, hi):
    """预注册标定（与 check_research_output.py 及 valuation-methods.md §9 完全一致）。"""
    if lo > hi:
        die(f"标定: range_low({lo}) > range_high({hi})")
    if price < lo * 0.50: return "显著低估"
    if price < lo * 0.85: return "低估"
    if price <= hi * 1.15: return "合理"
    if price <= hi * 1.50: return "高估"
    return "显著高估"

# ---------- EPV / 三要素（Greenwald）----------

def epv_value(e, coc, basis='NOPAT', net_debt=0.0, excess_cash=0.0):
    if coc <= 0:
        die("EPV: coc 必须为正")
    ev = e / coc
    if basis.upper() == 'NOPAT':
        return {'ev': ev, 'equity': ev - net_debt + excess_cash}
    return {'ev': None, 'equity': ev}

def franchise_growth_value(e, coc, g, roiic, basis='NOPAT', net_debt=0.0, excess_cash=0.0):
    if roiic is None or roiic <= 0 or not (coc > g):
        return None
    v = e * (1 - g / roiic) / (coc - g)
    if basis.upper() == 'NOPAT':
        return {'ev': v, 'equity': v - net_debt + excess_cash}
    return {'ev': None, 'equity': v}

def moat_verdict(ratio):
    if ratio < 1.0:  return 'EPV<净资产 → 毁灭价值（ROIC<资本成本），规避'
    if ratio <= 1.3: return 'EPV≈净资产 → 无/弱护城河的辛苦生意'
    return 'EPV≫净资产 → 护城河的财务度量（差额=特许经营价值）'

def run_epv(c):
    basis = c.get('earnings_basis', 'NOPAT')
    e, coc = need(c, 'normalized_earnings', 'epv'), need(c, 'coc', 'epv')
    nd, xc = c.get('net_debt', 0.0), c.get('excess_cash', 0.0)
    sh, av, price = need(c, 'shares', 'epv'), c.get('asset_value'), c.get('price')
    print(f"\n=== 盈利能力价值 EPV === 口径 {basis} | 常态化盈利 {e} | 资本成本(=WACC) {coc:.2%}")
    if basis.upper() != 'NOPAT':
        print("  [注] 退回净利润口径（coc 视作权益成本）")
    ep = epv_value(e, coc, basis, nd, xc)
    epv_ps = ep['equity'] / sh
    print(f"  EPV 权益价值 {ep['equity']:,.1f} | 每股 {epv_ps:,.2f}")
    if av:
        ratio = ep['equity'] / av
        print(f"  护城河验证：EPV/净资产 = {ratio:.2f}x → {moat_verdict(ratio)}")
    if c.get('asset_series'):
        print("  EPV/净资产 多年趋势：")
        for yr, ee, aa in c['asset_series']:
            print(f"    {yr}: {(ee/coc)/aa:.2f}x")
    growth_ps = None
    g = c.get('growth')
    if g:
        gg, roiic, mode = need(g, 'g', 'epv.growth'), g.get('roiic'), g.get('mode', 'franchise')
        fg = franchise_growth_value(e, coc, gg, roiic, basis, nd, xc) if mode == 'franchise' else None
        if fg is None:
            growth_ps = ep['equity'] * (1 + gg) / sh
            print(f"  成长价值（简化式兜底，g={gg:.1%}）：每股 {growth_ps:,.2f}")
        else:
            growth_ps = fg['equity'] / sh
            warn = ' ⚠ ROIIC<coc，增长毁灭价值' if roiic < coc else ''
            print(f"  成长价值（franchise 严格式，g={gg:.1%}，ROIIC={roiic:.1%}）：每股 {growth_ps:,.2f}{warn}")
    if av and price:
        asset_ps = av / sh
        print(f"  买点阶梯：底价 {asset_ps:,.2f}｜EPV {epv_ps:,.2f}" +
              (f"｜成长调整 {growth_ps:,.2f}" if growth_ps else ""))
    return {"epv_ps": epv_ps, "growth_ps": growth_ps}

# ---------- EVA / 剩余收益 ----------

def run_eva(c, top):
    ic = need(c, 'invested_capital', 'eva')
    nopat = need(c, 'nopat', 'eva')
    wacc = c.get('wacc', top.get('wacc'))
    sh = c.get('shares', top.get('shares'))
    nd = c.get('net_debt', top.get('net_debt', 0.0))
    fade = c.get('fade_years', 10)
    growth = c.get('nopat_growth', 0.0)
    rr, roiic = c.get('reinvestment_rate'), c.get('roiic')
    if wacc is None or wacc <= 0: die("eva: 缺少有效 wacc")
    if ic <= 0: die("eva: invested_capital 必须为正")
    roic = nopat / ic
    spread0 = roic - wacc
    print(f"\n=== EVA / 剩余收益 === NOPAT {nopat} | 投入资本 {ic} | ROIC {roic:.1%} | WACC {wacc:.2%} | 超额利差 {spread0:+.1%}")
    if rr is not None and roiic is not None:
        g_implied = rr * roiic
        print(f"  自洽检验：g = 再投资率 {rr:.0%} × ROIIC {roiic:.1%} = {g_implied:.1%}"
              f"（DCF 中假设的增速若高于此值，意味着需要外部资本或假设不自洽）")
    pv_eva, ic_t, nopat_t = 0.0, ic, nopat
    for t in range(1, fade + 1):
        spread_t = spread0 * (1 - t / fade)          # 超额回报线性衰减至 0
        nopat_t = nopat_t * (1 + growth)
        ic_t = nopat_t / (wacc + spread_t) if (wacc + spread_t) > 0 else ic_t
        eva_t = spread_t * ic_t
        pv_eva += eva_t / (1 + wacc) ** t
    value = ic + pv_eva
    equity = value - nd
    print(f"  剩余收益价值：投入资本 {ic:,.1f} + PV(EVA, {fade}年衰减) {pv_eva:,.1f} = EV {value:,.1f}")
    if sh:
        print(f"  权益 {equity:,.1f} | 每股 {equity/sh:,.2f}")
    if spread0 < 0:
        print("  ⚠ 当前 EVA 为负：公司未赚回资本成本，任何增长假设都在放大毁灭")
    return {"per_share": equity / sh if sh else None}

# ---------- PVGO 分解 ----------

def run_pvgo(c, top):
    e = need(c, 'earnings_ps', 'pvgo')          # 每股常态化盈利（或 FCF/股）
    r = c.get('r', top.get('wacc'))
    price = c.get('price', top.get('price'))
    if r is None or r <= 0: die("pvgo: 缺少有效折现率 r")
    if not price: die("pvgo: 缺少 price")
    zg = e / r
    pvgo = price - zg
    pct = pvgo / price
    print(f"\n=== PVGO 分解 === 每股盈利 {e} ÷ r {r:.2%} = 零增长价值 {zg:,.2f}/股")
    print(f"  现价 {price} = 零增长 {zg:,.2f} + 增长期权 PVGO {pvgo:,.2f} → **现价的 {pct:.0%} 在为未来增长付费**")
    if pct > 0.5:
        print("  ⚠ PVGO>50%：报告必须回答“这些增长从哪来、谁买单”（对照 base-rates）")
    return {"pvgo_pct": pct}

# ---------- 蒙特卡洛 ----------

def run_montecarlo(c, top):
    n = c.get('n', 2000)
    rng = random.Random(c.get('seed', 42))
    years = c.get('years', 5)
    rev0 = need(c, 'base_revenue', 'montecarlo')
    gm, gs = need(c, 'growth_mean', 'montecarlo'), need(c, 'growth_std', 'montecarlo')
    ml, mm, mh = need(c, 'margin_low', 'montecarlo'), need(c, 'margin_mode', 'montecarlo'), need(c, 'margin_high', 'montecarlo')
    wl, wh = c.get('wacc_low', top['wacc'] - 0.01), c.get('wacc_high', top['wacc'] + 0.01)
    g = c.get('terminal_g', top.get('terminal_g', 0.03))
    fade = c.get('fade_years', 5)
    shares, nd, price = top.get('shares'), top.get('net_debt', 0.0), top.get('price')
    if not shares: die("montecarlo: 顶层缺少 shares")
    vals = []
    for _ in range(n):
        gr = max(min(rng.gauss(gm, gs), gm + 3 * gs), gm - 3 * gs)   # 截断正态
        mg = rng.triangular(ml, mh, mm)
        wc = rng.uniform(wl, wh)
        if wc <= g: wc = g + 0.005
        rev, fcfs = rev0, []
        for _t in range(years):
            rev *= (1 + gr); fcfs.append(rev * mg)
        for k in range(fade):
            gr_f = gr + (g - gr) * (k + 1) / fade
            rev *= (1 + gr_f); fcfs.append(rev * mg)
        pv = sum(f / (1 + wc) ** (i + 1) for i, f in enumerate(fcfs))
        tv = fcfs[-1] * (1 + g) / (wc - g)
        ev = pv + tv / (1 + wc) ** len(fcfs)
        vals.append((ev - nd) / shares)
    vals.sort()
    q = lambda p: vals[min(int(p * n), n - 1)]
    mean = sum(vals) / n
    print(f"\n=== 蒙特卡洛（n={n}） === 公允价值分布（每股）")
    print(f"  P10 {q(.10):,.1f} | P25 {q(.25):,.1f} | P50 {q(.50):,.1f} | P75 {q(.75):,.1f} | P90 {q(.90):,.1f} | 均值 {mean:,.1f}")
    out = {"p50": q(.50), "mean": mean}
    if price:
        p_loss = sum(1 for v in vals if v < price) / n
        out["p_loss"] = p_loss
        print(f"  P(内在价值 < 现价 {price}) = {p_loss:.0%}  ← “现价买入是错误”的模型概率")
    return out

# ---------- 仓位思维 ----------

def run_position(results, cfg):
    price = cfg.get('price')
    scs = cfg.get('scenarios') or []
    if not price or not results or not scs:
        return
    pairs = [(sc.get('prob', 0.0), results[sc['name']]['per_share']) for sc in scs if sc['name'] in results]
    if not pairs: return
    ev_ret = sum(p * (v / price - 1) for p, v in pairs)
    ups = [(p, v / price - 1) for p, v in pairs if v > price]
    downs = [(p, 1 - v / price) for p, v in pairs if v <= price]
    up_mag = max((v for _, v in ups), default=0.0)
    down_mag = max((v for _, v in downs), default=0.0)
    asym = up_mag / down_mag if down_mag > 0 else float('inf')
    print(f"\n=== 仓位思维 === 概率加权期望收益 EV = {ev_ret:+.0%}")
    print(f"  上行幅度（牛） {up_mag:+.0%} | 下行幅度（熊） {-down_mag:.0%} | 不对称比 {asym:.1f}"
          + ("（<1.5：赔率结构不支持重仓）" if asym < 1.5 else ""))
    p_up = sum(p for p, _ in ups); p_dn = sum(p for p, _ in downs)
    b = sum(p * v for p, v in ups) / p_up if p_up else 0.0
    a = sum(p * v for p, v in downs) / p_dn if p_dn else 0.0
    if a > 0 and b > 0:
        kelly = (p_up * b - p_dn * a) / (a * b)
        lite = max(0.0, min(kelly / 4, 0.15))
        size = "标准" if lite >= 0.08 else ("中" if lite >= 0.04 else ("小" if lite > 0 else "零"))
        print(f"  Kelly-lite（¼Kelly，上限15%）≈ {lite:.0%} → 该赔率结构支持 **{size}仓位**（量级参考，非配置建议）")

# ---------- 主流程 ----------

def run(cfg):
    shares = need(cfg, "shares", "顶层")
    nd = cfg.get("net_debt", 0.0)
    wacc, g = need(cfg, "wacc", "顶层"), need(cfg, "terminal_g", "顶层")
    price = cfg.get("price")
    if shares <= 0: die("shares 必须为正")
    if not (0 < wacc < 0.5): die(f"wacc={wacc} 不在合理范围 (0, 0.5)")

    print(f"=== 输入 === 股本 {shares} | 净债 {nd} | WACC {wacc:.2%} | g {g:.2%}"
          + (f" | 现价 {price}" if price else ""))

    weighted, probs, results = 0.0, 0.0, {}
    if cfg.get("scenarios"):
        print("\n=== 情景 DCF ===")
        for sc in cfg["scenarios"]:
            r = dcf_value(sc, wacc, g, shares, nd)
            results[sc["name"]] = r
            p = sc.get("prob", 0.0); probs += p; weighted += p * r["per_share"]
            tv_warn = " ⚠TV>80%" if r["tv_share"] > 0.80 else ""
            print(f"  {sc['name']:<8} p={p:.0%}  EV {r['ev']:>9,.0f} | 每股 {r['per_share']:>7,.1f} "
                  f"| 退出P/FCF {r['exit_pfcf']:.1f}x | TV占比 {r['tv_share']:.0%}{tv_warn} "
                  f"| 期末股本 {r['shares_end']:.2f}")
        if abs(probs - 1.0) > 1e-6:
            print(f"  [警告] 概率和 = {probs:.2f} ≠ 1，加权值不可用")
        else:
            print(f"  ── 概率加权公允价值: {weighted:,.1f}/股"
                  + (f"（较现价 {(weighted/price-1):+.0%}）" if price else ""))

    sens = cfg.get("sensitivity")
    if sens and cfg.get("scenarios"):
        sc = next((s for s in cfg["scenarios"] if s["name"] == sens["scenario"]), None)
        if sc is None: die(f"sensitivity.scenario `{sens['scenario']}` 不在 scenarios 中")
        print(f"\n=== 敏感性（{sens['scenario']}，每股） ===")
        print("            " + "".join(f"g={gg:.1%}  " for gg in sens["g"]))
        for w in sens["wacc"]:
            cells = "".join(f"{dcf_value(sc, w, gg, shares, nd)['per_share']:>7,.1f} " for gg in sens["g"])
            print(f"  WACC {w:.1%} {cells}")

    rev = cfg.get("reverse")
    if rev and price:
        r = reverse_dcf(price, shares, nd, wacc, g, need(rev, "interim_fcf", "reverse"),
                        need(rev, "steady_margins", "reverse"), rev.get("base_revenue"))
        print(f"\n=== 反向 DCF ===  EV {r['ev']:,.0f} | 建设期FCF现值 {r['pv_interim']:,.0f}")
        print(f"  现价隐含稳态首年 FCF: {r['fcf_required']:,.0f}/年")
        for row in r["rows"]:
            cagr = f"，隐含营收 CAGR {row['implied_cagr']:.0%}" if row["implied_cagr"] is not None else ""
            print(f"    @FCF率 {row['margin']:.0%} → 需营收 {row['revenue_required']:,.0f}{cagr}")

    if cfg.get("pvgo"):        run_pvgo(cfg["pvgo"], cfg)
    if cfg.get("epv"):         run_epv(cfg["epv"])
    if cfg.get("eva"):         run_eva(cfg["eva"], cfg)
    if cfg.get("montecarlo"):  run_montecarlo(cfg["montecarlo"], cfg)
    run_position(results, cfg)

    if price and cfg.get("range_low") and cfg.get("range_high"):
        lo, hi = cfg["range_low"], cfg["range_high"]
        print(f"\n=== 标定 === 综合区间 [{lo}, {hi}] × 现价 {price} → **{calibrate(price, lo, hi)}**")
        print("  （动作映射与否决项见 valuation-methods.md §9，由分析师结合不确定性与财报可信度执行）")
    return results

# =====================================================================
# schema 3：事实层（inputs.json）＋判断层（驱动参数）→ 规则化综合区间
# 规则来源：references/valuation-assumptions.md（参数卡）、valuation-methods.md §2/§8
# =====================================================================

import copy, os, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, "..", "references", "industry-rules.json")
STATUTORY_TAX = {"us": 0.21, "hk": 0.165, "cn": 0.25}
PROB_DEFAULT = {"bear": 0.25, "base": 0.50, "bull": 0.25}
PROB_FLOOR = 0.15
PRIMARY_WEIGHT = 0.5
ADJ_LIMIT = 0.10
CUSTOM_CAP = 0.25
ROIIC_CAP_SPREAD = 0.05
METHOD_ORDER = ["dcf", "epv", "multiples", "sum_of_parts", "custom"]
UNRELIABLE = "无法给出可靠估值区间"


def dval(x):
    """驱动值可写数字或 {"value":…, "anchor":…, "pctile":…, "evidence":…}。"""
    return x.get("value") if isinstance(x, dict) else x


def wquantile(values, weights, q):
    """插值加权分位：按值排序，每个值的位置＝其累计权重区间的中点，线性插值；越界夹到端点。
    q=0.5 即插值版加权中位数（对正权重连续）。零权重点不参与。"""
    pts = sorted((v, w) for v, w in zip(values, weights) if w > 0)
    if not pts:
        return None
    tot = sum(w for _, w in pts)
    pos, cum = [], 0.0
    for v, w in pts:
        pos.append(((cum + w / 2) / tot, v))
        cum += w
    if q <= pos[0][0]:
        return pos[0][1]
    if q >= pos[-1][0]:
        return pos[-1][1]
    for (p0, v0), (p1, v1) in zip(pos, pos[1:]):
        if p0 <= q <= p1:
            return v0 if p1 == p0 else v0 + (v1 - v0) * (q - p0) / (p1 - p0)
    return pos[-1][1]


def composite_range(los, his, mids, weights):
    """L＝下沿插值加权中位数，H＝上沿插值加权中位数。两侧各自排序时极少数权重组合会出现 L>H
    （插值位置随排序跳动）；此时回退为按 mid 排序的同一组插值系数同时作用于 lo/hi，保证 L≤H。"""
    L, H = wquantile(los, weights, 0.5), wquantile(his, weights, 0.5)
    if L <= H + 1e-12:
        return L, H, False
    order = sorted((m, i) for i, m in enumerate(mids) if weights[i] > 0)
    tot = sum(weights[i] for _, i in order)
    pos, cum = [], 0.0
    for _, i in order:
        pos.append(((cum + weights[i] / 2) / tot, i))
        cum += weights[i]
    if 0.5 <= pos[0][0]:
        k = pos[0][1]
        return los[k], his[k], True
    if 0.5 >= pos[-1][0]:
        k = pos[-1][1]
        return los[k], his[k], True
    for (p0, a), (p1, b) in zip(pos, pos[1:]):
        if p0 <= 0.5 <= p1:
            t = 0.0 if p1 == p0 else (0.5 - p0) / (p1 - p0)
            return los[a] + (los[b] - los[a]) * t, his[a] + (his[b] - his[a]) * t, True


def quartiles(obs):
    q = statistics.quantiles(sorted(obs), n=4, method="inclusive")
    return q[0], q[1], q[2]


def growth_path(g1, g2, half_life, g_inf, n):
    """两段式：第 1 年 g1；第 2 年起从 g2 按半衰期衰减，归一到第 N 年恰好＝g∞。"""
    d = 0.5 ** (1.0 / half_life)
    dn = d ** (n - 2)
    path = [g1]
    for t in range(2, n + 1):
        path.append(g_inf + (g2 - g_inf) * (d ** (t - 2) - dn) / (1 - dn))
    return path


def fmt_ps(x):
    if x is None:
        return "n/a"
    a = abs(x)
    return f"{x:,.3f}" if a < 10 else (f"{x:,.2f}" if a < 1000 else f"{x:,.1f}")


# ---------- 事实层 ----------

def load_rules():
    with open(RULES_PATH, encoding="utf-8") as f:
        return json.load(f)["industries"]


def resolve_facts(inputs, cfg):
    facts = inputs.get("facts") or die("inputs.json 缺少 facts")
    F = {k: v.get("value") for k, v in facts.items() if isinstance(v, dict) and "value" in v}
    F["_s2c_clean"] = bool(facts.get("sales_to_capital_hist", {}).get("clean"))
    F["_history"] = facts.get("history") or []
    F["_fx_key"] = facts.get("fx", {}).get("key")
    log = []
    for ov in cfg.get("overrides") or []:
        for k in ("field", "value", "reason", "source"):
            need(ov, k, "overrides[]")
        if ov["field"] not in F:
            die(f"override 字段 `{ov['field']}` 不在 inputs.json facts 中")
        log.append((ov["field"], F[ov["field"]], ov["value"], ov["reason"], ov["source"]))
        F[ov["field"]] = ov["value"]
    ov_fields = {o[0] for o in log}
    if ({"base_revenue", "base_operating_income"} & ov_fields) and "op_margin_reported" not in ov_fields:
        if F.get("base_operating_income") is not None and F.get("base_revenue"):
            F["op_margin_reported"] = F["base_operating_income"] / F["base_revenue"]
    for k in ("price", "shares_outstanding", "net_debt", "base_revenue", "fx"):
        if F.get(k) is None:
            die(f"事实 `{k}` 缺失（inputs.json 或 override）")
    if F["shares_outstanding"] <= 0 or F["fx"] <= 0 or F["base_revenue"] <= 0:
        die("shares_outstanding / fx / base_revenue 必须为正")
    basis = inputs.get("basis") or {}
    pf, bc = cfg.get("pro_forma"), cfg.get("basis_confirmed")
    if basis.get("basis_flag") and not (pf or bc):
        die(f"basis_flag 未处理：{basis.get('reason')}——须写 pro_forma（现金增减＋股本口径＋ledger 出处）"
            "或 basis_confirmed（无期后事件＋出处）")
    if pf:
        for k in ("cash_delta", "shares_basis", "source"):
            need(pf, k, "pro_forma")
    if bc:
        need(bc, "source", "basis_confirmed")
    F["_pf_cash"] = float(pf["cash_delta"]) if pf else 0.0
    return F, log


def build_wacc(cfg):
    w = need(cfg, "wacc", "顶层")
    if isinstance(w, (int, float)):
        rf = cfg.get("rf")
        info = {"wacc": float(w), "rf": rf, "coe": cfg.get("coe"), "detail": "直接给定"}
    else:
        rf, beta, erp = need(w, "rf", "wacc"), need(w, "beta", "wacc"), need(w, "erp", "wacc")
        crp = w.get("crp", 0.0) * w.get("crp_lambda", 1.0)
        coe = rf + beta * erp + crp
        dw = w.get("target_debt_weight", 0.0)
        kd = w.get("kd_after_tax")
        if kd is None:
            kd = w.get("kd_pre_tax", 0.0) * (1 - w.get("marginal_tax", 0.0))
        wacc = (1 - dw) * coe + dw * kd
        info = {"wacc": wacc, "rf": rf, "coe": coe,
                "detail": f"CoE = rf {rf:.2%} + β {beta:.2f}×ERP {erp:.2%}" + (f" + CRP {crp:.2%}" if crp else "")
                          + f" = {coe:.2%}；Kd(税后) {kd:.2%}；D/(D+E) {dw:.1%} → WACC {wacc:.2%}"}
    if info["rf"] is None:
        die("需提供 rf（wacc 块或顶层 rf），用于校验永续 g ≤ rf")
    if not (0 < info["wacc"] < 0.5):
        die(f"wacc={info['wacc']} 不在合理范围 (0, 0.5)")
    return info


def build_terminal(cfg, rf):
    t = cfg.get("terminal") or {}
    g = t.get("g", min(rf, 0.025))
    if g > rf + 1e-12:
        die(f"永续 g({g:.2%}) > rf({rf:.2%})——硬错（valuation-assumptions.md §1）")
    if g < -0.02:
        die(f"永续 g({g:.2%}) 低于 −2%，不在支持范围")
    return {"g": g, "roiic": t.get("roiic"), "roiic_reason": t.get("roiic_reason")}


# ---------- 驱动模型 ----------

DRIVER_DEFAULTS = {"half_life": 3.0, "horizon": 10, "margin_years": 5, "nol_open": 0.0,
                   "dilution": 0.0, "allow_capital_release": False}


def scenario_drivers(cfg, sc, F):
    name = sc.get("name", "?")
    d = dict(DRIVER_DEFAULTS)
    common = cfg.get("drivers") or {}
    for src in (common, sc):
        for k, v in src.items():
            if k not in ("name", "prob", "evidence", "evidence_source", "rationale", "note", "basis"):
                d[k] = dval(v)
    if "revenue" in sc or "fcf_margin" in sc or "fcf" in sc:
        die(f"情景 {name}: schema 3 禁止手填 revenue/fcf_margin/fcf 路径——只给驱动参数")
    for k in ("g1", "margin_target"):
        if d.get(k) is None:
            die(f"情景 {name}: 缺少驱动 `{k}`")
    if d.get("g2") is None:
        d["g2"] = d["g1"]
    if d.get("m1") is None:
        if F.get("op_margin_reported") is None:
            die(f"情景 {name}: 事实层无报告口径经营利润率，须显式给 m1")
        adj = common.get("m1_adjustments") or []
        oi = F.get("base_operating_income")
        if adj:
            if oi is None:
                die("m1_adjustments 需要事实 base_operating_income")
            for a in adj:
                for k in ("item", "amount", "source"):
                    need(a, k, "drivers.m1_adjustments[]")
            d["m1"] = (oi + sum(a["amount"] for a in adj)) / F["base_revenue"]
        else:
            d["m1"] = F["op_margin_reported"]
    if d.get("sales_to_capital") is None:
        if not F["_s2c_clean"] or not F.get("sales_to_capital_hist"):
            die(f"情景 {name}: 历史 Rev/IC 不干净（inputs.sales_to_capital_hist.clean=false），"
                "sales_to_capital 必须显式给值并注明来源")
        d["sales_to_capital"] = F["sales_to_capital_hist"]
    if d.get("tax") is None:
        if F.get("tax_effective") is not None:
            d["tax"] = F["tax_effective"]
        elif cfg.get("market") in STATUTORY_TAX:
            d["tax"] = STATUTORY_TAX[cfg["market"]]
        else:
            die("有效税率为 null：须给 drivers.tax，或顶层 market ∈ us/hk/cn 以用法定税率")
    if not (0.5 <= d["half_life"] <= 5):
        die(f"情景 {name}: half_life={d['half_life']} 超出 [0.5, 5]")
    d["horizon"] = int(d["horizon"])
    if not (3 <= d["horizon"] <= 30):
        die(f"情景 {name}: horizon={d['horizon']} 超出 [3, 30]")
    if d["sales_to_capital"] <= 0:
        die(f"情景 {name}: sales_to_capital 必须为正")
    if d["margin_years"] < 1:
        die(f"情景 {name}: margin_years 必须 ≥1")
    if not (0 <= d["tax"] < 0.6):
        die(f"情景 {name}: tax={d['tax']} 不合理")
    return d


def project(d, F, wacc, term, roiic=None):
    """驱动式 FCFF：逐年路径 → EV / 每股 / EVA 分解。金额单位同 inputs（千元报表币）。"""
    n, g_inf = d["horizon"], term["g"]
    roiic = roiic if roiic is not None else (term["roiic"] if term["roiic"] is not None else wacc)
    if wacc <= g_inf:
        die(f"WACC({wacc}) 必须大于永续 g({g_inf})")
    if roiic <= 0:
        die("terminal.roiic 必须为正")
    gs = growth_path(d["g1"], d["g2"], d["half_life"], g_inf, n)
    ic0 = F.get("invested_capital") or 0.0
    release_floor = -max(ic0, 0.0)
    rev_prev, nol, cum_reinv, ic = F["base_revenue"], d["nol_open"], 0.0, ic0
    rows = []
    for t in range(1, n + 1):
        rev = rev_prev * (1 + gs[t - 1])
        m = d["m1"] + (d["margin_target"] - d["m1"]) * min((t - 1) / d["margin_years"], 1.0)
        ebit = rev * m
        if ebit <= 0:
            nol += -ebit
            tax = 0.0
        else:
            use = min(nol, ebit)
            nol -= use
            tax = (ebit - use) * d["tax"]
        nopat = ebit - tax
        reinv = (rev - rev_prev) / d["sales_to_capital"]
        if not d["allow_capital_release"]:
            reinv = max(0.0, reinv)
        elif cum_reinv + reinv < release_floor:
            reinv = release_floor - cum_reinv
        cum_reinv += reinv
        ic_prev, ic = ic, ic + reinv
        rows.append({"t": t, "g": gs[t - 1], "rev": rev, "margin": m, "ebit": ebit, "nopat": nopat,
                     "reinv": reinv, "fcff": nopat - reinv, "ic_open": ic_prev,
                     "roic": nopat / ic_prev if ic_prev > 0 else None, "eva": nopat - wacc * ic_prev})
        rev_prev = rev
    last = rows[-1]
    ebit_n1 = last["rev"] * (1 + g_inf) * last["margin"]
    nopat_n1 = ebit_n1 * (1 - d["tax"]) if ebit_n1 > 0 else ebit_n1
    terminal_loss = nopat_n1 <= 0
    tv = nopat_n1 / (wacc - g_inf) if terminal_loss else nopat_n1 * (1 - g_inf / roiic) / (wacc - g_inf)
    fcfs = [r["fcff"] for r in rows]
    pv = _pv(fcfs, wacc)
    disc_n = (1 + wacc) ** n
    ev = pv + tv / disc_n
    equity = ev - F["net_debt"] + F["_pf_cash"]
    shares_end = F["shares_outstanding"] * (1 + d["dilution"]) ** n
    per_share = equity * 1000.0 / F["fx"] / shares_end
    pv_eva = sum(r["eva"] / (1 + wacc) ** r["t"] for r in rows)
    cont = (tv - ic) / disc_n
    ev_eva = ic0 + pv_eva + cont
    if abs(ev_eva - ev) > 1e-6 * max(1.0, abs(ev)):
        die(f"EVA 分解与 DCF 不恒等（{ev_eva} vs {ev}）——实现错误")
    rev0 = F["base_revenue"]
    cagr = lambda k: (rows[k - 1]["rev"] / rev0) ** (1 / k) - 1 if k <= n and rows[k - 1]["rev"] > 0 else None
    return {"rows": rows, "ev": ev, "pv_explicit": pv, "tv": tv, "tv_share": (tv / disc_n) / ev if ev else float("nan"),
            "nopat_n1": nopat_n1, "terminal_loss": terminal_loss, "roiic": roiic,
            "exit_multiple": tv / nopat_n1 if nopat_n1 else float("nan"),
            "equity": equity, "per_share": per_share, "shares_end": shares_end,
            "cagr5": cagr(5), "cagr10": cagr(10), "ic0": ic0, "ic_n": ic,
            "eva": {"ic0": ic0, "pv_eva": pv_eva, "continuing": cont, "ev": ev_eva},
            "terminal_rr": (g_inf / roiic) if not terminal_loss else None}


# ---------- 各方法 [lo, mid, hi] ----------

def per_share(equity, F, shares=None):
    return equity * 1000.0 / F["fx"] / (shares or F["shares_outstanding"])


def run_scenarios(cfg, F, wacc, term, pert):
    scs = cfg.get("scenarios") or []
    if not scs:
        return None
    names = [s.get("name") for s in scs]
    if "base" not in names:
        die("schema 3 情景须含 name=base")
    probs = {s["name"]: float(need(s, "prob", f"情景 {s.get('name')}")) for s in scs}
    if pert.get("prob_shift"):
        src, dst, amt = pert["prob_shift"]
        if src in probs and dst in probs:
            probs[src] -= amt
            probs[dst] += amt
    if abs(sum(probs.values()) - 1.0) > 1e-6:
        die(f"情景概率和 = {sum(probs.values()):.4f} ≠ 1")
    out = []
    for s in scs:
        d = scenario_drivers(cfg, s, F)
        if pert.get("s2c_mult"):
            d["sales_to_capital"] *= pert["s2c_mult"]
        if pert.get("margin_shift"):
            d["margin_target"] += pert["margin_shift"]
        sroiic = dval(s.get("roiic")) if s.get("roiic") is not None else None
        r = project(d, F, wacc, term, roiic=sroiic)
        out.append({"name": s["name"], "prob": probs[s["name"]], "drivers": d, "res": r, "cfg": s})
    return out


def dcf_method(scen):
    vals = [max(s["res"]["per_share"], 0.0) for s in scen]
    probs = [s["prob"] for s in scen]
    base = next(s for s in scen if s["name"] == "base")
    m = {"id": "dcf", "lo": wquantile(vals, probs, 0.25), "mid": sum(p * v for p, v in zip(probs, vals)),
         "hi": wquantile(vals, probs, 0.75), "gate": None, "flags": []}
    if base["res"]["per_share"] <= 0:
        m["gate"] = "基准情景每股 ≤0（经营价值为负）"
        m["flags"].append("经营价值为负")
    return m


def epv_method(c, F, wacc, tax):
    om = F.get("op_margin_median_5y")
    if om is None:
        return {"id": "epv", "gate": "无近 5 年经营利润率中位数", "lo": None, "mid": None, "hi": None}
    adj = c.get("adjustments") or []
    for a in adj:
        for k in ("item", "amount", "source"):
            need(a, k, "methods.epv.adjustments[]")
    ebit = om * F["base_revenue"] + sum(a["amount"] for a in adj)
    nopat = ebit * (1 - tax) if ebit > 0 else ebit
    m = {"id": "epv", "nopat": nopat, "ebit": ebit, "om": om, "adjustments": adj, "gate": None}
    if nopat <= 0:
        m.update(gate="常态化 NOPAT ≤0", lo=None, mid=None, hi=None)
        return m
    ps = lambda w: per_share(nopat / w - F["net_debt"] + F["_pf_cash"], F)
    m.update(lo=ps(wacc + 0.01), mid=ps(wacc), hi=ps(max(wacc - 0.01, 0.005)))
    return m


METRIC_FACTS = {"revenue": "base_revenue", "book_equity": "book_equity", "net_income": "net_income_ttm",
                "ebitda": "ebitda_fy", "ebit": "base_operating_income"}


def multiples_method(c, F):
    items = c.get("items") or []
    rows = []
    mcap = F["price"] * F["shares_outstanding"] * F["fx"] / 1000.0
    for it in items:
        name = need(it, "name", "multiples.items[]")
        basis = it.get("basis", "equity")
        if basis not in ("equity", "ev"):
            die(f"倍数 {name}: basis 须为 equity/ev")
        if "metric_value" in it:
            need(it, "metric_source", f"倍数 {name}")
            metric = it["metric_value"]
        else:
            key = need(it, "metric", f"倍数 {name}")
            if key not in METRIC_FACTS:
                die(f"倍数 {name}: metric 须为 {sorted(METRIC_FACTS)} 或显式 metric_value")
            metric = F.get(METRIC_FACTS[key])
        obs_src = it.get("peers") or it.get("history") or []
        if it.get("band"):
            die(f"倍数 {name}: 不接受经验带（band），须给逐家同业原始倍数或自身历史序列")
        for o in obs_src:
            need(o, "value", f"倍数 {name} 观测")
            if it.get("peers"):
                need(o, "source", f"倍数 {name} 同业 {o.get('name')}")
        obs = [float(o["value"]) for o in obs_src]
        row = {"name": name, "basis": basis, "metric": metric, "n": len(obs), "gate": None,
               "kind": "同业" if it.get("peers") else "自身历史"}
        if metric is None or metric <= 0:
            row["gate"] = f"指标 ≤0 或缺失（{metric}）"
        elif len(obs) < 3:
            row["gate"] = f"观测 {len(obs)} 个 <3（证据不足）"
        else:
            q = quartiles(obs)
            row["q"] = q
            bridge = (-F["net_debt"] + F["_pf_cash"]) if basis == "ev" else 0.0
            row["lo"], row["mid"], row["hi"] = (max(per_share(x * metric + bridge, F), 0.0) for x in q)
        row["market"] = ((mcap + (F["net_debt"] - F["_pf_cash"] if basis == "ev" else 0.0)) / metric
                         if metric else None)
        rows.append(row)
    ok = [r for r in rows if r["gate"] is None]
    m = {"id": "multiples", "items": rows, "gate": None if ok else "无有效倍数（全部被闸门剔除）"}
    if ok:
        eq = [1.0] * len(ok)
        m.update(lo=wquantile([r["lo"] for r in ok], eq, 0.5), mid=wquantile([r["mid"] for r in ok], eq, 0.5),
                 hi=wquantile([r["hi"] for r in ok], eq, 0.5))
    else:
        m.update(lo=None, mid=None, hi=None)
    return m


def _triplet(x, ctx):
    lo, hi = need(x, "lo", ctx), need(x, "hi", ctx)
    return lo, x.get("mid", (lo + hi) / 2), hi


def sop_method(c, F):
    kind = c.get("kind", "sotp")
    if kind not in ("sotp", "nav", "asset_ladder", "liquidation"):
        die(f"sum_of_parts.kind 非法：{kind}")
    tot = [0.0, 0.0, 0.0]
    parts = []
    for p in need(c, "parts", "sum_of_parts"):
        nm, tp = need(p, "name", "sum_of_parts.parts[]"), p.get("type", "value")
        need(p, "source", f"部件 {nm}")
        if tp == "value":
            v = _triplet(p, f"部件 {nm}")
        elif tp == "metric_x_multiple":
            mv = need(p, "metric_value", f"部件 {nm}")
            v = tuple(mv * x for x in _triplet(need(p, "multiple", f"部件 {nm}"), f"部件 {nm}.multiple"))
        elif tp == "metric_div_rate":
            mv = need(p, "metric_value", f"部件 {nm}")
            r_lo, r_mid, r_hi = _triplet(need(p, "rate", f"部件 {nm}"), f"部件 {nm}.rate")
            if min(r_lo, r_mid, r_hi) <= 0:
                die(f"部件 {nm}: rate 必须为正")
            v = (mv / r_hi, mv / r_mid, mv / r_lo)
        else:
            die(f"部件 {nm}: type 须为 value / metric_x_multiple / metric_div_rate")
        parts.append((nm, tp, v))
        tot = [a + b for a, b in zip(tot, v)]
    ded = sum(need(x, "value", "sum_of_parts.deductions[]") for x in c.get("deductions") or [])
    deduct_nd = c.get("deduct_net_debt", kind in ("sotp", "nav"))
    bridge = -ded - ((F["net_debt"] - F["_pf_cash"]) if deduct_nd else 0.0)
    lo, mid, hi = (max(per_share(x + bridge, F), 0.0) for x in tot)
    m = {"id": "sum_of_parts", "kind": kind, "parts": parts, "deductions": ded, "deduct_net_debt": deduct_nd,
         "lo": lo, "mid": mid, "hi": hi, "gate": None}
    rp = c.get("realization_path")
    if kind in ("asset_ladder", "liquidation") and not (rp and rp.get("evidence") and rp.get("source")):
        m["gate"] = "无变现路径公告证据 → 仅作资产底价信号（少数股东不可实现）"
        m["signal_only"] = True
    return m


def custom_methods(cs, workdir):
    out = []
    for c in cs or []:
        nm = need(c, "name", "custom[]")
        script = need(c, "script", f"custom {nm}").replace("\\", "/")
        if not script.startswith("valuation/calc/") or not script.endswith(".py"):
            die(f"custom {nm}: script 必须位于 valuation/calc/*.py（计算出口条款）")
        outp = c.get("output", script[:-3] + ".txt")
        m = {"id": f"custom:{nm}", "script": script, "gate": None, "lo": None, "mid": None, "hi": None}
        if workdir is None:
            m.update(lo=need(c, "lo", f"custom {nm}"), mid=need(c, "mid", f"custom {nm}"), hi=need(c, "hi", f"custom {nm}"))
        else:
            if not os.path.isfile(os.path.join(workdir, script)):
                die(f"custom {nm}: 找不到 {script}")
            path = os.path.join(workdir, outp)
            if not os.path.isfile(path):
                die(f"custom {nm}: 找不到输出 {outp}（先运行 {script}）")
            with open(path, encoding="utf-8") as f:
                hit = re.search(r"RESULT\s+lo=([-\d.eE]+)\s+mid=([-\d.eE]+)\s+hi=([-\d.eE]+)", f.read())
            if not hit:
                die(f"custom {nm}: {outp} 缺少 `RESULT lo=… mid=… hi=…` 行（每股，价格币）")
            m.update(lo=float(hit.group(1)), mid=float(hit.group(2)), hi=float(hit.group(3)))
        m.update(lo=max(m["lo"], 0.0), mid=max(m["mid"], 0.0), hi=max(m["hi"], 0.0))
        out.append(m)
    return out


# ---------- 权重与合成 ----------

def industry_valuation(cfg, inputs):
    ind = cfg.get("industry") or inputs.get("industry")
    rules = load_rules()
    v = (rules.get(ind) or {}).get("valuation")
    if v is None:
        if not (cfg.get("primary_method") and isinstance(cfg.get("fcff_applicable"), bool)):
            die(f"行业 {ind!r} 不在 industry-rules.json（或无 valuation 块）：须显式给 primary_method 与 fcff_applicable")
        return ind, cfg["primary_method"], cfg["fcff_applicable"], [cfg["primary_method"]]
    allowed = v["primary"]
    primary = cfg.get("primary_method", allowed[0])
    if primary not in allowed:
        die(f"primary_method={primary} 不在行业 {ind} 的可选主方法 {allowed} 中")
    fa = v["fcff_applicable"]
    if fa == "subtype":
        if not isinstance(cfg.get("fcff_applicable"), bool) or not cfg.get("fcff_applicable_reason"):
            die(f"行业 {ind} 按子类型判定 FCFF 适用性：须给 fcff_applicable(bool)＋fcff_applicable_reason")
        fa = cfg["fcff_applicable"]
    return ind, primary, fa, allowed


def assign_weights(methods, primary, adjust, pert_shift=0.0):
    app = [m for m in methods if m["gate"] is None]
    if not app:
        return
    is_primary = lambda m: m["id"] == primary or (primary == "custom" and m["id"].startswith("custom:")
                                                  and m is next(x for x in app if x["id"].startswith("custom:")))
    prim = [m for m in app if is_primary(m)]
    if prim and len(app) > 1:
        for m in app:
            m["weight"] = PRIMARY_WEIGHT if m is prim[0] else (1 - PRIMARY_WEIGHT) / (len(app) - 1)
    else:
        for m in app:
            m["weight"] = 1.0 / len(app)
    for mid, dlt in (adjust or {}).items():
        if abs(dlt) > ADJ_LIMIT + 1e-9:
            die(f"weights.adjust[{mid}]={dlt:+.2f} 超过 ±{ADJ_LIMIT}")
        tgt = next((m for m in app if m["id"] == mid), None)
        if tgt is not None:
            tgt["weight"] += dlt
    if pert_shift and prim and len(app) > 1:
        prim[0]["weight"] += pert_shift
    for m in app:
        if m["weight"] < -1e-12:
            die(f"方法 {m['id']} 调整后权重为负")
        m["weight"] = max(m["weight"], 0.0)
    tot = sum(m["weight"] for m in app)
    for m in app:
        m["weight"] /= tot
    over = [m for m in app if m["id"].startswith("custom:") and not is_primary(m) and m["weight"] > CUSTOM_CAP]
    rest = [m for m in app if m not in over]
    if over and rest:
        excess = sum(m["weight"] - CUSTOM_CAP for m in over)
        for m in over:
            m["weight"] = CUSTOM_CAP
            m["capped"] = True
        rt = sum(m["weight"] for m in rest) or 1.0
        for m in rest:
            m["weight"] += excess * m["weight"] / rt


def synthesize(methods, price):
    app = [m for m in methods if m["gate"] is None and m.get("weight", 0) > 0]
    res = {"L": None, "H": None, "label": None, "reason": None, "flags": [], "intersection": None,
           "envelope": None, "divergence": None}
    if not app:
        res["reason"] = "全部方法被闸门剔除"
        return res
    w = [m["weight"] for m in app]
    L, H, fallback = composite_range([m["lo"] for m in app], [m["hi"] for m in app], [m["mid"] for m in app], w)
    res.update(L=L, H=H)
    if fallback:
        res["flags"].append("合成口径回退（下沿中位数>上沿中位数，改按 mid 排序同系数插值）")
    lo_max, hi_min = max(m["lo"] for m in app), min(m["hi"] for m in app)
    res["intersection"] = (lo_max, hi_min) if lo_max <= hi_min else None
    res["envelope"] = (min(m["lo"] for m in app), max(m["hi"] for m in app))
    mids = [m["mid"] for m in app]
    res["divergence"] = (max(mids) / min(mids)) if min(mids) > 0 else float("inf")
    if len(app) == 1:
        res["flags"].append("单一方法")
    elif res["intersection"] is None or res["divergence"] > 2:
        res["flags"].append("方法分歧")
    if any("经营价值为负" in (m.get("flags") or []) for m in methods):
        res["flags"].append("经营价值为负")
    if H <= 0:
        res["reason"] = "合成上沿 H ≤0"
        return res
    res["label"] = calibrate(price, L, H)
    return res


# ---------- 主评估（纯函数；稳健性与 checker 复用） ----------

def evaluate(inputs, cfg, pert=None, workdir=None):
    if cfg.get("schema") != 3:
        die("evaluate() 仅支持 schema 3")
    pert = pert or {}
    F, ov_log = resolve_facts(inputs, cfg)
    winfo = build_wacc(cfg)
    wacc = winfo["wacc"] + pert.get("wacc_shift", 0.0)
    term = build_terminal(cfg, winfo["rf"])
    if term["roiic"] is not None and term["roiic"] > winfo["wacc"] + 1e-12:
        if not term["roiic_reason"]:
            die("terminal.roiic > WACC 须写 roiic_reason（ch3 护城河「宽」＋CAP 论证）")
        if term["roiic"] > winfo["wacc"] + ROIIC_CAP_SPREAD + 1e-12:
            die(f"terminal.roiic 上限 WACC+{ROIIC_CAP_SPREAD:.0%}")
    ind, primary, fcff_ok, allowed = industry_valuation(cfg, inputs)
    mcfg = cfg.get("methods") or {}
    methods, warnings = [], []

    scen = run_scenarios(cfg, F, wacc, term, pert)
    if scen:
        m = dcf_method(scen)
        if not fcff_ok:
            m["gate"] = "行业 fcff_applicable=false"
        methods.append(m)
    base = next((s for s in scen if s["name"] == "base"), None) if scen else None
    tax = base["drivers"]["tax"] if base else (cfg.get("drivers") or {}).get("tax") or F.get("tax_effective") or 0.0
    if mcfg.get("epv", {}) is not False:
        m = epv_method(mcfg.get("epv") or {}, F, wacc, tax)
        if not fcff_ok:
            m["gate"] = "行业 fcff_applicable=false"
        methods.append(m)
    if mcfg.get("multiples"):
        methods.append(multiples_method(mcfg["multiples"], F))
    if mcfg.get("sum_of_parts"):
        methods.append(sop_method(mcfg["sum_of_parts"], F))
    methods.extend(custom_methods(mcfg.get("custom"), workdir))

    sd = cfg.get("structure_discount")
    if sd:
        pct = need(sd, "pct", "structure_discount")
        need(sd, "basis", "structure_discount")
        if not (0 <= pct < 1):
            die("structure_discount.pct 须在 [0, 1)")
        for m in methods:
            for k in ("lo", "mid", "hi"):
                if m.get(k) is not None:
                    m[k] *= (1 - pct)
    for m in methods:
        if m["gate"] is None:
            for k in ("lo", "mid", "hi"):
                m[k] = max(m[k], 0.0)
            if m["lo"] > m["hi"]:
                m["lo"], m["hi"] = m["hi"], m["lo"]
    wcfg = cfg.get("weights") or {}
    adjust = wcfg.get("adjust") or {}
    for k in adjust:
        if not (wcfg.get("reasons") or {}).get(k):
            die(f"weights.adjust[{k}] 须在 weights.reasons 写理由")
    assign_weights(methods, primary, adjust, pert.get("primary_shift", 0.0))
    syn = synthesize(methods, F["price"])
    if scen:
        warnings.extend(prob_warnings(scen, cfg))
        warnings.extend(driver_warnings(scen, F))
    return {"F": F, "overrides": ov_log, "wacc": wacc, "winfo": winfo, "term": term, "industry": ind,
            "primary": primary, "allowed": allowed, "fcff_ok": fcff_ok, "scen": scen, "methods": methods,
            "syn": syn, "warnings": warnings, "tax": tax}


def prob_warnings(scen, cfg):
    w = []
    for s in scen:
        p, ev = s["prob"], str(s["cfg"].get("evidence") or "").strip()
        if p < PROB_FLOOR - 1e-9:
            w.append(f"PROB_FLOOR: 情景 {s['name']} 概率 {p:.2f} < {PROB_FLOOR}")
        if s["name"] != "base":
            if ev == "中强" and p < 0.30 - 1e-9:
                w.append(f"PROB_EVIDENCE: 非基准情景 {s['name']} 证据中强但概率 {p:.2f} < 0.30")
            if ev == "强" and p < 0.40 - 1e-9:
                w.append(f"PROB_EVIDENCE: 非基准情景 {s['name']} 证据强但概率 {p:.2f} < 0.40")
        elif ev == "弱" and p > 0.40 + 1e-9:
            w.append(f"PROB_EVIDENCE: 基准情景证据弱但概率 {p:.2f} > 0.40")
        dflt = PROB_DEFAULT.get(s["name"])
        if dflt is not None and abs(p - dflt) > 1e-9 and not s["cfg"].get("prob_reason"):
            w.append(f"PROB_REASON: 情景 {s['name']} 概率偏离默认 {dflt} 未写 prob_reason")
    return w


def driver_warnings(scen, F):
    w = []
    hist = F["_history"]
    yoys = sorted(h["yoy"] for h in hist if h.get("yoy") is not None)
    oms = sorted(h["op_margin"] for h in hist if h.get("op_margin") is not None)
    p30 = lambda xs: wquantile(xs, [1.0] * len(xs), 0.30) if len(xs) >= 3 else None
    for s in scen:
        d, c, r = s["drivers"], s["cfg"], s["res"]
        if r["cagr10"] is not None and r["cagr10"] > 0.30 and not (c.get("extreme_growth_reason")):
            die(f"情景 {s['name']}: 10 年营收 CAGR {r['cagr10']:.0%} >30%，须写 extreme_growth_reason")
        if d["half_life"] > 4 and not c.get("half_life_reason"):
            w.append(f"DRIVER_REASON: 情景 {s['name']} half_life>4 未写 half_life_reason（ch3 护城河宽＋领先指标）")
        m1_raw = c.get("m1", None)
        if (m1_raw is not None and F.get("op_margin_reported") is not None
                and abs(d["m1"] - F["op_margin_reported"]) > 0.02 and not isinstance(m1_raw, dict)):
            w.append(f"DRIVER_M1: 情景 {s['name']} m1 {d['m1']:.1%} 偏离报告口径 {F['op_margin_reported']:.1%} >2pp，"
                     "须写 {value, anchor, evidence} 或用 drivers.m1_adjustments 逐项列常态化调整")
        g1 = c.get("g1")
        if isinstance(g1, dict) and g1.get("anchor") is not None and s["name"] == "base":
            if abs(g1["value"] - g1["anchor"]) > 0.05 and not g1.get("reason"):
                w.append(f"DRIVER_ANCHOR: 基准 g1 偏离锚 {g1['value'] - g1['anchor']:+.1%} >5pp 未写结构性理由")
        if s["name"] == "bear":
            if p30(yoys) is not None and d["g1"] > p30(yoys) + 1e-9:
                w.append(f"DRIVER_BEAR: 熊 g1 {d['g1']:.1%} > 自身历史同比 P30 {p30(yoys):.1%}")
            if p30(oms) is not None and d["margin_target"] > p30(oms) + 1e-9:
                w.append(f"DRIVER_BEAR: 熊 margin_target {d['margin_target']:.1%} > 自身历史 P30 {p30(oms):.1%}")
        if oms and d["margin_target"] > max(oms) + 1e-9 and not c.get("margin_reason"):
            w.append(f"DRIVER_REASON: 情景 {s['name']} margin_target {d['margin_target']:.1%} 高于自身历史最高 "
                     f"{max(oms):.1%}，须写 margin_reason（同业达成年数与规模）")
        hi_roic = [x["roic"] for x in r["rows"] if x["roic"] is not None and x["roic"] > 0.5]
        if hi_roic:
            w.append(f"DRIVER_ROIC: 情景 {s['name']} 路径隐含 ROIC 最高 {max(hi_roic):.0%} >50%（检查 sales_to_capital）")
    return w


# ---------- 稳健性 / 龙卷风 / MC ----------

def robustness(inputs, cfg, base_ev, workdir):
    names = [s["name"] for s in cfg.get("scenarios") or []]
    perts = []
    for dst in ("bear", "bull"):
        if "base" in names and dst in names:
            perts.append((f"概率：基准 −0.15 → {dst}", {"prob_shift": ("base", dst, 0.15)}))
    if sum(1 for m in base_ev["methods"] if m["gate"] is None) > 1:
        perts += [("主方法权重 +0.1", {"primary_shift": 0.1}), ("主方法权重 −0.1", {"primary_shift": -0.1})]
    perts += [("WACC +1pp", {"wacc_shift": 0.01}), ("WACC −1pp", {"wacc_shift": -0.01}),
              ("S2C ×1.3", {"s2c_mult": 1.3}), ("S2C ×0.7", {"s2c_mult": 0.7}),
              ("margin_target +2pp", {"margin_shift": 0.02}), ("margin_target −2pp", {"margin_shift": -0.02})]
    rows, base_label = [], base_ev["syn"]["label"]
    for name, p in perts:
        try:
            ev = evaluate(inputs, cfg, pert=p, workdir=workdir)
            syn = ev["syn"]
            if syn["label"] is None or base_label is None:
                status = "不适用"
            else:
                status = "翻转" if syn["label"] != base_label else "不变"
            rows.append((name, syn["L"], syn["H"], syn["label"] or UNRELIABLE, status))
        except ValueError as e:
            rows.append((name, None, None, f"不适用（{e}）", "不适用"))
    return rows


def tornado(base_s, F, wacc, term):
    d0 = base_s["drivers"]
    v0 = base_s["res"]["per_share"]
    sroiic = dval(base_s["cfg"].get("roiic")) if base_s["cfg"].get("roiic") is not None else None
    notches = [("g1 ±5pp", "g1", 0.05, "add"), ("half_life ±1", "half_life", 1.0, "add"),
               ("margin_target ±2pp", "margin_target", 0.02, "add"), ("m1 ±2pp", "m1", 0.02, "add"),
               ("margin_years ±2", "margin_years", 2, "add"), ("sales_to_capital ±30%", "sales_to_capital", 0.3, "mult"),
               ("tax ±5pp", "tax", 0.05, "add")]
    if abs(d0["g2"] - d0["g1"]) > 1e-12:
        notches.append(("g2 ±5pp", "g2", 0.05, "add"))
    out = []
    for label, k, step, mode in notches:
        vals = []
        for sgn in (-1, 1):
            d = dict(d0)
            d[k] = d[k] * (1 + sgn * step) if mode == "mult" else d[k] + sgn * step
            if k == "g1" and abs(d0["g2"] - d0["g1"]) < 1e-12:
                d["g2"] = d["g1"]
            if k == "half_life":
                d[k] = min(max(d[k], 0.5), 5.0)
            if k == "margin_years":
                d[k] = max(d[k], 1)
            if k == "tax":
                d[k] = min(max(d[k], 0.0), 0.59)
            vals.append(project(d, F, wacc, term, roiic=sroiic)["per_share"])
        out.append((label, vals[0], vals[1], abs(vals[1] - vals[0])))
    for label, dw, dg in (("WACC ±1pp", 0.01, 0.0), ("永续 g ±0.5pp", 0.0, 0.005)):
        vals = []
        for sgn in (-1, 1):
            t = dict(term)
            t["g"] = term["g"] + sgn * dg
            w = wacc + sgn * dw
            if w <= t["g"]:
                vals.append(float("nan"))
                continue
            vals.append(project(d0, F, w, t, roiic=sroiic)["per_share"])
        out.append((label, vals[0], vals[1], abs(vals[1] - vals[0]) if all(v == v for v in vals) else 0.0))
    out.sort(key=lambda x: -x[3])
    return v0, out


def montecarlo3(scen, F, wacc, term, mc):
    n, rng = int(mc.get("n", 2000)), random.Random(mc.get("seed", 42))
    keys = ["g1", "g2", "margin_target", "sales_to_capital", "half_life"]
    bands = []
    for i, s in enumerate(scen):
        b = {}
        for k in keys:
            x = s["drivers"][k]
            lo = (scen[i - 1]["drivers"][k] + x) / 2 if i > 0 else None
            hi = (scen[i + 1]["drivers"][k] + x) / 2 if i < len(scen) - 1 else None
            lo = lo if lo is not None else (x - (hi - x) if hi is not None else x)
            hi = hi if hi is not None else (x + (x - lo))
            lo, hi = min(lo, hi), max(lo, hi)
            if k == "half_life":
                lo, hi = max(lo, 0.5), min(hi, 5.0)
            if k == "sales_to_capital":
                lo = max(lo, 1e-3)
            b[k] = (lo, hi)
        bands.append(b)
    probs = [s["prob"] for s in scen]
    vals = []
    for _ in range(n):
        u, acc, i = rng.random(), 0.0, len(scen) - 1
        for j, p in enumerate(probs):
            acc += p
            if u < acc:
                i = j
                break
        d = dict(scen[i]["drivers"])
        for k in keys:
            d[k] = rng.uniform(*bands[i][k])
        w = rng.uniform(wacc - 0.005, wacc + 0.005)
        if w <= term["g"]:
            w = term["g"] + 0.005
        sroiic = dval(scen[i]["cfg"].get("roiic")) if scen[i]["cfg"].get("roiic") is not None else None
        vals.append(project(d, F, w, term, roiic=sroiic)["per_share"])
    vals.sort()
    q = lambda p: vals[min(int(p * n), n - 1)]
    return {"n": n, "q": {k: q(k) for k in (0.10, 0.25, 0.50, 0.75, 0.90)}, "mean": sum(vals) / n,
            "p_loss": sum(1 for v in vals if v < F["price"]) / n}


# ---------- 输出 ----------

def football(methods, syn, price):
    app = [m for m in methods if m.get("lo") is not None]
    if not app:
        return []
    xs = [price] + [m["lo"] for m in app] + [m["hi"] for m in app]
    if syn["L"] is not None:
        xs += [syn["L"], syn["H"]]
    lo_ax, hi_ax = min(xs + [0.0]), max(xs)
    width = 48
    pos = lambda x: int(round((x - lo_ax) / (hi_ax - lo_ax) * (width - 1))) if hi_ax > lo_ax else 0
    lines = []
    rows = [(m["id"] + ("" if m["gate"] is None else "（剔除）"), m["lo"], m["mid"], m["hi"]) for m in app]
    if syn["L"] is not None:
        rows.append(("综合 [L,H]", syn["L"], None, syn["H"]))
    for name, lo, mid, hi in rows:
        bar = [" "] * width
        for k in range(pos(lo), pos(hi) + 1):
            bar[k] = "─"
        if mid is not None:
            bar[pos(mid)] = "●"
        bar[pos(price)] = "┃" if bar[pos(price)] == " " else "╋"
        lines.append(f"  {name:<20} {''.join(bar)}  [{fmt_ps(lo)}, {fmt_ps(hi)}]")
    lines.append(f"  {'':<20} 轴 {fmt_ps(lo_ax)} … {fmt_ps(hi_ax)}；┃/╋＝现价 {fmt_ps(price)}；●＝mid")
    return lines


def sens_table(title, base_s, F, wacc, term, rows_spec, cols_spec):
    sroiic = dval(base_s["cfg"].get("roiic")) if base_s["cfg"].get("roiic") is not None else None
    (rname, rvals, rapply), (cname, cvals, capply) = rows_spec, cols_spec
    print(f"\n=== 敏感性：{title}（基准情景，每股） ===")
    print("  " + f"{rname}\\{cname}".ljust(16) + "".join(f"{c:>11.1%}" for c in cvals))
    for r in rvals:
        cells = []
        for c in cvals:
            d, w, t = dict(base_s["drivers"]), wacc, dict(term)
            w, t = rapply(d, w, t, r)
            w, t = capply(d, w, t, c)
            if w <= t["g"]:
                cells.append(f"{'n/a':>11}")
                continue
            if abs(d["g2"] - base_s["drivers"]["g2"]) < 1e-12 and abs(base_s["drivers"]["g2"] - base_s["drivers"]["g1"]) < 1e-12:
                d["g2"] = d["g1"]
            cells.append(f"{fmt_ps(project(d, F, w, t, roiic=sroiic)['per_share']):>11}")
        print(f"  {r:<16.1%}" + "".join(cells))


def run3(inputs, cfg, workdir=None):
    ev = evaluate(inputs, cfg, workdir=workdir)
    F, wacc, term, scen, methods, syn = ev["F"], ev["wacc"], ev["term"], ev["scen"], ev["methods"], ev["syn"]
    price = F["price"]
    print("=== 事实与覆盖（valuation/inputs.json） ===")
    print(f"  现价 {price:g} | 总股本 {F['shares_outstanding']:,.0f} | fx {F['fx']:g}（{F['_fx_key'] or '同币'}）"
          f" | 净债 {F['net_debt']:,.0f}（千元报表币） | 基期营收 {F['base_revenue']:,.0f}")
    for fld, old, new, why, src in ev["overrides"]:
        print(f"  ⚠ 事实覆盖 {fld}: {old} → {new}｜{why}｜{src}")
    if cfg.get("pro_forma"):
        pf = cfg["pro_forma"]
        print(f"  ⚠ pro_forma 现金 {pf['cash_delta']:+,.0f}｜股本口径 {pf['shares_basis']}｜{pf['source']}")
    elif cfg.get("basis_confirmed"):
        print(f"  基准日期确认：{cfg['basis_confirmed'].get('reason', '')}｜{cfg['basis_confirmed']['source']}")
    print(f"\n=== WACC === {ev['winfo']['detail']}" + (f"（稳健性扰动后 {wacc:.2%}）" if wacc != ev["winfo"]["wacc"] else ""))
    roiic_txt = "＝WACC" if term["roiic"] is None else f"{term['roiic']:.1%}"
    print(f"  永续 g {term['g']:.2%}（rf {ev['winfo']['rf']:.2%}）| 终值 ROIIC {roiic_txt}"
          f" | 行业 {ev['industry']} 主方法 {ev['primary']}（可选 {ev['allowed']}）| FCFF 适用 {ev['fcff_ok']}")

    base = next((s for s in scen if s["name"] == "base"), None) if scen else None
    if base:
        b = base["res"]
        interim = [r["fcff"] for r in b["rows"][:5]]
        steady = []
        for s in scen:
            if s["name"] in ("base", "bull"):
                r_ = s["res"]
                fm = s["drivers"]["margin_target"] * (1 - s["drivers"]["tax"]) * (1 - term["g"] / r_["roiic"])
                steady.append((s["name"], fm))
        print("\n=== 反向 DCF ===（interim＝基准情景前 5 年 FCFF；稳态 FCF 率＝margin_target×(1−t)×(1−g/ROIIC)）")
        pos_m = [fm for _, fm in steady if fm > 0]
        rv = reverse_dcf(price * F["fx"] / 1000.0, F["shares_outstanding"], F["net_debt"] - F["_pf_cash"],
                         wacc, term["g"], interim, pos_m or [1.0], F["base_revenue"])
        print(f"  市场 EV {rv['ev']:,.0f} | 建设期 FCFF 现值 {rv['pv_interim']:,.0f} | 现价隐含稳态首年 FCF {rv['fcf_required']:,.0f}")
        if rv["fcf_required"] <= 0:
            print("  现价已被建设期 FCFF 覆盖（隐含稳态 FCF ≤0）——反向 DCF 无增长解读")
        else:
            for (nm, fm) in steady:
                if fm <= 0:
                    print(f"    @{nm} 稳态 FCF 率 {fm:.1%} ≤0 → 不适用")
                    continue
                req = rv["fcf_required"] / fm
                cg = (req / F["base_revenue"]) ** (1 / len(interim)) - 1
                print(f"    @{nm} 稳态 FCF 率 {fm:.1%} → 需营收 {req:,.0f}，隐含 {len(interim)} 年营收 CAGR {cg:+.1%}"
                      f"（基准路径 5 年 CAGR {b['cagr5']:+.1%}）")
        epv = next((m for m in methods if m["id"] == "epv"), None)
        e_ps = per_share(epv["nopat"], F) if epv and epv.get("nopat") is not None else None
        print("\n=== PVGO ===")
        if e_ps is None or e_ps <= 0:
            print(f"  常态化每股 NOPAT {fmt_ps(e_ps)} ≤0 → PVGO 不适用")
        else:
            zg = e_ps / wacc
            print(f"  常态化每股 NOPAT {fmt_ps(e_ps)} ÷ WACC {wacc:.2%} = 零增长价值 {fmt_ps(zg)} → PVGO 占现价 {(price - zg) / price:.0%}")

        print("\n=== 情景路径（驱动式 FCFF，千元报表币） ===")
        for s in scen:
            d, r = s["drivers"], s["res"]
            print(f"  [{s['name']}] p={s['prob']:.2f} 证据 {s['cfg'].get('evidence', '—')} | g1 {d['g1']:.1%} g2 {d['g2']:.1%}"
                  f" 半衰期 {d['half_life']:g} N={d['horizon']} | m1 {d['m1']:.1%}→{d['margin_target']:.1%}/{d['margin_years']:g}年"
                  f" | S2C {d['sales_to_capital']:.2f} | t {d['tax']:.1%} | 稀释 {d['dilution']:.1%}")
            print("    年   增速     营收          利润率   NOPAT        再投资       FCFF         ROIC")
            for x in r["rows"]:
                print(f"    {x['t']:>2} {x['g']:>7.1%} {x['rev']:>13,.0f} {x['margin']:>7.1%} {x['nopat']:>12,.0f}"
                      f" {x['reinv']:>12,.0f} {x['fcff']:>12,.0f} {('n/a' if x['roic'] is None else format(x['roic'], '.1%')):>8}")
            tl = " ⚠终值期仍亏损（不计再投资项）" if r["terminal_loss"] else ""
            tvw = " ⚠TV>80%" if r["tv_share"] > 0.8 else ""
            c10 = "n/a" if r["cagr10"] is None else format(r["cagr10"], "+.1%")
            print(f"    EV {r['ev']:,.0f} | TV 占比 {r['tv_share']:.0%}{tvw} | 退出 EV/NOPAT {r['exit_multiple']:.1f}x"
                  f" | 5 年 CAGR {r['cagr5']:+.1%} 10 年 {c10} | 终值再投资率 "
                  f"{'n/a' if r['terminal_rr'] is None else format(r['terminal_rr'], '.0%')}{tl}")
            print(f"    → 每股 {fmt_ps(r['per_share'])}（期末股本 {r['shares_end']:,.0f}）")
        print("\n=== EVA 分解（与 DCF 恒等，不进区间） ===")
        for s in scen:
            e = s["res"]["eva"]
            print(f"  {s['name']:<6} IC₀ {e['ic0']:,.0f} + PV(EVA 显性期) {e['pv_eva']:,.0f} + PV(终值期 EVA) {e['continuing']:,.0f}"
                  f" = EV {e['ev']:,.0f} ≡ DCF ✓")

        sens_table("WACC × margin_target", base, F, wacc, term,
                   ("WACC", [wacc - 0.01, wacc, wacc + 0.01], lambda d, w, t, x: (x, t)),
                   ("margin", [base["drivers"]["margin_target"] + k for k in (-0.02, 0, 0.02)],
                    lambda d, w, t, x: (d.__setitem__("margin_target", x), (w, t))[1]))
        if base["drivers"]["g1"] >= 0.15 or cfg.get("sensitivity_growth"):
            def set_g1(d, w, t, x):
                d["g1"] = x
                return w, t
            sens_table("g1 × margin_target", base, F, wacc, term,
                       ("g1", [base["drivers"]["g1"] + k for k in (-0.05, 0, 0.05)], set_g1),
                       ("margin", [base["drivers"]["margin_target"] + k for k in (-0.02, 0, 0.02)],
                        lambda d, w, t, x: (d.__setitem__("margin_target", x), (w, t))[1]))
        if base["res"]["roiic"] != wacc:
            def set_g(d, w, t, x):
                t["g"] = x
                return w, t
            sens_table("WACC × g（ROIIC∞≠WACC）", base, F, wacc, term,
                       ("WACC", [wacc - 0.01, wacc, wacc + 0.01], lambda d, w, t, x: (x, t)),
                       ("g", [term["g"] + k for k in (-0.005, 0, 0.005)], set_g))
        else:
            print("  （ROIIC∞＝WACC：g 不影响价值，WACC×g 表省略）")

    for m in methods:
        if m["id"] == "epv":
            print("\n=== EPV ===")
            if m.get("om") is not None:
                adj = "".join(f"\n    调整 {a['item']} {a['amount']:+,.0f}｜{a['source']}" for a in m.get("adjustments") or [])
                print(f"  常态化 EBIT＝近 5 年经营利润率中位 {m['om']:.1%} × 基期营收 + 调整 = {m['ebit']:,.0f}"
                      f"；NOPAT {m['nopat']:,.0f}{adj}")
                be = F.get("book_equity")
                if be and m["nopat"] > 0:
                    ratio = (m["nopat"] / wacc - F["net_debt"]) / be
                    print(f"  EPV 权益 / 账面权益 = {ratio:.2f}x → {moat_verdict(ratio)}")
        if m["id"] == "multiples":
            print("\n=== 相对估值（倍数，脚本算分位；不接受经验带） ===")
            coe = ev["winfo"]["coe"] or wacc
            g = term["g"]
            ro = term["roiic"] or wacc
            print(f"  合理 P/E＝(1−g/ROIIC)/(r−g) = {(1 - g / ro) / (coe - g):.1f}x（r＝CoE {coe:.2%}）", end="")
            if F.get("net_income_ttm") and F.get("book_equity") and F["book_equity"] > 0:
                roe = F["net_income_ttm"] / F["book_equity"]
                print(f"｜合理 P/B＝(ROE−g)/(CoE−g) = {(roe - g) / (coe - g):.2f}x（ROE {roe:.1%}）")
            else:
                print()
            for it in m["items"]:
                mk = "n/a" if it["market"] is None else f"{it['market']:.2f}x"
                if it["gate"]:
                    print(f"  {it['name']}（{it['kind']} n={it['n']}）剔除：{it['gate']}｜市场 {mk}")
                else:
                    q = it["q"]
                    print(f"  {it['name']}（{it['kind']} n={it['n']}）P25/P50/P75 {q[0]:.2f}/{q[1]:.2f}/{q[2]:.2f}x"
                          f"｜市场 {mk} → 每股 [{fmt_ps(it['lo'])}, {fmt_ps(it['mid'])}, {fmt_ps(it['hi'])}]")
        if m["id"] == "sum_of_parts":
            print(f"\n=== 加总法（{m['kind']}） ===")
            for nm, tp, v in m["parts"]:
                print(f"  {nm:<18} {tp:<18} [{v[0]:,.0f}, {v[1]:,.0f}, {v[2]:,.0f}]")
            print(f"  扣减 {m['deductions']:,.0f}" + ("｜扣净债" if m["deduct_net_debt"] else "")
                  + f" → 每股 [{fmt_ps(m['lo'])}, {fmt_ps(m['mid'])}, {fmt_ps(m['hi'])}]")
            if m.get("signal_only"):
                print(f"  ⚑ {m['gate']}")
        if m["id"].startswith("custom:"):
            print(f"\n=== custom {m['id'][7:]}（{m['script']}） === 每股 [{fmt_ps(m['lo'])}, {fmt_ps(m['mid'])}, {fmt_ps(m['hi'])}]")

    sd = cfg.get("structure_discount")
    if sd:
        print(f"\n  结构折价 {sd['pct']:.0%} 已作用于各方法区间｜{sd['basis']}")
    print("\n=== 方法区间表（闸门 / 权重） ===")
    print("  方法             lo          mid         hi          权重    闸门")
    for m in methods:
        wt = m.get("weight")
        cap = "（custom 上限）" if m.get("capped") else ""
        print(f"  {m['id']:<14} {fmt_ps(m.get('lo')):>11} {fmt_ps(m.get('mid')):>11} {fmt_ps(m.get('hi')):>11}"
              f"  {('—' if wt is None else format(wt, '.2f')):>6}  {m['gate'] or '通过'}{cap}")
    adj = (cfg.get("weights") or {}).get("adjust") or {}
    for k, v in adj.items():
        print(f"  权重调整 {k} {v:+.2f}｜{cfg['weights']['reasons'][k]}")
    print("\n=== 合成（插值加权中位数；反向 DCF / PVGO / EVA / MC 不进区间） ===")
    if syn["L"] is not None:
        print(f"  L＝各方法下沿加权中位数 {fmt_ps(syn['L'])}｜H＝上沿加权中位数 {fmt_ps(syn['H'])}")
    inter = "空" if syn["intersection"] is None else f"[{fmt_ps(syn['intersection'][0])}, {fmt_ps(syn['intersection'][1])}]"
    env = "—" if syn["envelope"] is None else f"[{fmt_ps(syn['envelope'][0])}, {fmt_ps(syn['envelope'][1])}]"
    div = "—" if syn["divergence"] is None else ("∞" if syn["divergence"] == float("inf") else f"{syn['divergence']:.2f}×")
    print(f"  诊断：交集 {inter}｜包络 {env}｜mid 最大/最小 {div}")
    if syn["flags"]:
        print(f"  ⚑ 标记：{'、'.join(syn['flags'])} → 不确定性 ≥「高」" +
              ("；章节须逐项归因方法分歧" if "方法分歧" in syn["flags"] else ""))
    print("\n=== Football field ===")
    for ln in football(methods, syn, price):
        print(ln)

    if base:
        v0, tor = tornado(base, F, wacc, term)
        print(f"\n=== 驱动龙卷风（基准情景每股 {fmt_ps(v0)}，一档扰动） ===")
        for i, (lab, lo, hi, sp) in enumerate(tor):
            star = " ★最承重" if i < 3 else ""
            print(f"  {lab:<24} {fmt_ps(lo):>11} … {fmt_ps(hi):>11}  幅度 {fmt_ps(sp)}{star}")

    rob = robustness(inputs, cfg, ev, workdir)
    flips = sum(1 for r in rob if r[4] == "翻转")
    valid = sum(1 for r in rob if r[4] != "不适用")
    print(f"\n=== 稳健性（固定扰动集） === 标签翻转 {flips}/{valid}" + (f"（另 {len(rob) - valid} 组不适用）" if len(rob) > valid else ""))
    for name, L, H, lab, st in rob:
        rng_ = "—" if L is None else f"[{fmt_ps(L)}, {fmt_ps(H)}]"
        print(f"  {name:<22} {rng_:<24} {lab:<6} {st}")

    mc = cfg.get("montecarlo", {})
    if scen and mc is not False:
        r = montecarlo3(scen, F, wacc, term, mc or {})
        q = r["q"]
        print(f"\n=== 蒙特卡洛（情景混合抽样 n={r['n']}，只看分布形状与 P(loss)，不进区间） ===")
        print(f"  P10 {fmt_ps(q[0.10])} | P25 {fmt_ps(q[0.25])} | P50 {fmt_ps(q[0.50])} | P75 {fmt_ps(q[0.75])}"
              f" | P90 {fmt_ps(q[0.90])} | 均值 {fmt_ps(r['mean'])}")
        print(f"  P(内在价值 < 现价 {price:g}) = {r['p_loss']:.0%}")
    if scen:
        run_position({s["name"]: {"per_share": max(s["res"]["per_share"], 0.0)} for s in scen},
                     {"price": price, "scenarios": [{"name": s["name"], "prob": s["prob"]} for s in scen]})

    for lst in cfg.get("listings") or []:
        nm, lp, lfx = need(lst, "name", "listings[]"), need(lst, "price", "listings[]"), need(lst, "fx", "listings[]")
        conv = lambda x: x * F["fx"] / lfx
        if syn["L"] is not None:
            print(f"\n=== 分市场折算 {nm} === 区间 [{fmt_ps(conv(syn['L']))}, {fmt_ps(conv(syn['H']))}]"
                  f"（1 {nm} 币 = {lfx:g} 报表币）× 现价 {lp:g} → **{calibrate(lp, conv(syn['L']), conv(syn['H']))}**")

    for w in ev["warnings"]:
        print(f"  [警告] {w}")
    if syn["label"] is None:
        print(f"\n=== 标定 === {UNRELIABLE}（{syn['reason']}）")
        print("  （动作按财报可信度等级与否决链给出，见 valuation-methods.md §9）")
    else:
        print(f"\n=== 标定 === 综合区间 [{fmt_ps(syn['L'])}, {fmt_ps(syn['H'])}] × 现价 {price:g} → **{syn['label']}**")
        print("  （动作映射与否决项见 valuation-methods.md §9，由分析师结合不确定性与财报可信度执行）")
    return ev


DEMO3_INPUTS = {
    "schema": 1, "industry": "saas",
    "facts": {
        "price": {"value": 30.0}, "shares_outstanding": {"value": 100_000_000},
        "fx": {"value": 1.0, "key": None}, "net_debt": {"value": -200_000.0},
        "book_equity": {"value": 900_000.0}, "invested_capital": {"value": 700_000.0},
        "base_revenue": {"value": 1_000_000.0}, "base_operating_income": {"value": 120_000.0},
        "op_margin_reported": {"value": 0.12}, "net_income_ttm": {"value": 95_000.0},
        "ebitda_fy": {"value": 170_000.0}, "tax_effective": {"value": 0.21},
        "op_margin_median_5y": {"value": 0.11},
        "sales_to_capital_hist": {"value": 1.4, "clean": True},
        "history": [{"period": f"FY{y}", "yoy": g, "op_margin": m} for y, g, m in
                    ((2021, 0.22, 0.06), (2022, 0.18, 0.08), (2023, 0.15, 0.10), (2024, 0.14, 0.11), (2025, 0.12, 0.12))],
    },
    "basis": {"basis_flag": True, "reason": "股价日期晚于资产负债表日"},
}

DEMO3 = {
    "schema": 3, "market": "us",
    "basis_confirmed": {"reason": "资产负债表日后无融资/回购/并购", "source": "ledger §1（示例）"},
    "wacc": {"rf": 0.043, "beta": 1.1, "erp": 0.045, "kd_after_tax": 0.045, "target_debt_weight": 0.10},
    "terminal": {"g": 0.025},
    "drivers": {"sales_to_capital": {"value": 1.4, "anchor": "历史 Rev/IC 中位（干净）"}, "half_life": 3},
    "scenarios": [
        {"name": "bear", "prob": 0.25, "evidence": "中", "g1": 0.06, "margin_target": 0.08},
        {"name": "base", "prob": 0.50, "evidence": "中", "g1": {"value": 0.12, "anchor": 0.12, "pctile": "P50"},
         "margin_target": 0.18, "margin_reason": "示例：同业成熟期 18–22%（5 家，规模相当），5 年达成"},
        {"name": "bull", "prob": 0.25, "evidence": "弱", "g1": 0.17, "margin_target": 0.22,
         "margin_reason": "示例：同业成熟期 22–25%（5 家，规模相当）"},
    ],
    "methods": {
        "multiples": {"items": [
            {"name": "EV/EBITDA", "basis": "ev", "metric": "ebitda",
             "peers": [{"name": "A", "value": 14.0, "source": "示例"}, {"name": "B", "value": 17.5, "source": "示例"},
                       {"name": "C", "value": 19.0, "source": "示例"}, {"name": "D", "value": 22.0, "source": "示例"}]},
            {"name": "P/E", "basis": "equity", "metric": "net_income",
             "history": [{"period": "FY2023", "value": 24.0}, {"period": "FY2024", "value": 28.0},
                         {"period": "FY2025", "value": 31.0}]}]},
    },
    "montecarlo": {"n": 1000, "seed": 42},
}


DEMO = {
    "price": 100.0, "shares": 1.0, "net_debt": 5.0, "wacc": 0.09, "terminal_g": 0.03,
    "scenarios": [
        {"name": "bear", "prob": 0.3, "revenue": [10, 11, 12, 13, 14],
         "fcf_margin": [0.10, 0.12, 0.14, 0.15, 0.16], "fade_years": 3,
         "fade_g_start": 0.05, "annual_dilution": 0.01},
        {"name": "base", "prob": 0.5, "revenue": [10, 12, 14, 17, 20],
         "fcf_margin": [0.12, 0.15, 0.18, 0.20, 0.22], "fade_years": 5,
         "fade_g_start": 0.10, "annual_dilution": 0.01},
        {"name": "bull", "prob": 0.2, "revenue": [10, 13, 17, 22, 28],
         "fcf_margin": [0.14, 0.18, 0.22, 0.25, 0.28], "fade_years": 5,
         "fade_g_start": 0.14, "annual_dilution": 0.02}],
    "sensitivity": {"scenario": "base", "wacc": [0.08, 0.09, 0.10], "g": [0.02, 0.03, 0.04]},
    "reverse": {"interim_fcf": [1.2, 1.8, 2.5, 3.4, 4.4],
                "steady_margins": [0.20, 0.25], "base_revenue": 10},
    "range_low": 45, "range_high": 75,
    "pvgo": {"earnings_ps": 5.5},
    "epv": {"earnings_basis": "NOPAT", "normalized_earnings": 6.0, "coc": 0.09,
            "net_debt": 5.0, "shares": 1.0, "asset_value": 30.0, "price": 100.0,
            "growth": {"g": 0.04, "roiic": 0.20, "mode": "franchise"},
            "asset_series": [["FY-2", 4.5, 26], ["FY-1", 5.2, 28], ["最新", 6.0, 30]]},
    "eva": {"invested_capital": 40.0, "nopat": 6.0, "fade_years": 10,
            "reinvestment_rate": 0.4, "roiic": 0.20},
    "montecarlo": {"n": 2000, "base_revenue": 10, "years": 5,
                   "growth_mean": 0.14, "growth_std": 0.06,
                   "margin_low": 0.10, "margin_mode": 0.18, "margin_high": 0.26},
}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="JSON 假设文件路径")
    ap.add_argument("--inputs", help="schema 3：valuation/inputs.json 路径")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--demo3", action="store_true")
    a = ap.parse_args()
    try:
        if a.demo:
            run(DEMO)
        elif a.demo3:
            run3(DEMO3_INPUTS, DEMO3)
        elif a.config:
            with open(a.config, encoding="utf-8") as f:
                cfg = json.load(f)
            if cfg.get("schema") == 3:
                if not a.inputs:
                    die("schema 3 配置须同时传 --inputs valuation/inputs.json")
                with open(a.inputs, encoding="utf-8") as f:
                    inputs = json.load(f)
                workdir = os.path.dirname(os.path.dirname(os.path.abspath(a.inputs)))
                run3(inputs, cfg, workdir=workdir)
            else:
                run(cfg)
        else:
            ap.print_help(); sys.exit(1)
    except ValueError as e:
        print(str(e), file=sys.stderr); sys.exit(2)
