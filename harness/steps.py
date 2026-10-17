"""Deterministic pipeline steps (no LLM): workdir contract, skill scripts, ledger merge,
assembly (SKILL.md §6), lint, checker, appendix, naming. PDF conversion lives in `pdf.py`.
"""
from __future__ import annotations

import glob
import io
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .config import ORCH_ROOT, REFS, SCRIPTS, SKILL_ROOT
from .docs import sections
from .util import ScriptResult, now, read, read_json, run_py, today, write, write_json
from . import validators as V

TREE = ["collection", "forensic", "quality", "chapters", "valuation", "draft", "redteam", "checker", "final"]


# ------------------------------------------------------------------------------------
# Step 0 / fixture preparation
# ------------------------------------------------------------------------------------

def make_tree(workdir: Path) -> None:
    for d in TREE:
        (workdir / d).mkdir(parents=True, exist_ok=True)


def write_brief(workdir: Path, fields: Dict) -> Dict:
    brief = {
        "company": "", "ticker": "", "exchange": "", "mode": "full", "language": "zh", "format": "pdf",
        "currency": "", "fiscal_year": "", "fiscal_period": "", "industry": "", "ah_listing": False,
        "cn_adr": False, "prior_report": "none", "forecast_review": "none", "coverage": "initiation",
    }
    brief.update(fields)
    brief.update({"workdir": workdir.resolve().as_posix(), "skill_root": SKILL_ROOT.as_posix(),
                  "orch_root": ORCH_ROOT.as_posix()})
    brief.setdefault("created", today())
    write_json(workdir / "brief.json", brief)
    return brief


def prepare_fixture(source: Path, workdir: Path) -> Tuple[Dict, List[str]]:
    """Fresh workdir from a finished run: its archived collection becomes `collection/`, nothing else is copied.

    W1 and G1 are then already satisfied (G1's industry-classification.md lives in the collection),
    so the run starts at the W1→W2 handoff. Returns (brief, notes).
    """
    if workdir.exists() and any(workdir.iterdir()):
        raise FileExistsError(f"workdir 已存在且非空：{workdir}")
    src_coll = source / "collection-deprecated"
    if not src_coll.is_dir():
        src_coll = source / "collection"
    make_tree(workdir)
    shutil.copytree(src_coll, workdir / "collection", dirs_exist_ok=True)
    old = read_json(source / "brief.json")
    keep = {k: old[k] for k in ("company", "ticker", "exchange", "mode", "language", "format", "currency",
                                "fiscal_year", "fiscal_period", "industry", "ah_listing", "cn_adr") if k in old}
    keep.update({"prior_report": "none", "forecast_review": "none", "coverage": "initiation",
                 "created": today(), "data_cutoff": old.get("created", today()),
                 "fixture_source": source.resolve().as_posix()})
    brief = write_brief(workdir, keep)
    notes = [f"collection/ ← {src_coll.relative_to(source.parent).as_posix()}（{len(list(src_coll.glob('*.md')))} 文件）",
             "prior_report=none（基准对照为同数据重跑，不做旧报告复盘）"]
    return brief, notes


# ------------------------------------------------------------------------------------
# W2 scripts (run by the harness, not by the reconciler LLM)
# ------------------------------------------------------------------------------------

def collision_check(workdir: Path) -> ScriptResult:
    return run_py([SCRIPTS / "collision_check.py", workdir], cwd=workdir, tee=workdir / "forensic" / "collision-report.txt")


def checker_financials(workdir: Path) -> ScriptResult:
    return run_py([SCRIPTS / "check_research_output.py", "--financials", "forensic/financials.csv"],
                  cwd=workdir, tee=workdir / "forensic" / "checker-financials.txt")


def reconcile_merge(workdir: Path) -> ScriptResult:
    return run_py([SCRIPTS / "reconcile_merge.py", workdir], cwd=workdir, tee=workdir / ".harness" / "logs" / "reconcile_merge.txt")


def derive_metrics(workdir: Path) -> ScriptResult:
    return run_py([SCRIPTS / "derive_metrics.py", workdir], cwd=workdir, tee=workdir / ".harness" / "logs" / "derive_metrics.txt")


def failing_anchor_keys(res: ScriptResult, workdir: Path) -> List[int]:
    """Indices of derived-inputs entries whose anchor derive_metrics reported as missing from the ledger."""
    di = read_json(workdir / "forensic" / "derived-inputs.json")
    bad = set(re.findall(r"key=(\S+) period=(\S+?)：", res.output))
    return [idx for idx, item in enumerate(di.get("inputs", []))
            if (str(item.get("key")), str(item.get("period"))) in bad]


def drop_derived_inputs(workdir: Path, indices: Sequence[int]) -> List[str]:
    """Agent-body fallback (动作 10③): after ≤2 fix rounds, delete inputs whose anchor still fails."""
    path = workdir / "forensic" / "derived-inputs.json"
    di = read_json(path)
    inputs = di.get("inputs", [])
    dropped = [f"{inputs[i].get('key')}@{inputs[i].get('period')}" for i in sorted(set(indices)) if i < len(inputs)]
    di["inputs"] = [x for i, x in enumerate(inputs) if i not in set(indices)]
    write_json(path, di)
    return dropped


SUMMARY_TITLE = "派生指标摘要（derived-summary.md 原样并入，脚本产出勿手改）"


def merge_derived_summary(workdir: Path) -> str:
    """动作 10④: insert derived-summary.md verbatim into ledger §2 as the next 2.x subsection (idempotent)."""
    ledger_path = workdir / "forensic" / "ledger.md"
    summary = read(workdir / "forensic" / "derived-summary.md").strip()
    text = read(ledger_path)
    lines = text.splitlines()
    secs = sections(text)
    sec3 = next((s for s in secs if s.sid == "3" and s.level <= 2), None)
    existing = next((s for s in secs if "派生指标摘要" in s.title and (s.sid or "").startswith("2.")), None)
    if existing is not None:
        end = sec3.start if sec3 and sec3.start > existing.start else existing.end
        num = existing.sid
        del lines[existing.start:end]
        insert_at = existing.start
    else:
        subs = [s.sid for s in secs if s.sid and re.fullmatch(r"2\.\d+", s.sid)]
        num = f"2.{max((int(x.split('.')[1]) for x in subs), default=0) + 1}"
        insert_at = sec3.start if sec3 else len(lines)
    block = [f"### {num} {SUMMARY_TITLE}", "", summary, ""]
    lines[insert_at:insert_at] = block
    write(ledger_path, "\n".join(lines).rstrip() + "\n")
    return num


def ledger_summary_consistent(workdir: Path) -> bool:
    return read(workdir / "forensic" / "derived-summary.md").strip() in read(workdir / "forensic" / "ledger.md")


# ------------------------------------------------------------------------------------
# Assembly (SKILL.md §6) and header
# ------------------------------------------------------------------------------------

def industry_line(brief: Dict) -> str:
    rules = read_json(REFS / "industry-rules.json")["industries"]
    slugs = [s.strip() for s in str(brief.get("industry", "")).split(",") if s.strip()]
    parts = [f"{rules.get(s, {}).get('name_zh', s)}（{s}）" for s in slugs]
    if brief.get("language") == "en":
        return "Industry appendix: " + ", ".join(slugs)
    return "行业附录: " + "、".join(parts)


def write_header(workdir: Path, brief: Dict) -> None:
    company, ticker = brief["company"], brief["ticker"]
    created, cutoff = brief.get("created", today()), brief.get("data_cutoff", brief.get("created", today()))
    if brief.get("language") == "en":
        title = (f"# {company} ({ticker}) FY{brief.get('fiscal_year')} {brief.get('fiscal_period')} Earnings Deep Dive"
                 if brief.get("mode") == "earnings" else f"# {company} ({ticker}) Equity Research Report")
        sub = f"Date: {created} | Data cutoff: {cutoff} | Currency: {brief.get('currency', '')}"
    else:
        title = (f"# {company}（{ticker}） FY{brief.get('fiscal_year')} {brief.get('fiscal_period')} 财报深度分析"
                 if brief.get("mode") == "earnings" else f"# {company}（{ticker}）个股投资研究报告")
        sub = f"撰写日期：{created} ｜ 数据截止日：{cutoff}（采集时点，详见各章来源标注） ｜ 报告币种：{brief.get('currency', '')}"
    write(workdir / "draft" / "_header.md", f"{title}\n\n{sub}\n\n{industry_line(brief)}\n")


def assemble(workdir: Path, order: Sequence[str], out_rel: str) -> int:
    parts = [read(workdir / "draft" / "_header.md").strip()]
    for nn in order:
        for f in sorted(glob.glob(str(workdir / "chapters" / f"ch{nn}-*.md"))):
            t = read(f)
            t = re.sub(r"<!--\s*data-gaps:.*?-->\s*", "", t, flags=re.S)
            parts.append(t.strip())
    text = "\n\n---\n\n".join(parts) + "\n"
    write(workdir / out_rel, text)
    return len(text)


DRAFT_ORDER = ["02", "03", "04", "05", "06", "07", "08"]
FINAL_ORDER = ["01", *DRAFT_ORDER, "09"]


# ------------------------------------------------------------------------------------
# W8: lint, checker, appendix, naming
# ------------------------------------------------------------------------------------

def lint(workdir: Path, tee: Optional[Path] = None) -> Tuple[int, List[Tuple[str, str]]]:
    res = run_py([ORCH_ROOT / "lint_contract.py", workdir, "--json"], cwd=workdir)
    try:
        data = json.loads(res.stdout)
        issues = [(i["code"], i["message"]) for i in data.get("issues", [])]
    except ValueError:
        issues = [("LINT_CRASH", res.output[-300:])]
    if tee:
        write(tee, "\n".join(f"[FAIL] {c}: {m}" for c, m in issues) or "OK: 契约检查通过")
    return res.code, issues


@dataclass
class CheckerResult:
    code: int
    issues: List[Dict]
    counts: Dict[str, int] = field(default_factory=dict)
    text: str = ""

    def blocking(self) -> List[Dict]:
        return [i for i in self.issues if i["severity"] in ("P0", "P1")]


def latest_assumptions(workdir: Path) -> str:
    return "valuation/assumptions.v2.json" if (workdir / "valuation" / "assumptions.v2.json").exists() else "valuation/assumptions.json"


def latest_dcf_output(workdir: Path) -> str:
    return "valuation/dcf-output.v2.txt" if (workdir / "valuation" / "dcf-output.v2.txt").exists() else "valuation/dcf-output.txt"


def checker(workdir: Path, report_rel: str, brief: Dict, tee: Optional[Path] = None) -> CheckerResult:
    args = [SCRIPTS / "check_research_output.py", "--report", report_rel,
            "--assumptions", latest_assumptions(workdir), "--financials", "forensic/financials.csv",
            "--industry", str(brief.get("industry") or "auto"), "--language", brief.get("language", "zh")]
    js = run_py([*args, "--json"], cwd=workdir)
    txt = run_py(args, cwd=workdir, tee=tee)
    try:
        payload = json.loads(js.stdout)
        issues = payload.get("issues", payload) if isinstance(payload, dict) else payload
    except ValueError:
        issues = [{"severity": "P1", "code": "CHECKER_CRASH", "message": js.output[-300:], "file": ""}]
    counts = {s: sum(1 for i in issues if i.get("severity") == s) for s in ("P0", "P1", "P2", "P3")}
    return CheckerResult(txt.code, issues, counts, txt.output)


def final_basename(brief: Dict) -> str:
    date = str(brief.get("created", today())).replace("-", "")
    if brief.get("mode") == "earnings":
        return f"{brief['company']}_{brief['ticker']}_{brief.get('fiscal_year')}{brief.get('fiscal_period')}_财报深度分析_{date}"
    return f"{brief['company']}_{brief['ticker']}_个股投资研究报告_{date}"


def unique_final(workdir: Path, base: str) -> str:
    """No overwrite: `_v2`, `_v3`… when a same-named md or pdf already exists."""
    name, n = base, 1
    while (workdir / "final" / f"{name}.md").exists() or (workdir / "final" / f"{name}.pdf").exists():
        n += 1
        name = f"{base}_v{n}"
    return name


# ---- appendix -----------------------------------------------------------------------

def _ledger_source_section(workdir: Path) -> Optional[str]:
    text = read(workdir / "forensic" / "ledger.md")
    lines = text.splitlines()
    for s in sections(text):
        if "来源清单" in s.title:
            return "\n".join(lines[s.start + 1:s.end]).strip()
    return None


def _fallback_sources(workdir: Path) -> str:
    rows = []
    adj = workdir / "forensic" / "adjudications.json"
    if adj.exists():
        for rec in read_json(adj).get("adjudications", []):
            rows.append(f"| {rec.get('metric', '')} | ledger {rec.get('ledger_ref', rec.get('id', ''))} | — |")
    di = workdir / "forensic" / "derived-inputs.json"
    if di.exists():
        for i in read_json(di).get("inputs", []):
            rows.append(f"| {i.get('key')}（{i.get('period')}） | ledger 锚：{str(i.get('anchor', ''))[:40]} | {i.get('ts', '')} |")
    return "| 数据项 | 来源 | 时间 |\n|---|---|---|\n" + "\n".join(rows)


def _scenario_rows(conf: Dict) -> List[str]:
    rows = []
    for sc in conf.get("scenarios", []):
        p = sc.get("prob", sc.get("p", sc.get("probability", "")))
        ev = sc.get("evidence_strength", sc.get("evidence", sc.get("证据强度", "")))
        rows.append(f"| {sc.get('name', '?')} | {p} | {ev if isinstance(ev, str) else json.dumps(ev, ensure_ascii=False)} |")
    return rows


def _thesis_brief(workdir: Path) -> str:
    path = workdir / "valuation" / "valuation-notes.md"
    if not path.exists():
        return ""
    text = read(path)
    lines = text.splitlines()
    for s in sections(text):
        if "thesis brief" in s.title.lower():
            body = "\n".join(lines[s.start + 1:s.end]).strip()
            return re.sub(r"^(#{1,6})\s", lambda m: "#" * max(len(m.group(1)), 4) + " ", body, flags=re.M)
    return ""


def explain_issue(issue: Dict, brief: Dict) -> str:
    """Deterministic diagnoses for checker findings whose cause is mechanical; else the protocol default."""
    code, detail = issue.get("code", ""), issue.get("detail", "") or ""
    if code == "EPS_RECONCILIATION_MISMATCH":
        m = re.search(r"expected=(-?[\d.e+-]+), provided=(-?[\d.e+-]+)", detail)
        if m:
            try:
                ratio = float(m.group(2)) / float(m.group(1))
            except (ValueError, ZeroDivisionError):
                ratio = 0
            ccy = brief.get("currency") or "元"
            for k, unit in ((1e3, "千"), (1e6, "百万")):
                if abs(ratio / k - 1) < 0.02:
                    return f"单位约定差异：净利润列以{unit}{ccy}计、EPS 列以{ccy}/股计，检查器同单位相除差 {k:,.0f} 倍；换算后一致，非数字错误"
    if code == "REPORT_AI_CAPEX_NOT_SPLIT" and not re.search(r"semiconductor|internet|saas|hardware|telecom",
                                                             str(brief.get("industry", ""))):
        return f"关键词触发：行业附录为 {brief.get('industry')}，报告不涉及 AI/云/数据中心资本开支拆分，不适用"
    if code in ("FORENSIC_DSO_DIVERGENCE", "FORENSIC_MSCORE_INFO", "FORENSIC_ELEVATED_ACCRUALS", "FORENSIC_CASH_CONVERSION_DECLINING"):
        return "公司层面质量信号（非报告缺陷），已由第五章 5.2 财报质量核查与可信度等级承接"
    return "P2/P3 按协议记录，未强改"


def appendix(workdir: Path, brief: Dict, chk: CheckerResult, lint_issues: List[Tuple[str, str]],
             explanations: Dict[str, str]) -> str:
    en = brief.get("language") == "en"
    conf_rel = latest_assumptions(workdir)
    conf = read_json(workdir / conf_rel)
    label = V.dcf_label(read(workdir / latest_dcf_output(workdir))) or {}
    src = _ledger_source_section(workdir) or _fallback_sources(workdir)
    disp_rows = []
    for i in chk.issues:
        key = f"{i.get('code')}|{i.get('file', '')}|{i.get('message', '')[:40]}"
        disp = explanations.get(i.get("code", ""), explanations.get(key, explain_issue(i, brief)))
        disp_rows.append(f"| {i.get('severity')} | {i.get('code')} | {disp} |")
    lint_rows = [f"| {c} | {explanations.get(c, '显式解释：见下')} | {m[:90]} |" for c, m in lint_issues]
    counts = " ".join(f"{k}={v}" for k, v in chk.counts.items())
    sc_rows = _scenario_rows(conf)
    if en:
        h = ["## Appendix", "### Sources and timestamps", "### Key valuation assumptions and checker summary",
             "### Disclaimer: not investment advice"]
    else:
        h = ["## 附录", "### 附录 A：数据来源与时间戳清单", "### 附录 B：估值关键假设摘要",
             "### 附录 C：检查器结果摘要（P0/P1 处置状态）", "### 附录 D：免责声明"]
    out = [h[0], "", h[1], "",
           "底稿＝`forensic/ledger.md` 对账台账（W2 产物；Tier 1＝监管披露/审计数，Tier 2＝官方统计与交易所行情，"
           "Tier 3＝权威数据库，Tier 4＝数据商快照，Tier 5＝媒体与转述链）。各条目以自身时间戳为准。", "", src, ""]
    out += [h[2], "", f"摘自 `{conf_rel}`（dcf.py 配置）与 `valuation/valuation-notes.md`；脚本复算："
                      f"`PYTHONUTF8=1 python <skill_root>/scripts/dcf.py --config {conf_rel}`。", "",
            "| 输入 | 值 |", "|---|---|",
            f"| 现价 price | {conf.get('price')} |", f"| 股本 shares | {conf.get('shares')} |",
            f"| 净债务 net_debt | {conf.get('net_debt')} |", f"| WACC | {conf.get('wacc')} |",
            f"| 永续增长 terminal_g | {conf.get('terminal_g')} |",
            f"| 综合区间 [range_low, range_high] | [{conf.get('range_low')}, {conf.get('range_high')}] |", ""]
    if sc_rows:
        out += ["| 情景 | 概率 | 证据强度 |", "|---|---|---|", *sc_rows, ""]
    if label:
        out += [f"脚本标定行（逐字）：`{label.get('line', '')}`", ""]
    tb = _thesis_brief(workdir)
    if tb:
        out += ["**Thesis brief（valuation-notes 原文）**", "", tb, ""]
    if not en:
        out += [h[3], ""]
    out += [f"**研究输出检查器**（`check_research_output.py`，{now()}，终稿复跑）：{counts}。", ""]
    if disp_rows:
        out += ["| 级别 | 代码 | 处置与说明 |", "|---|---|---|", *disp_rows, ""]
    lint_line = "通过" if not lint_issues else f"{len(lint_issues)} 项（显式解释，非静默）"
    out += [f"**契约 lint**（`lint_contract.py`）：{lint_line}。", ""]
    if lint_rows:
        out += ["| 代码 | 处置 | 原文 |", "|---|---|---|", *lint_rows, ""]
    out += [h[-1], "", DISCLAIMER_EN if en else DISCLAIMER_ZH.format(cutoff=brief.get("data_cutoff", brief.get("created")))]
    return "\n".join(out).rstrip() + "\n"


DISCLAIMER_ZH = (
    "本报告由自动化研究流水线生成，仅供研究参考，**不构成任何投资建议、证券要约或买卖招揽**。撰写方非持牌投资顾问，"
    "报告未考虑任何特定读者的投资目标、财务状况与风险承受能力。报告依据的公开资料采集与核验时点为 {cutoff}"
    "（各条目以自身时间戳为准），其后的信息变化不另行更新；Tier 4/5 来源可靠性低于 Tier 1 披露文件。"
    "估值区间、情景概率与预测均为基于既定假设的模型输出，不构成对未来股价的承诺。读者应独立判断并自行承担投资决策责任。")
DISCLAIMER_EN = (
    "Generated by an automated research pipeline for research reference only. **Not investment advice**, not an offer or "
    "solicitation. The author is not a licensed adviser. Valuation ranges, scenario probabilities and forecasts are model "
    "outputs under stated assumptions, not promises about future prices.")
