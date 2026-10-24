#!/usr/bin/env python3
"""equity-research skill · 估值事实层生成器（W5 第一步；事实由脚本生成，假设只给驱动）

用法（Windows Git Bash 需 PYTHONUTF8=1）：
    PYTHONUTF8=1 python scripts/valuation_inputs.py <workdir> [--out <path>]

读 <workdir>/forensic/financials.csv（千元，报表币）＋ forensic/derived-inputs.json（price/股本/fx 锚）＋
   forensic/derived.csv（catalog 指标，om_pct 等直接引用不重算），
写 <workdir>/valuation/inputs.json：价格、总股本、fx、净债、基准日期核对、基期营收（TTM 或 FY）、
   报告口径经营利润率、有效税率、投入资本序列与"是否干净"判定、历史增速/利润率序列。
每项带 value/unit/source/formula/flags。规则见 references/valuation-assumptions.md §0。

退出码：0＝正常写出；1＝CSV 卫生检查失败 / 缺锚（fail loud，不写输出，回报编排者重派 W2 修数）。
"""
import argparse
import csv
import datetime as dt
import importlib.util
import io
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("derive_metrics", os.path.join(HERE, "derive_metrics.py"))
DM = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(DM)

FY_RE = re.compile(r"^FY(\d{4})$")
H_RE = re.compile(r"^(\d{4})H([12])$")
DATE_RE = re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")
LIAB_ASSET_MAX = 5.0          # 总负债 > 总资产×5 视为列错位（优先股计负债的公司约 2–3 倍）
CV_CLEAN_MAX = 0.5            # Rev/IC 变异系数上限（"干净"判定）
TAX_CLAMP = (0.0, 0.40)


class InputsError(Exception):
    pass


# ---------- CSV 卫生（checker --financials 复用） ----------

def _num(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return "NaN"


def csv_hygiene(path):
    """返回问题列表 [(code, message)]；空列表＝通过。行长度、期间格式与重复、cash≤总资产、负债/资产、有息负债≤总负债。"""
    issues = []
    with io.open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return [("CSV_EMPTY", "financials.csv 为空")]
    header = [h.strip() for h in rows[0]]
    seen = set()
    for i, raw in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in raw):
            continue
        period = raw[0].strip()
        if len(raw) != len(header):
            issues.append(("CSV_ROW_LENGTH", f"第 {i} 行（{period}）字段数 {len(raw)} ≠ 表头 {len(header)}"
                                             "——列错位，后续列的值会落进错误的列"))
            continue
        if not (FY_RE.match(period) or H_RE.match(period)):
            issues.append(("CSV_PERIOD_FORMAT", f"第 {i} 行期间标签 {period!r} 不是 FYyyyy / yyyyH1|H2"))
        if period in seen:
            issues.append(("CSV_PERIOD_DUPLICATE", f"期间 {period} 重复"))
        seen.add(period)
        rec = dict(zip(header, raw))
        ta, cash = _num(rec.get("total_assets")), _num(rec.get("cash"))
        tl, ibd = _num(rec.get("total_liabilities")), _num(rec.get("interest_bearing_debt"))
        for col, v in (("total_assets", ta), ("cash", cash), ("total_liabilities", tl), ("interest_bearing_debt", ibd)):
            if v == "NaN":
                issues.append(("CSV_NON_NUMERIC", f"{period} 列 {col} 非数值"))
        if isinstance(ta, float) and isinstance(cash, float) and cash > ta:
            issues.append(("CSV_CASH_GT_ASSETS", f"{period} 现金 {cash:,.0f} > 总资产 {ta:,.0f}（多半是列错位）"))
        if isinstance(ta, float) and isinstance(tl, float) and ta > 0 and tl > ta * LIAB_ASSET_MAX:
            issues.append(("CSV_LIAB_GT_ASSETS", f"{period} 总负债 {tl:,.0f} > 总资产×{LIAB_ASSET_MAX:g}"))
        if isinstance(tl, float) and isinstance(ibd, float) and ibd > tl:
            issues.append(("CSV_DEBT_GT_LIAB", f"{period} 有息负债 {ibd:,.0f} > 总负债 {tl:,.0f}"))
    return issues


# ---------- 期间与日期 ----------

def parse_fye(entries):
    e = entries.get(("fiscal_year_end", DM.LATEST))
    if not e:
        return (12, 31), ["财年结束日未转录（derived-inputs fiscal_year_end），假定 12-31"]
    m = re.match(r"^(\d{1,2})-(\d{1,2})$", str(e.get("value", "")).strip())
    if not m:
        raise InputsError(f"fiscal_year_end 值须为 MM-DD：{e.get('value')!r}")
    return (int(m.group(1)), int(m.group(2))), []


def _month_end(y, m):
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def period_end(period, fye):
    m = FY_RE.match(period)
    if m:
        y = int(m.group(1))
        return _month_end(y, fye[0]) if fye[1] >= 28 else dt.date(y, fye[0], fye[1])
    m = H_RE.match(period)
    if m:
        y, h = int(m.group(1)), int(m.group(2))
        mm = fye[0] - 6 if h == 1 else fye[0]       # H1 结束＝财年结束前 6 个月（12 月年结 → 6-30）
        yy = y
        if mm <= 0:
            mm += 12
            yy -= 1
        return _month_end(yy, mm)
    raise InputsError(f"无法解析期间 {period!r}")


def entry_date(e):
    for k in ("as_of", "anchor", "ts"):
        m = DATE_RE.search(str(e.get(k) or ""))
        if m:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def fact(value, unit, source, formula=None, flags=None, **extra):
    d = {"value": value, "unit": unit, "source": source, "formula": formula, "flags": flags or []}
    d.update(extra)
    return d


# ---------- 构建 ----------

def load_derived_csv(path):
    out = {}
    if not os.path.isfile(path):
        return out
    with io.open(path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                out.setdefault(r["metric"], {})[r["period"]] = float(r["value"])
            except (ValueError, TypeError):
                continue
    return out


def ic_of(row):
    ta, tl, cash = row.get("total_assets"), row.get("total_liabilities"), row.get("cash")
    if ta is None or tl is None or cash is None:
        return None
    return (ta - tl) + (row.get("interest_bearing_debt") or 0.0) - cash


def build(workdir):
    forensic = os.path.join(workdir, "forensic")
    csv_path = os.path.join(forensic, "financials.csv")
    if not os.path.isfile(csv_path):
        raise InputsError(f"缺少 {csv_path}")
    hyg = csv_hygiene(csv_path)
    if hyg:
        raise InputsError("financials.csv 卫生检查失败（回报编排者重派 W2 修数）：\n" +
                          "\n".join(f"  - [{c}] {m}" for c, m in hyg))
    rows = DM.load_financials(csv_path)
    entries, industry = DM.load_inputs(os.path.join(forensic, "derived-inputs.json"))
    derived = load_derived_csv(os.path.join(forensic, "derived.csv"))
    fye, fye_flags = parse_fye(entries)
    for r in rows:
        r["_end"] = period_end(r["period"], fye)
    rows.sort(key=lambda r: r["_end"])
    fy = [r for r in rows if FY_RE.match(r["period"])]
    by_period = {r["period"]: r for r in rows}
    if not fy:
        raise InputsError("financials.csv 没有财年（FY）行")
    facts, notes = {}, list(fye_flags)

    # 价格 / 股本 / fx（derived-inputs，W2 锚校验过；禁止 CSV shares 列）
    missing = [k for k in ("price_close", "shares_outstanding") if (k, DM.LATEST) not in entries]
    if missing:
        raise InputsError(f"derived-inputs.json 缺少 {missing}（period=最新）——W2 须转录价格与总股本锚")
    pe, se = entries[("price_close", DM.LATEST)], entries[("shares_outstanding", DM.LATEST)]
    price_date, shares_date = entry_date(pe), entry_date(se)
    facts["price"] = fact(float(pe["value"]), pe.get("unit", ""), f"derived-inputs price_close @ {pe.get('anchor', '')}",
                          date=str(price_date) if price_date else None)
    facts["shares_outstanding"] = fact(float(se["value"]), "股", f"derived-inputs shares_outstanding @ {se.get('anchor', '')}",
                                       date=str(shares_date) if shares_date else None,
                                       flags=["禁止使用 CSV shares 列（IAS 33 加权平均股数）"])
    fx_keys = sorted(k for (k, p) in entries if k.startswith("fx_") and p == DM.LATEST)
    if len(fx_keys) > 1:
        raise InputsError(f"derived-inputs 有多个 fx 键 {fx_keys}，只能保留一个 fx_<价格币>_<报表币>")
    if fx_keys:
        k = fx_keys[0]
        parts = k.split("_")
        if len(parts) != 3:
            raise InputsError(f"fx 键名须为 fx_<价格币>_<报表币>：{k}")
        fe = entries[(k, DM.LATEST)]
        fxv = float(fe["value"])
        if fxv <= 0:
            raise InputsError(f"{k} 必须为正：{fxv}")
        facts["fx"] = fact(fxv, f"{parts[2].upper()}/{parts[1].upper()}", f"derived-inputs {k} @ {fe.get('anchor', '')}",
                           formula=f"1 {parts[1].upper()} = {fxv:g} {parts[2].upper()}；每股(价格币)＝权益(报表币)÷fx",
                           key=k, price_ccy=parts[1], report_ccy=parts[2])
    else:
        facts["fx"] = fact(1.0, "同币", "未转录 fx 键", formula="视为同币",
                           flags=["⚠ 未转录 fx_<价格币>_<报表币>，按同币处理——跨币标的须由 W2 补转录"], key=None)

    # 资产负债表（最新有总资产的期间）
    bs_rows = [r for r in rows if r.get("total_assets") is not None]
    if not bs_rows:
        raise InputsError("financials.csv 没有任何期间有 total_assets")
    bs = bs_rows[-1]
    if bs.get("cash") is None:
        raise InputsError(f"{bs['period']} 缺 cash，无法计算净债")
    ibd = bs.get("interest_bearing_debt")
    nd_flags = [] if ibd is not None else ["⚠ interest_bearing_debt 缺失，按 0 计"]
    mi = bs.get("minority_equity")
    nd = (ibd or 0.0) - bs["cash"] + (mi or 0.0)
    facts["net_debt"] = fact(nd, "千元（报表币）", f"financials.csv {bs['period']}",
                             formula="interest_bearing_debt − cash" + (" + minority_equity" if mi is not None else ""),
                             flags=nd_flags, period=bs["period"],
                             components={"interest_bearing_debt": ibd, "cash": bs["cash"], "minority_equity": mi})
    facts["book_equity"] = fact(bs["total_assets"] - (bs.get("total_liabilities") or 0.0), "千元（报表币）",
                                f"financials.csv {bs['period']}", formula="total_assets − total_liabilities（含少数股东）",
                                period=bs["period"])
    ic0 = ic_of(bs)
    facts["invested_capital"] = fact(ic0, "千元（报表币）", f"financials.csv {bs['period']}",
                                     formula="(total_assets − total_liabilities) + interest_bearing_debt − cash",
                                     period=bs["period"],
                                     flags=[] if (ic0 or 0) > 0 else ["⚠ 投入资本 ≤0（资本释放上限按 0 处理）"])

    # 基准日期核对
    bs_date = bs["_end"]
    later = [n for n, d in (("股本", shares_date), ("股价", price_date)) if d and d > bs_date]
    undated = [n for n, d in (("股本", shares_date), ("股价", price_date)) if d is None]
    basis = {"balance_sheet_date": str(bs_date), "shares_date": str(shares_date) if shares_date else None,
             "price_date": str(price_date) if price_date else None,
             "basis_flag": bool(later or undated),
             "reason": (f"{'/'.join(later)}日期晚于资产负债表日 {bs_date}" if later else "") +
                       (f"；{'/'.join(undated)}无日期" if undated else ""),
             "required": "assumptions.json 须写 pro_forma（现金增减/股本口径/ledger 出处）或 basis_confirmed（无期后事件＋出处）"}

    # 基期营收：成对半年行 → TTM；否则最新 FY
    last_fy = fy[-1]
    fy_year = int(FY_RE.match(last_fy["period"]).group(1))
    h_cur = by_period.get(f"{fy_year + 1}H1")
    h_prev = by_period.get(f"{fy_year}H1")
    if (fye == (12, 31) and h_cur and h_prev and h_cur.get("revenue") is not None
            and h_prev.get("revenue") is not None and last_fy.get("revenue") is not None):
        def ttm(col):
            vals = (last_fy.get(col), h_cur.get(col), h_prev.get(col))
            return None if None in vals else vals[0] + vals[1] - vals[2]
        rev_basis, rev_formula = f"TTM {h_cur['period']}", f"{last_fy['period']} + {h_cur['period']} − {h_prev['period']}"
        base_rev, base_oi, ni_ttm = ttm("revenue"), ttm("operating_income"), ttm("net_income")
    else:
        rev_basis, rev_formula = last_fy["period"], f"{last_fy['period']} revenue"
        base_rev, base_oi, ni_ttm = last_fy.get("revenue"), last_fy.get("operating_income"), last_fy.get("net_income")
    if not base_rev or base_rev <= 0:
        raise InputsError(f"基期营收不可用或非正（{rev_basis}）")
    facts["base_revenue"] = fact(base_rev, "千元（报表币）", "financials.csv", formula=rev_formula, basis=rev_basis,
                                 flags=[] if rev_basis.startswith("TTM") else
                                 ["CSV 无成对半年行 → 用最新 FY；ledger 的 TTM 须走 override"])
    facts["base_operating_income"] = fact(base_oi, "千元（报表币）", "financials.csv", formula=rev_formula.replace("revenue", "operating_income"),
                                          basis=rev_basis)
    facts["op_margin_reported"] = fact(None if base_oi is None else base_oi / base_rev, "比率", "financials.csv",
                                       formula="base_operating_income / base_revenue（同口径）", basis=rev_basis)
    facts["net_income_ttm"] = fact(ni_ttm, "千元（报表币）", "financials.csv", formula=rev_formula.replace("revenue", "net_income"),
                                   basis=rev_basis)
    dep = last_fy.get("depreciation")
    facts["ebitda_fy"] = fact(None if (dep is None or last_fy.get("operating_income") is None)
                              else last_fy["operating_income"] + dep, "千元（报表币）", f"financials.csv {last_fy['period']}",
                              formula="operating_income + depreciation")

    # 有效税率
    rates = [1 - r["net_income"] / r["pre_tax_income"] for r in fy
             if (r.get("net_income") or 0) > 0 and (r.get("pre_tax_income") or 0) > 0]
    tax = None if not rates else min(max(statistics.median(rates), TAX_CLAMP[0]), TAX_CLAMP[1])
    facts["tax_effective"] = fact(tax, "比率", "financials.csv", formula="盈利年份 1 − NI/PTI 的中位数，夹在 [0, 40%]",
                                  flags=[] if rates else ["无盈利年份 → null（dcf.py 按 drivers.tax 或法定税率表）"],
                                  n_years=len(rates))

    # 历史序列（FY）
    om_derived = derived.get("om_pct", {})
    hist = []
    for i, r in enumerate(fy):
        rev, oi, ic = r.get("revenue"), r.get("operating_income"), ic_of(r)
        om = om_derived.get(r["period"])
        om = om / 100.0 if om is not None else (oi / rev if (oi is not None and rev) else None)
        prev = fy[i - 1].get("revenue") if i else None
        hist.append({"period": r["period"], "revenue": rev,
                     "yoy": (rev / prev - 1) if (rev and prev) else None,
                     "op_margin": om,
                     "om_source": "derived.csv om_pct" if r["period"] in om_derived else "csv 计算",
                     "invested_capital": ic,
                     "rev_to_ic": (rev / ic) if (rev and ic and ic > 0) else None,
                     "roic_pretax": (oi / ic) if (oi is not None and ic and ic > 0) else None})
    facts["history"] = hist

    recent = hist[-5:]
    s2c = [h["rev_to_ic"] for h in recent]
    clean = len(recent) >= 3 and all(v is not None for v in s2c)
    cv = None
    if clean:
        mu = statistics.mean(s2c)
        cv = statistics.pstdev(s2c) / mu if mu else None
        clean = cv is not None and cv < CV_CLEAN_MAX
    facts["sales_to_capital_hist"] = fact(statistics.median(s2c) if clean else None, "倍（营收/投入资本）", "financials.csv",
                                          formula="近 5 个 FY Rev/IC 中位数（≥3 期、IC>0、变异系数<0.5 才算干净）",
                                          clean=clean, cv=cv, series=[(h["period"], h["rev_to_ic"]) for h in recent],
                                          flags=[] if clean else ["历史不干净 → 仅作诊断；sales_to_capital 必须显式给值并注明来源"])
    oms = [h["op_margin"] for h in recent if h["op_margin"] is not None]
    facts["op_margin_median_5y"] = fact(statistics.median(oms) if oms else None, "比率", "derived.csv om_pct / csv",
                                        formula="近 5 个 FY 经营利润率中位数（EPV 常态化默认）", n_years=len(oms))

    return {"schema": 1, "generated_by": "scripts/valuation_inputs.py",
            "generated": dt.date.today().isoformat(), "industry": industry,
            "units": "金额＝千元（报表币，同 financials.csv）；price＝价格币/股；shares＝股",
            "fiscal_year_end": f"{fye[0]:02d}-{fye[1]:02d}",
            "facts": facts, "basis": basis, "notes": notes}


def summary(doc):
    f = doc["facts"]
    p = lambda x, fmt: "n/a" if x is None else format(x, fmt)
    fx = f["fx"]
    lines = [
        f"inputs: industry={doc['industry']} | 现价 {f['price']['value']:g}（{f['price'].get('date')}）"
        f" | 总股本 {f['shares_outstanding']['value']:,.0f}（{f['shares_outstanding'].get('date')}）",
        f"  fx: {fx['formula']}" + ("" if fx.get("key") else "  ⚠ 同币声明"),
        f"  净债 {f['net_debt']['value']:,.0f}（{f['net_debt']['period']}，{f['net_debt']['formula']}）",
        f"  基期营收 {f['base_revenue']['value']:,.0f}（{f['base_revenue']['basis']}）| 报告口径经营利润率 "
        f"{p(f['op_margin_reported']['value'], '.1%')} | 有效税率 {p(f['tax_effective']['value'], '.1%')}",
        f"  投入资本 {p(f['invested_capital']['value'], ',.0f')} | Rev/IC 历史 "
        f"{'干净 ' + format(f['sales_to_capital_hist']['value'], '.2f') if f['sales_to_capital_hist']['clean'] else '不干净（须显式给 sales_to_capital）'}",
    ]
    b = doc["basis"]
    if b["basis_flag"]:
        lines.append(f"  ⚠ basis_flag：{b['reason']} → {b['required']}")
    for n in doc["notes"]:
        lines.append(f"  注：{n}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="估值事实层生成器 → valuation/inputs.json")
    ap.add_argument("workdir")
    ap.add_argument("--out", help="默认 <workdir>/valuation/inputs.json")
    a = ap.parse_args(argv)
    try:
        doc = build(a.workdir)
    except InputsError as e:
        print(f"[P1] valuation_inputs 失败：{e}", file=sys.stderr)
        return 1
    out = a.out or os.path.join(a.workdir, "valuation", "inputs.json")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(summary(doc))
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
