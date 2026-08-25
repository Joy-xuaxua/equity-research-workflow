#!/usr/bin/env python3
"""equity-research skill · 标准派生指标层计算器（W2 专用，catalog 覆盖指标全局唯一口径）

用法（Windows Git Bash 需 PYTHONUTF8=1）：
    PYTHONUTF8=1 python scripts/derive_metrics.py <workdir> [--catalog <path>] [--industry <slug>]

读 <workdir>/forensic/financials.csv（财年序列，行序=时间序）＋
   <workdir>/forensic/derived-inputs.json（可选；CSV 装不下的外部输入，每条带 ledger 锚）＋
   <workdir>/forensic/ledger.md（锚校验底本，仅在外部输入存在时要求），
按 references/derived-metrics.json 的公式计算派生指标（受控 AST 白名单求值，仅标准库、无网络、输出确定），
写 <workdir>/forensic/derived.csv（长格式：metric,label,period,value,unit,formula,inputs,anchor；纯净无注释）与
   <workdir>/forensic/derived-summary.md（并入 ledger §2.8 的底稿）。
不修改 financials.csv 与 ledger.md（加行不加列契约由 W2 保管）。

行为要点：
- 锚校验 fail loud：derived-inputs 每条 anchor 必须逐字出现在 ledger.md 原文；任何失配 →
  列出全部失败锚、exit 1、不写任何输出（修复后重跑）。
- 输入缺失（CSV 列缺口 / 外部输入未转录 / 期间不匹配）→ 该指标该期间 value=未获取，不猜数；
  per_fy 指标整条无可用期间时保留一行「未获取」（缺口可见、可审计）。
- 舍入：数值输出一律 1 位小数（% / 天 / 倍 / 年 / 万元 / pp）。
- 防呆：periodicity=point/window 的公式引用 financials.csv 的 shares 列 → 报错退出（该列是
  IAS 33 加权平均股数；市值/每股类必须用 derived-inputs 的 shares_outstanding 总股本，误用可差约 3 倍）。

退出码：0＝正常产出（允许含「未获取」行）；1＝配置/锚校验失败（无输出）。
"""

import argparse
import ast
import csv
import io
import json
import os
import sys

CATALOG_PATH = os.path.join(os.path.dirname(__file__), "..", "references", "derived-metrics.json")
NOT_OBTAINED = "未获取"
LATEST = "最新"
CSV_FIELDNAMES = ["metric", "label", "period", "value", "unit", "formula", "inputs", "anchor"]
FUNC_NAMES = {"yoy", "cagr", "first", "last", "avg2"}
PERIODICITY = {"per_fy", "window", "point"}
ALLOWED_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult,
                 ast.Div, ast.Pow, ast.USub, ast.UAdd, ast.Constant, ast.Name, ast.Call)


class Unresolved(Exception):
    """输入缺失（列缺口/外部输入未转录/期间不匹配）——指标降级为「未获取」，不是流程失败。"""


def fail(msg):
    print(f"[P1] {msg}", file=sys.stderr)
    sys.exit(1)


def fmt_value(v):
    """输入回显：整数去 .0，浮点 6 位有效数字。"""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return f"{v:.6g}"


# ---------- catalog ----------

def parse_formula(key, formula):
    try:
        node = ast.parse(formula, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"公式语法错误 [{key}]: {formula} ({e})")
    for n in ast.walk(node):
        if isinstance(n, ast.expr_context):  # Name/属性的 Load/Store 上下文节点，非求值语义
            continue
        if not isinstance(n, ALLOWED_NODES):
            raise ValueError(f"公式含白名单外节点 [{key}]: {type(n).__name__}")
        if isinstance(n, ast.Constant) and not isinstance(n.value, (int, float)):
            raise ValueError(f"公式含非数字字面量 [{key}]: {n.value!r}")
        if isinstance(n, ast.Call):
            if not (isinstance(n.func, ast.Name) and n.func.id in FUNC_NAMES):
                raise ValueError(f"公式调用未登记函数 [{key}]（仅支持 {sorted(FUNC_NAMES)}）")
            if len(n.args) != 1 or not isinstance(n.args[0], ast.Name) or n.keywords:
                raise ValueError(f"函数仅接受单个列名参数 [{key}]: {formula}")
    return node


def referenced_names(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def load_catalog(path):
    with io.open(path, "r", encoding="utf-8") as f:
        catalog = json.load(f)
    if catalog.get("version") != 1:
        raise ValueError(f"derived-metrics.json version != 1: {catalog.get('version')}")
    metrics = catalog.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        raise ValueError("derived-metrics.json metrics 为空或非列表")
    seen, ordered = set(), []
    for m in metrics:
        key = m.get("key")
        if not key or key in seen:
            raise ValueError(f"catalog 指标 key 缺失或重复：{key!r}")
        seen.add(key)
        if m.get("periodicity") not in PERIODICITY:
            raise ValueError(f"catalog 指标 {key} 的 periodicity 非法：{m.get('periodicity')!r}")
        if m.get("type") == "external" or not m.get("formula"):
            m["_formula_ast"] = None
            if m.get("periodicity") == "window":
                raise ValueError(f"external 指标 {key} 不支持 window")
        else:
            m["_formula_ast"] = parse_formula(key, m["formula"])
        ordered.append(m)
    prior = set()
    for m in ordered:  # 顺序检查：公式引用的先行指标必须定义在其之前（catalog 受控、确定性要求）
        node = m["_formula_ast"]
        if node is not None:
            for name in referenced_names(node):
                if name != m["key"] and name in seen and name not in prior:
                    raise ValueError(f"catalog 顺序错误：{m['key']} 引用了定义在后的指标 {name}")
        prior.add(m["key"])
    for m in ordered:  # 总股本防呆：point/window 公式禁用 CSV shares 列（IAS 33 加权平均股数）
        node = m["_formula_ast"]
        if node is None or m["periodicity"] == "per_fy":
            if node is not None and "shares" in referenced_names(node):
                print(f"[P2] 提示：{m['key']}（per_fy）引用了 CSV shares 列（IAS 33 加权平均股数）——"
                      f"每股/市值类请改用外部输入 shares_outstanding", file=sys.stderr)
            continue
        if "shares" in referenced_names(node):
            raise ValueError(f"总股本防呆：{m['key']}（{m['periodicity']}）公式引用了 financials.csv 的 shares 列"
                             "（IAS 33 加权平均股数）——市值/每股类一律用外部输入 shares_outstanding（总股本）")
    return ordered


# ---------- 工作目录输入 ----------

def load_financials(path):
    if not os.path.isfile(path):
        fail(f"缺少 {path}（W2 应先产出 financials.csv）")
    with io.open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = []
        for raw in csv.DictReader(f):
            if not (raw.get("period") or "").strip():
                continue
            row = {"period": raw["period"].strip()}
            for col, val in raw.items():
                if col in (None, "period"):
                    continue
                val = (val or "").strip()
                if val:
                    try:
                        row[col] = float(val.replace(",", ""))
                    except ValueError:
                        fail(f"financials.csv 非数值单元格：period={row['period']} col={col} val={val!r}")
                else:
                    row[col] = None
            rows.append(row)
    if not rows:
        fail("financials.csv 无数据行")
    return rows


def load_inputs(path):
    """derived-inputs.json → ({(key, period): entry}, industry)。文件不存在 → ({}, None)。"""
    if not os.path.isfile(path):
        return {}, None
    with io.open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    entries = {}
    for e in doc.get("inputs", []):
        key = (e.get("key") or "").strip()
        period = (e.get("period") or LATEST).strip()
        if not key:
            fail("derived-inputs.json 存在空 key 的输入条目")
        if (key, period) in entries:
            fail(f"derived-inputs.json 重复输入条目：key={key} period={period}")
        entries[(key, period)] = e
    return entries, doc.get("industry") or None


def validate_anchors(entries, ledger_text):
    failures = []
    for (key, period), e in sorted(entries.items()):
        anchor = (e.get("anchor") or "").strip()
        if not anchor:
            failures.append(f"key={key} period={period}：anchor 为空（每个外部输入必须带 ledger 原文锚）")
        elif anchor not in ledger_text:
            failures.append(f"key={key} period={period}：anchor 未逐字出现在 ledger.md ——「{anchor}」")
    return failures


# ---------- 求值 ----------

class Evaluator:
    """受控公式求值。变量解析顺序——per_fy：当前行 CSV 列 → 同期间外部输入 → 先行派生指标；
    point/window：「最新」外部输入 → 先行 point 指标（裸 CSV 列名不可用，须经 last()/first()）。"""

    def __init__(self, rows, entries, computed):
        self.rows = rows
        self.entries = entries
        self.computed = computed
        self.used_inputs = []   # [(display, value_str)]
        self.used_anchors = []  # ["key@anchor"]
        self.used_csv = False

    def _record(self, display, value):
        self.used_inputs.append((display, fmt_value(value)))

    def _resolve_ext(self, key, period):
        e = self.entries.get((key, period))
        if e is None:
            return None
        anchor = (e.get("anchor") or "").strip()
        self.used_anchors.append(f"{key}@{anchor}" if anchor else f"{key}@<无锚>")
        return float(e["value"])

    def resolve_name(self, key, ctx):
        if ctx["kind"] == "per_fy":
            row = self.rows[ctx["idx"]]
            if key in row and row[key] is not None:
                self.used_csv = True
                self._record(key, row[key])
                return row[key]
            v = self._resolve_ext(key, row["period"])
            if v is not None:
                self._record(key, v)
                return v
            vals = self.computed.get(key)
            if vals and row["period"] in vals:
                v = vals[row["period"]]
                self._record(key, v)
                return v
            raise Unresolved(f"{key} 在 {row['period']} 不可用")
        v = self._resolve_ext(key, LATEST)
        if v is not None:
            self._record(key, v)
            return v
        vals = self.computed.get(key)
        if vals and LATEST in vals:
            v = vals[LATEST]
            self._record(key, v)
            return v
        raise Unresolved(f"{key} 在 point/window 语境不可用（CSV 列请用 last()/first()）")

    def call_func(self, name, col, ctx):
        def cell(i):
            row = self.rows[i]
            if col not in row or row[col] is None:
                raise Unresolved(f"{col} 在 {row['period']} 缺失")
            self.used_csv = True
            if ctx["kind"] == "per_fy" and i == ctx["idx"]:
                self._record(col, row[col])
            else:
                self._record(f"{col}[{row['period']}]", row[col])
            return row[col]

        if name == "yoy":
            if ctx["kind"] != "per_fy" or ctx["idx"] < 1:
                raise Unresolved(f"yoy({col}) 需要 per_fy 语境且有上一行")
            cur, prev = cell(ctx["idx"]), cell(ctx["idx"] - 1)
            if prev == 0:
                raise Unresolved(f"yoy({col}) 基期为 0")
            return (cur / prev - 1.0) * 100.0
        if name == "avg2":
            if ctx["kind"] != "per_fy" or ctx["idx"] < 1:
                raise Unresolved(f"avg2({col}) 需要 per_fy 语境且有上一行")
            cur, prev = cell(ctx["idx"]), cell(ctx["idx"] - 1)
            return (cur + prev) / 2.0
        if name == "first":
            return cell(0)
        if name == "last":
            return cell(len(self.rows) - 1)
        if name == "cagr":
            if len(self.rows) < 2:
                raise Unresolved(f"cagr({col}) 需要至少两个财年")
            v0, v1 = cell(0), cell(len(self.rows) - 1)
            if v0 <= 0 or v1 <= 0:
                raise Unresolved(f"cagr({col}) 要求首末期均为正数")
            return ((v1 / v0) ** (1.0 / (len(self.rows) - 1)) - 1.0) * 100.0
        raise Unresolved(f"未知函数 {name}")

    def eval(self, node, ctx):
        if isinstance(node, ast.Expression):
            return self.eval(node.body, ctx)
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            return self.resolve_name(node.id, ctx)
        if isinstance(node, ast.UnaryOp):
            v = self.eval(node.operand, ctx)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.BinOp):
            l, r = self.eval(node.left, ctx), self.eval(node.right, ctx)
            if isinstance(node.op, ast.Add):
                return l + r
            if isinstance(node.op, ast.Sub):
                return l - r
            if isinstance(node.op, ast.Mult):
                return l * r
            if isinstance(node.op, ast.Div):
                if r == 0:
                    raise Unresolved("除数为 0")
                return l / r
            if isinstance(node.op, ast.Pow):
                return l ** r
        if isinstance(node, ast.Call):
            return self.call_func(node.func.id, node.args[0].id, ctx)
        raise Unresolved(f"未支持节点 {type(node).__name__}")

    def anchor_str(self):
        parts = []
        if self.used_csv:
            parts.append("csv@financials.csv（台账溯源）")
        parts.extend(self.used_anchors)
        return "; ".join(dict.fromkeys(parts))


# ---------- 计算与产出 ----------

def render_row(m, period, value, ev):
    return {"metric": m["key"], "label": m.get("label", ""), "period": period,
            "value": f"{value:.1f}", "unit": m.get("unit", ""), "formula": m.get("formula") or "转录（derived-inputs.json）",
            "inputs": "; ".join(f"{d}={v}" for d, v in dict.fromkeys(ev.used_inputs)) if ev else "",
            "anchor": ev.anchor_str() if ev else ""}


def compute_rows(metrics, rows, entries):
    computed = {}
    out = []
    for m in metrics:
        key, per = m["key"], m["periodicity"]
        node = m["_formula_ast"]
        if node is None:  # external：值/单位/期间按 derived-inputs 转录直通（锚随之）
            matched = [(k, p, e) for (k, p), e in sorted(entries.items()) if k == key]
            if matched:
                for k, p, e in matched:
                    anchor = (e.get("anchor") or "").strip()
                    v = e.get("value")
                    v_str = fmt_value(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)
                    out.append({"metric": key, "label": m.get("label", ""), "period": p,
                                "value": v_str, "unit": e.get("unit") or m.get("unit") or "-",
                                "formula": "转录（derived-inputs.json）", "inputs": f"{key}={v_str}",
                                "anchor": f"{key}@{anchor}" if anchor else f"{key}@<无锚>"})
            else:
                out.append({"metric": key, "label": m.get("label", ""), "period": LATEST, "value": NOT_OBTAINED,
                            "unit": m.get("unit", ""), "formula": "转录（derived-inputs.json）", "inputs": "", "anchor": ""})
                print(f"[P2] derived 未获取：{key}（derived-inputs.json 未转录该 KPI）", file=sys.stderr)
            continue
        emitted, reason = [], None
        if per == "per_fy":
            for i in range(len(rows)):
                ev = Evaluator(rows, entries, computed)
                try:
                    v = ev.eval(node, {"kind": "per_fy", "idx": i})
                except (Unresolved, ZeroDivisionError, ValueError, OverflowError) as e:
                    reason = str(e)
                    continue
                computed.setdefault(key, {})[rows[i]["period"]] = v
                emitted.append(render_row(m, rows[i]["period"], v, ev))
        else:
            ev = Evaluator(rows, entries, computed)
            try:
                v = ev.eval(node, {"kind": per})
                wperiod = f"{rows[0]['period']}→{rows[-1]['period']}" if per == "window" else LATEST
                computed.setdefault(key, {})[wperiod] = v
                emitted.append(render_row(m, wperiod, v, ev))
            except (Unresolved, ZeroDivisionError, ValueError, OverflowError) as e:
                reason = str(e)
        if not emitted:  # 整条无可用期间 → 保留一行「未获取」（缺口可见，不静默消失）
            fallback = (rows[-1]["period"] if per == "per_fy"
                        else (f"{rows[0]['period']}→{rows[-1]['period']}" if per == "window" else LATEST))
            emitted.append({"metric": key, "label": m.get("label", ""), "period": fallback, "value": NOT_OBTAINED,
                            "unit": m.get("unit", ""), "formula": m.get("formula", ""), "inputs": "", "anchor": ""})
            print(f"[P2] derived 未获取：{key}（{reason or '输入缺失'}）", file=sys.stderr)
        out.extend(emitted)
    return out, computed


def write_summary(path, out_rows):
    lines = [
        "# 派生指标摘要（ledger §2.8 底稿）",
        "",
        "> 由 `scripts/derive_metrics.py` 按 `references/derived-metrics.json` 生成，勿手改；",
        "> 重跑：`PYTHONUTF8=1 python <skill_root>/scripts/derive_metrics.py <workdir>`。",
        "> 值为「未获取」＝输入缺失（对应 ledger 列缺口/未转录项），不是计算失败；外部输入与锚见 `forensic/derived-inputs.json`。",
        "",
        "| 指标 | 期间 | 值 | 单位 | 公式 |",
        "|---|---|---:|---|---|",
    ]
    for r in out_rows:
        lines.append(f"| {r['label']}（{r['metric']}） | {r['period']} | {r['value']} | {r['unit']} | {r['formula']} |")
    lines.append("")
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))


def run(workdir, catalog=CATALOG_PATH, industry=None):
    forensic = os.path.join(workdir, "forensic")
    try:
        metrics_all = load_catalog(catalog)
    except ValueError as e:
        fail(f"catalog 无效：{e}")
    rows = load_financials(os.path.join(forensic, "financials.csv"))
    entries, doc_industry = load_inputs(os.path.join(forensic, "derived-inputs.json"))
    industry = industry or doc_industry or "any"

    if entries:
        ledger_path = os.path.join(forensic, "ledger.md")
        if not os.path.isfile(ledger_path):
            fail(f"存在外部输入但缺少 {ledger_path}（锚校验底本）")
        with io.open(ledger_path, "r", encoding="utf-8") as f:
            failures = validate_anchors(entries, f.read())
        if failures:
            print("[P1] derived-inputs 锚校验失败（anchor 须逐字出现在 ledger.md；修复后重跑，本次不产出输出）：",
                  file=sys.stderr)
            for x in failures:
                print(f"  - {x}", file=sys.stderr)
            sys.exit(1)

    metrics = [m for m in metrics_all if m.get("industry", "any") in ("any", industry)]
    formula_names = set()
    for m in metrics:  # 被公式引用的外部输入必须转录为数字（external 直通条目允许字符串）
        if m["_formula_ast"] is not None:
            formula_names |= referenced_names(m["_formula_ast"])
    for (k, p), e in sorted(entries.items()):
        v = e.get("value")
        if k in formula_names and (isinstance(v, bool) or not isinstance(v, (int, float))):
            fail(f"外部输入 key={k} period={p} 被公式引用但 value 非数字：{v!r}")

    out, _ = compute_rows(metrics, rows, entries)
    csv_path = os.path.join(forensic, "derived.csv")
    with io.open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, lineterminator="\n")
        w.writeheader()
        for r in out:
            w.writerow(r)
    write_summary(os.path.join(forensic, "derived-summary.md"), out)
    n_missing = sum(1 for r in out if r["value"] == NOT_OBTAINED)
    print(f"derived: {len(out)} 行（未获取 {n_missing}）｜industry={industry}｜→ {csv_path} ＋ derived-summary.md")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="标准派生指标层计算器（只产 derived.csv/derived-summary.md，"
                                             "不改 financials.csv 与 ledger.md）")
    ap.add_argument("workdir", help="研究工作目录（含 forensic/）")
    ap.add_argument("--catalog", default=CATALOG_PATH, help="derived-metrics.json 路径")
    ap.add_argument("--industry", default=None, help="覆盖 derived-inputs.json 的 industry（默认 any）")
    args = ap.parse_args(argv)
    return run(args.workdir, catalog=args.catalog, industry=args.industry)


if __name__ == "__main__":
    sys.exit(main())
