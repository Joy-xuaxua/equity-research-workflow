#!/usr/bin/env python3
"""equity-research skill · 跨线指标对撞与勾稽复算检查器

用法（Windows Git Bash 需 PYTHONUTF8=1）：
    PYTHONUTF8=1 python scripts/collision_check.py <workdir> [--json] [--strict] [--out <path>]

扫描 <workdir>/collection/[0-9][0-9]-*.md 的「## 指标登记」块（行式 YAML 子集，无 PyYAML），
按 (key, period, scope) 跨线分组对撞 + 按 references/collision-metrics.json 的勾稽规则复算，
产出 forensic/collision-report.txt（三节 txt，判断不入此文件）。仅使用 Python 标准库。

退出码：P0/P1 → 1；--strict 时 P2 也计入；「无登记块」降级为 P2（旧 workdir 退出 0）。

anchor 唯一性口径：剔除指标登记块后的正文中出现且仅出现 1 次（登记块内的引用不计入）。
"""

import argparse
import glob
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "..", "references", "collision-metrics.json")
COLLISION_TOL = 0.005  # 同名同期间同口径值差的立案阈值（0.5%，吸收四舍五入）
MARKET_FALLBACK_PERIOD = "最新"  # 行情类指标在期间缺失时的回退期间
MARKET_KEYS = {"price_close", "market_cap", "shares_outstanding", "high_52w", "pe_ttm", "ps_ttm", "price_first_day_close"}
BARE_MAGNITUDE = {"": 1, "元": 1, "千": 1e3, "万": 1e4, "百万": 1e6, "亿": 1e8, "万亿": 1e12}
CCY_TOKENS = {"人民币": "CNY", "港元": "HKD", "美元": "USD"}
RANGE_SEP = re.compile(r"(-?[\d,]+(?:\.\d+)?)\s*[–—~～]\s*(-?[\d,]+(?:\.\d+)?)")
NUM_RE = re.compile(r"-?[\d,]+(?:\.\d+)?")


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    detail: str = ""
    file: str = ""

    def line(self) -> str:
        loc = f" [{self.file}]" if self.file else ""
        detail = f"\n    {self.detail}" if self.detail else ""
        return f"[{self.severity}] {self.code}{loc}: {self.message}{detail}"


def add(issues: List[Issue], severity: str, code: str, message: str, detail: str = "", file: str = "") -> None:
    issues.append(Issue(severity, code, message, detail, file))


# ---------- registry ----------

def load_registry(path: str = REGISTRY_PATH) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        registry = json.load(f)
    if registry.get("version") != 1:
        raise ValueError(f"collision-metrics.json version != 1: {registry.get('version')}")
    return registry


def expected_registry_lines(registry: Dict) -> Dict[str, set]:
    """按 lines_by_mode 推导各模式下「应含登记指标」的采集线；不在其中的线（如 full 模式 04-industry）不要求登记块。"""
    out: Dict[str, set] = {"full": set(), "earnings": set()}
    for meta in registry["metrics"].values():
        for mode, lines in meta.get("lines_by_mode", {}).items():
            out[mode] |= set(lines or [])
    return out


def read_mode(workdir: str) -> str:
    try:
        with open(os.path.join(workdir, "brief.json"), encoding="utf-8") as f:
            mode = json.load(f).get("mode")
        return mode if mode in ("full", "earnings") else "full"
    except (OSError, ValueError):
        return "full"


# ---------- 值 / 单位 / 期间解析 ----------

def parse_number_loose(s: str) -> Tuple[Optional[float], Optional[float]]:
    """'4,856' → (4856, 4856)；'120,000–150,000' → (120000, 150000)；解析失败 → (None, None)。"""
    if s is None:
        return None, None
    t = str(s).strip().strip('"').strip("'")
    t = re.sub(r"^(约|大约|approx\.?|≈|\+|±)\s*", "", t)
    m = RANGE_SEP.search(t)
    if m:
        try:
            return float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
        except ValueError:
            return None, None
    m = NUM_RE.search(t)
    if not m:
        return None, None
    try:
        v = float(m.group(0).replace(",", ""))
    except ValueError:
        return None, None
    return v, v


def parse_unit(unit: str, units: Dict) -> Optional[Tuple[str, float, Optional[str]]]:
    """返回 (dim, factor, ccy)。① 整串命中 units；② 抽走币种词后余下为币种单位键或裸量级词。失败 → None。"""
    u = (unit or "").strip()
    if not u:
        return None
    if u in units:
        e = units[u]
        return e["dim"], float(e["factor"]), e.get("ccy")
    for token, ccy in CCY_TOKENS.items():
        if token in u:
            rest = u.replace(token, "")
            if rest in units and units[rest]["dim"] == "currency":
                return "currency", float(units[rest]["factor"]), ccy
            if rest in BARE_MAGNITUDE:
                return "currency", float(BARE_MAGNITUDE[rest]), ccy
            return None
    return None


def canonical_period(p: str) -> Optional[str]:
    """FY2025/财年2025/2025→FY2025；2025H1/1H2025→2025H1；FY2026Q1/2026Q1→FY2026Q1；最新/TTM/日期原样。"""
    s = (p or "").strip()
    if not s:
        return None
    m = re.match(r"^(?:FY\s*|财年\s*)?(\d{4})(?:财年)?$", s)
    if m:
        return f"FY{m.group(1)}"
    m = re.match(r"^(\d{4})\s*[Hh]([12])$", s)
    if m:
        return f"{m.group(1)}H{m.group(2)}"
    m = re.match(r"^([12])[Hh](\d{4})$", s) or re.match(r"^[Hh]([12])\s*(\d{4})$", s)
    if m:
        return f"{m.group(2)}H{m.group(1)}"
    m = re.match(r"^(\d{4})\s*上半年$", s)
    if m:
        return f"{m.group(1)}H1"
    m = re.match(r"^(\d{4})\s*下半年$", s)
    if m:
        return f"{m.group(1)}H2"
    m = re.match(r"^(?:FY\s*)?(\d{4})\s*[Qq]([1-4])$", s) or re.match(r"^(\d{4})财年[Qq]([1-4])$", s)
    if m:
        return f"FY{m.group(1)}Q{m.group(2)}"
    if re.match(r"^(最新|当前|current|latest|收盘)$", s, re.I):
        return "最新"
    if re.match(r"^(TTM|滚动|滚动十二个月|trailing)", s, re.I):
        return "TTM"
    m = re.match(r"^(\d{4}-\d{2}-\d{2})$", s)
    if m:
        return m.group(1)
    return None


# ---------- 登记块解析 ----------

def extract_registry_block(text: str) -> Tuple[Optional[str], str]:
    """返回 (块内容或 None, 剔除该 fenced 块后的正文)。只取「## 指标登记」之后第一个 fence。"""
    m = re.search(r"^##\s*指标登记\s*$", text, flags=re.M)
    if not m:
        return None, text
    after = text[m.end():]
    fence = re.search(r"^```[a-zA-Z]*\s*$", after, flags=re.M)
    if not fence:
        return None, text
    start = fence.end()
    close = re.search(r"^```\s*$", after[start:], flags=re.M)
    if not close:
        return None, text
    block = after[start:start + close.start()]
    body = text[:m.end()] + after[:fence.end()] + after[start + close.end():]
    return block, body


def parse_metric_block(block: str, fname: str, issues: List[Issue]) -> List[Dict]:
    """行式 YAML 子集：'- key: x' 起条目，缩进行为字段，字段值去引号。"""
    entries: List[Dict] = []
    cur: Optional[Dict] = None
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        m = re.match(r"^\s*-\s*(\S+)\s*:\s*(.*)$", line)
        if m:
            if cur:
                entries.append(cur)
            cur = {m.group(1): m.group(2).strip().strip('"').strip("'")}
            continue
        m = re.match(r"^\s+(\S+)\s*:\s*(.*)$", line)
        if m and cur is not None:
            if m.group(1) in cur:
                add(issues, "P1", "ENTRY_DUPLICATE_FIELD", f"条目 {cur.get('key', '?')} 字段 {m.group(1)} 重复", file=fname)
            cur[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    if cur:
        entries.append(cur)
    return entries


# ---------- 校验 ----------

def validate_entries(entries: List[Dict], fname: str, body: str, registry: Dict, issues: List[Issue]) -> List[Dict]:
    metrics = registry["metrics"]
    valid: List[Dict] = []
    for e in entries:
        key = e.get("key", "")
        if key not in metrics:
            add(issues, "P1", "REGISTRY_KEY_UNKNOWN", f"登记 key 不在清单：{key}", file=fname)
            continue
        missing = [f for f in ("value", "unit", "period", "source", "tier", "ts", "anchor") if not e.get(f)]
        if missing:
            add(issues, "P1", "ENTRY_MALFORMED", f"key={key} 缺字段：{', '.join(missing)}", file=fname)
            continue
        lo, hi = parse_number_loose(e["value"])
        if lo is None:
            add(issues, "P1", "VALUE_UNPARSEABLE", f"key={key} value 无法解析：{e['value']!r}", file=fname)
            continue
        unit = parse_unit(e["unit"], registry["units"])
        if unit is None:
            add(issues, "P2", "UNIT_UNKNOWN", f"key={key} unit 无法解析：{e['unit']!r}（不参与比较）", file=fname)
            continue
        period = canonical_period(e["period"])
        if period is None:
            add(issues, "P3", "PERIOD_UNRECOGNIZED", f"key={key} period 无法归一：{e['period']!r}", file=fname)
            continue
        scope = (e.get("scope") or "").strip().lower()
        if metrics[key].get("scope_required") and not scope:
            add(issues, "P2", "SCOPE_MISSING", "key=%s 为分部指标，scope 必填" % key, file=fname)
        anchor = e["anchor"]
        n = body.count(anchor)
        if n != 1:
            add(issues, "P2", "ANCHOR_NOT_UNIQUE",
                f"key={key} anchor 在正文出现 {n} 次（应为 1，剔除登记块计）：{anchor[:30]}…", file=fname)
        valid.append({
            "key": key, "file": fname, "lo": lo, "hi": hi,
            "dim": unit[0], "factor": unit[1], "ccy": unit[2], "unit_raw": e["unit"],
            "period": period, "scope": scope,
            "source": e.get("source", ""), "tier": e.get("tier", ""), "ts": e.get("ts", ""),
            "anchor": anchor,
        })
    return valid


def dedupe_and_selfcheck(valid: List[Dict], fname: str, issues: List[Issue]) -> List[Dict]:
    """同文件同 (key,period,scope)：归一值不同 → P1 SELF_CONTRADICTION；相同 → 去重。"""
    seen: Dict[Tuple, Dict] = {}
    out: List[Dict] = []
    for e in valid:
        g = (e["key"], e["period"], e["scope"])
        if g in seen:
            a, b = seen[g], e
            if (round(a["lo"] * a["factor"], 6), round(a["hi"] * a["factor"], 6)) != \
               (round(b["lo"] * b["factor"], 6), round(b["hi"] * b["factor"], 6)):
                add(issues, "P1", "SELF_CONTRADICTION",
                    f"{e['key']} / {e['period']} 同文件两个登记值不一致："
                    f"{a['lo'] * a['factor']:g} vs {b['lo'] * b['factor']:g}", file=fname)
            continue
        seen[g] = e
        out.append(e)
    return out


# ---------- 对撞与勾稽 ----------

def group_entries(all_entries: List[Dict]) -> Dict[Tuple, List[Dict]]:
    groups: Dict[Tuple, List[Dict]] = {}
    for e in all_entries:
        groups.setdefault((e["key"], e["period"], e["scope"]), []).append(e)
    return groups


def _norm(e: Dict) -> Tuple[float, float]:
    return round(e["lo"] * e["factor"], 6), round(e["hi"] * e["factor"], 6)


def _fmt_range(r: Tuple[float, float]) -> str:
    return f"{r[0]:g}" + (f"–{r[1]:g}" if r[0] != r[1] else "")


def collide(groups: Dict[Tuple, List[Dict]], issues: List[Issue]) -> set:
    """跨线对撞；返回被立案（值有分歧）的 (key, period) 集合，供勾稽跳过。"""
    contested: set = set()
    for (key, period, scope), entries in sorted(groups.items()):
        # 按 (dim, ccy) 分桶：同桶才比大小；币种桶数 >1 → P2 交对账员
        buckets: Dict[Tuple, List[Dict]] = {}
        for e in entries:
            buckets.setdefault((e["dim"], e["ccy"]), []).append(e)
        currency_ccys = {c for (d, c) in buckets if d == "currency"}
        if len(currency_ccys) > 1:
            add(issues, "P2", "CURRENCY_MISMATCH",
                f"{key} / {period}" + (f" / {scope}" if scope else "") +
                " 跨币种并列（" + " vs ".join(sorted(str(c) for c in currency_ccys)) + "），不比大小，交对账员裁汇率",
                file=entries[0]["file"])
        for bucket in buckets.values():
            distinct: List[Tuple[Tuple[float, float], Dict]] = []
            for e in bucket:
                r = _norm(e)
                if all(r != rr for rr, _ in distinct):
                    distinct.append((r, e))
            if len(distinct) < 2:
                continue
            contested_pair = False
            scalars = [d for d in distinct if d[0][0] == d[0][1]]
            ranges = [d for d in distinct if d[0][0] != d[0][1]]
            for i, (ra, _) in enumerate(scalars):
                for rb, _ in scalars[i + 1:]:
                    if abs(ra[0] - rb[0]) > COLLISION_TOL * max(abs(ra[0]), abs(rb[0]), 1.0):
                        contested_pair = True
            for (ra, _), (rb, _) in [(a, b) for a in scalars for b in ranges]:
                if not (ra[0] <= rb[1] and rb[0] <= ra[0]):
                    contested_pair = True
            for i, (ra, _) in enumerate(ranges):
                for rb, _ in ranges[i + 1:]:
                    if not (ra[0] <= rb[1] and rb[0] <= ra[1]):
                        contested_pair = True
            if not contested_pair:
                continue
            contested.add((key, period))
            detail = "\n    ".join(
                f"{'ABCD'[i]}: {_fmt_range(r)}（{e['unit_raw']}）tier{e['tier']} {e['source']}｜"
                f"anchor=\"{e['anchor'][:24]}…\"｜ts={e['ts']}｜{e['file']}"
                for i, (r, e) in enumerate(distinct[:4])
            )
            add(issues, "P1", "COLLISION_VALUE_MISMATCH",
                f"{key} / {period}" + (f" / {scope}" if scope else "") + " 跨线值分歧，需裁决",
                detail=detail, file=distinct[0][1]["file"])
    return contested


def run_crosschecks(groups: Dict[Tuple, List[Dict]], registry: Dict, issues: List[Issue], contested: set) -> None:
    """inputs 齐备才执行；区间输入跳过；被立案分歧的指标不参与；按取值签名去重（防回退期间重复触发）。"""
    net_income_periods = [p for (k, p, s) in groups if k == "net_income"]

    def entry_at(key: str, period: str) -> Optional[Dict]:
        cand = groups.get((key, period, ""))
        if not cand and key in MARKET_KEYS:
            cand = groups.get((key, MARKET_FALLBACK_PERIOD, ""))
        if not cand:
            return None
        if (key, cand[0]["period"]) in contested:
            return None
        return cand[0]

    def scalar(e: Optional[Dict]) -> Optional[float]:
        if e is None or e["lo"] != e["hi"]:
            return None
        return e["lo"] * e["factor"]

    fired: set = set()
    periods = sorted({p for (_, p, _) in groups})
    for rule in registry["crosschecks"]:
        rid, tol, sev = rule["id"], rule["rel_tol"], rule.get("severity", "P1")
        for period in periods:
            if rule.get("aggregation") == "sum_scope":
                rev = entry_at("revenue", period)
                segs = [e for (k, p, _), es in groups.items() if k == "revenue_segment" and p == period for e in es]
                if rev is None or not segs or ("revenue", period) in contested:
                    continue
                seg_vals = [scalar(e) for e in segs]
                expected_total = sum(v for v in seg_vals if v is not None)
                actual = scalar(rev)
                if actual is None or any(v is None for v in seg_vals):
                    continue
                expected, actual_v = expected_total, actual
                sig = (rid, period, round(expected, 6), round(actual_v, 6))
            else:
                inputs: Dict[str, Dict] = {}
                skip = False
                for key in rule["inputs"]:
                    e = entry_at(key, period)
                    if e is None and key == "net_income" and rid == "pe_identity":
                        e = entry_at(key, "TTM") or \
                            (entry_at(key, max(net_income_periods)) if net_income_periods else None)
                    if e is None:
                        skip = True
                        break
                    inputs[key] = e
                if skip:
                    continue
                vals = {k: scalar(e) for k, e in inputs.items()}
                if any(v is None for v in vals.values()):
                    continue
                if rid == "market_cap_identity":
                    expected, actual_v = vals["price_close"] * vals["shares_outstanding"], vals["market_cap"]
                elif rid == "balance_sheet_identity":
                    expected, actual_v = vals["total_liabilities"] + vals["total_equity"], vals["total_assets"]
                elif rid == "fcf_identity":
                    expected, actual_v = vals["cfo"] - vals["capex"], vals["fcf"]
                elif rid == "pe_identity":
                    if vals["net_income"] <= 0:
                        continue
                    expected, actual_v = vals["market_cap"] / vals["net_income"], vals["pe_ttm"]
                elif rid == "eps_identity":
                    if vals["shares_outstanding"] == 0:
                        continue
                    expected, actual_v = vals["net_income"] / vals["shares_outstanding"], vals["eps"]
                else:
                    continue
                sig = (rid, tuple(sorted((k, inputs[k]["period"]) for k in inputs)),
                       round(expected, 6), round(actual_v, 6))
            if sig in fired:
                continue
            fired.add(sig)
            if expected == actual_v:
                continue
            delta = abs(actual_v - expected) / max(abs(expected), abs(actual_v), 1.0)
            if delta > tol:
                add(issues, sev, "CROSSCHECK_FAIL",
                    f"{rid}｜期望≈{expected:g} 实际={actual_v:g} Δ={delta:.1%}（tol {tol:.0%}）",
                    detail=rule.get("expr", ""))


# ---------- 冲突表覆盖检查 ----------

def check_table_coverage(text: str, fname: str, registered_keys: set, registry: Dict, issues: List[Issue]) -> None:
    """冲突表行涉及清单内指标但本文件登记块无该条目 → P2 TABLE_UNREGISTERED。"""
    m = re.search(r"^##\s*冲突\s*$", text, flags=re.M)
    if not m:
        return
    seg = text[m.end():]
    n = re.search(r"^##\s", seg, flags=re.M)
    if n:
        seg = seg[:n.start()]
    name_to_key: Dict[str, str] = {}
    for key, meta in registry["metrics"].items():
        name_to_key[meta["name_zh"]] = key
        name_to_key[key] = key
    for row in re.finditer(r"^\|(.+)$", seg, flags=re.M):
        indicator = row.group(1).split("|")[0].strip()
        if not indicator or set(indicator) <= {"-", " ", ":"} or indicator in ("指标", "metric"):
            continue
        hit = None
        for name, key in name_to_key.items():
            if name and (indicator == name or (len(name) >= 3 and name in indicator)):
                hit = key
                break
        if hit and hit not in registered_keys:
            add(issues, "P2", "TABLE_UNREGISTERED",
                f"冲突表行涉及清单内指标 {hit}（{indicator!r}）但本文件登记块无该条目", file=fname)


# ---------- 报告与主流程 ----------

def build_report(issues: List[Issue], files_total: int, files_with_block: int, degraded: bool) -> str:
    def pick(pred):
        return [i.line() for i in issues if pred(i)]

    sections = [
        ("== 对撞冲突（P1，需裁决）==",
         lambda i: i.code in ("COLLISION_VALUE_MISMATCH", "SELF_CONTRADICTION", "REGISTRY_KEY_UNKNOWN",
                              "ENTRY_MALFORMED", "VALUE_UNPARSEABLE", "ENTRY_DUPLICATE_FIELD")),
        ("== 勾稽复算 ==", lambda i: i.code == "CROSSCHECK_FAIL"),
        ("== 登记块体检（P2/P3）==", lambda i: i.code not in (
            "COLLISION_VALUE_MISMATCH", "SELF_CONTRADICTION", "REGISTRY_KEY_UNKNOWN", "ENTRY_MALFORMED",
            "VALUE_UNPARSEABLE", "ENTRY_DUPLICATE_FIELD", "CROSSCHECK_FAIL")),
    ]
    lines = [f"collision_check 报告｜登记文件 {files_with_block}/{files_total}｜registry v1"]
    if degraded:
        lines.append("（无任何登记块：对撞与勾稽降级跳过，仅登记块体检）")
    for title, pred in sections:
        rows = pick(pred)
        if rows:
            lines.append(title)
            lines.extend(rows)
    counts = {s: sum(1 for i in issues if i.severity == s) for s in ("P0", "P1", "P2", "P3")}
    lines.append(f"汇总：P1 × {counts['P1']}，P2 × {counts['P2']}，P3 × {counts['P3']}")
    return "\n".join(lines) + "\n"


def run(workdir: str, out: Optional[str] = None, as_json: bool = False, strict: bool = False) -> Tuple[int, List[Issue]]:
    issues: List[Issue] = []
    try:
        registry = load_registry()
    except (OSError, ValueError) as exc:
        add(issues, "P1", "REGISTRY_LOAD_FAIL", f"无法加载 collision-metrics.json：{exc}")
        return 1, issues
    files = sorted(glob.glob(os.path.join(workdir, "collection", "[0-9][0-9]-*.md")))
    if not files:
        add(issues, "P1", "NO_COLLECTION", f"{workdir}/collection/ 下没有 [0-9][0-9]-*.md 采集文件")
        return 1, issues
    all_entries: List[Dict] = []
    files_with_block = 0
    scanned = 0
    expected = expected_registry_lines(registry)
    mode = read_mode(workdir)
    expected_md = {slug + ".md" for slug in expected[mode]}
    for path in files:
        fname = os.path.basename(path)
        if fname not in expected_md:
            continue  # 本线按 registry 不含清单指标（如 full 模式 04-industry），不要求登记块
        scanned += 1
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        block, body = extract_registry_block(text)
        if block is None:
            add(issues, "P2", "REGISTRY_BLOCK_MISSING", "无「## 指标登记」块（旧版采集文件）；对撞/勾稽对该文件降级", file=fname)
            continue
        files_with_block += 1
        entries = validate_entries(parse_metric_block(block, fname, issues), fname, body, registry, issues)
        entries = dedupe_and_selfcheck(entries, fname, issues)
        all_entries.extend(entries)
        check_table_coverage(text, fname, {e["key"] for e in entries}, registry, issues)
    degraded = files_with_block == 0
    if not degraded:
        groups = group_entries(all_entries)
        contested = collide(groups, issues)
        run_crosschecks(groups, registry, issues, contested)
    out_path = out or os.path.join(workdir, "forensic", "collision-report.txt")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    report = build_report(issues, scanned, files_with_block, degraded)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(report)
    if as_json:
        print(json.dumps({"issues": [i.__dict__ for i in issues]}, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(report)
    fail_levels = {"P0", "P1"} if not strict else {"P0", "P1", "P2"}
    return (1 if any(i.severity in fail_levels for i in issues) else 0), issues


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="跨线指标对撞与勾稽复算")
    ap.add_argument("workdir", help="研究工作目录（含 collection/）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    ap.add_argument("--strict", action="store_true", help="P2 也返回非零退出码")
    ap.add_argument("--out", help="报告输出路径（默认 <workdir>/forensic/collision-report.txt）")
    args = ap.parse_args()
    code, _ = run(args.workdir, args.out, args.json, args.strict)
    sys.exit(code)


if __name__ == "__main__":
    main()
