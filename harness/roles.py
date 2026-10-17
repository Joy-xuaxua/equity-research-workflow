"""Per-agent preload manifests, harness-mode addenda and task texts.

Each agent keeps its `.claude/agents/<name>.md` body verbatim as the system prompt (methodology
rules untouched). The harness appends an addendum that (a) says the must-read files are already
in the first message, (b) moves the deterministic steps to Python, (c) states the validators that
run at the handoff and (d) asks for a machine-readable HARNESS_REPORT trailer. The first message
carries `[PARAMS]`, the task and exactly the files / reference sections that agent's must-read
list names — so it can work in a few turns instead of one Read per turn.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .config import INDUSTRIES, REFS, SCRIPTS, SKILL_ROOT
from .docs import Doc, extract, keep_level2, load, render_all
from .util import read, read_json, today

# ------------------------------------------------------------------------------------
# PARAMS
# ------------------------------------------------------------------------------------

PARAM_ORDER = ["workdir", "skill_root", "company", "ticker", "exchange", "mode", "language", "currency",
               "fiscal_year", "fiscal_period", "industry", "ah_listing", "cn_adr", "prior_report",
               "forecast_review", "coverage", "grade", "action_cap", "chapters", "line", "revision",
               "orch_root", "format"]


def params_block(brief: Dict, gates: Dict, **extra) -> str:
    vals = {k: brief.get(k) for k in PARAM_ORDER if k in brief}
    if brief.get("mode") != "earnings":
        vals.pop("fiscal_year", None)
        vals.pop("fiscal_period", None)
    vals.pop("orch_root", None)
    vals.pop("format", None)
    if gates.get("grade"):
        vals["grade"] = gates["grade"]
        vals["action_cap"] = gates.get("action_cap") or "none"
    vals.update({k: v for k, v in extra.items() if v is not None})
    lines = ["[PARAMS]"]
    for k in PARAM_ORDER:
        if k in vals and vals[k] not in (None, ""):
            v = vals[k]
            lines.append(f"{k}={str(v).lower() if isinstance(v, bool) else v}")
    return "\n".join(lines)


# ------------------------------------------------------------------------------------
# Doc helpers
# ------------------------------------------------------------------------------------

def ref(name: str, ids: Sequence[str] = (), titles: Sequence[str] = (), scope: str = "") -> Optional[Doc]:
    return load(REFS / name, f"<skill_root>/references/{name}", ids, titles, scope)


def industry_docs(brief: Dict, ids: Sequence[str] = ()) -> List[Optional[Doc]]:
    slugs = [s.strip() for s in str(brief.get("industry", "")).split(",") if s.strip()]
    return [load(INDUSTRIES / f"{s}.md", f"<skill_root>/industries/{s}.md", ids) for s in slugs]


def wd(workdir: Path, rel: str, scope: str = "全文") -> Optional[Doc]:
    p = workdir / rel
    return Doc(rel, scope, read(p)) if p.exists() else None


def reconciled(workdir: Path, lines: Sequence[str], keep: Sequence[str] = ("发现", "冲突", "未获取到"),
               scope: str = "发现/冲突/未获取到＋裁决戳（跳过指标登记与原文附录）") -> List[Optional[Doc]]:
    out: List[Optional[Doc]] = []
    rdir = workdir / "reconciled-collection"
    for ln in lines:
        hit = sorted(rdir.glob(f"{ln}-*.md"))
        if hit:
            out.append(Doc(f"reconciled-collection/{hit[0].name}", scope, keep_level2(read(hit[0]), keep)))
    return out


def template_sections(brief: Dict, chapter_ids: Sequence[str]) -> Optional[Doc]:
    """full: report-template.md preamble + §<CN numeral>; earnings: earnings-mode.md §6 subsections."""
    if brief.get("mode") == "earnings":
        return ref("earnings-mode.md", chapter_ids, scope="§" + "/".join(chapter_ids) + "（节选）")
    text = read(REFS / "report-template.md")
    pre = text.split("\n## ", 1)[0]
    body = extract(text, chapter_ids)
    return Doc("<skill_root>/references/report-template.md", "引言＋§" + "/".join(chapter_ids) + "（节选）", pre + "\n\n" + body)


def industry_kpi_rule(brief: Dict) -> str:
    """The checker's REPORT_INDUSTRY_KPI_MISSING rule, stated up front so W8 does not bounce it back."""
    rules = read_json(REFS / "industry-rules.json")["industries"]
    out = []
    for slug in [s.strip() for s in str(brief.get("industry", "")).split(",") if s.strip()]:
        for g in rules.get(slug, {}).get("required_groups", []):
            out.append(f"「{g['label']}」（表格中出现任一术语即可：{'、'.join(g.get('terms', [])[:8])}）")
    return "；".join(out)


# ------------------------------------------------------------------------------------
# Addendum (system-prompt suffix)
# ------------------------------------------------------------------------------------

def addendum(workdir: Path, scripts: str, validators: str, report_schema: str, extra: str = "") -> str:
    return f"""---
## Harness 运行模式（本节由 Python harness 追加；覆盖上文中与之冲突的“流程”指令——方法论与纪律条款一律照旧）

1. **必读文件已预载**：首条消息里的 `<file path=… scope=…>` 块逐字附上了你「必读清单」与输入数据中本任务所需的文件（或标注的节选）。视同你已按序读完：**不要再用 Read 读取已预载的内容**。仅当需要预载之外的文件、或某块是「节选」而你确需其他节时，才用 Read/Grep 回退（用 offset/limit 只取所需片段）。
2. **少回合**：彼此独立的工具调用放在同一回合并行发出（例如一次回复里同时 Write 全部输出文件）；写完不必 Read 回来核对——harness 会校验。
3. **确定性步骤归 harness**：{scripts}
4. **交接校验**：你结束后 harness 立即运行校验器：{validators}。不通过时会在**同一会话**把校验结果发回给你——只修被点名的问题。
5. **回报**：照你的「回报格式」写小结，末尾追加一个 ```json 代码块（HARNESS_REPORT，合法 JSON，harness 据此做门禁与派发）：
{report_schema}
6. 环境：工作目录 `{workdir.as_posix()}`（相对路径均相对于此）；Windows，Bash 为 Git Bash，运行 python 加 `PYTHONUTF8=1`；今天 {today()}。
{extra}""".rstrip()


def first_message(params: str, task: str, docs: Sequence[Optional[Doc]], notes: str = "") -> str:
    parts = [params, "", task]
    if notes:
        parts += ["", notes]
    parts += ["", "以下为预载文件（视同已读）：", "", render_all(docs)]
    return "\n".join(parts)


@dataclass
class Spec:
    agent: str
    prompt: str
    addendum: str
    tools: Optional[List[str]] = None
    max_turns: int = 40


# ------------------------------------------------------------------------------------
# W1 collector (dispatch kept; redesign with PDF pre-extraction = Phase 2)
# ------------------------------------------------------------------------------------

REQ_SECTIONS = {
    "full": {"01": ["1.1", "1.2", "1.3"], "02": ["2.1"], "03": ["3.1"], "04": ["4.1"]},
    "earnings": {"01": ["1"], "02": ["2.2"], "03": ["3.2"], "04": ["4.2"]},
}


def collector(workdir: Path, brief: Dict, gates: Dict, line: str) -> Spec:
    mode = brief.get("mode", "full")
    ids = ["0", *REQ_SECTIONS[mode][line[:2]]]
    if brief.get("ah_listing") or brief.get("cn_adr"):
        ids.append("5")
    if brief.get("industry"):
        ids.append("6")
    docs = [ref("data-sources.md"), ref("data-requirements.md", ids), ref("collision-metrics.json")]
    if mode == "earnings":
        docs.append(ref("earnings-mode.md", ["3"]))
    if brief.get("ah_listing") or brief.get("cn_adr"):
        docs.append(ref("markets-cn-hk.md"))
    task = f"执行 W1 采集：本线 line={line}。落盘 `collection/{line}.md`（含「## 指标登记」行式 YAML 块：每条 `- key: …` 起、字段逐行缩进，不用 flow-style `{{…}}`）。"
    add = addendum(workdir,
                   "登记块格式与锚唯一性由 harness 校验器检查（同时检查 key/单位/期间是否符合 collision-metrics.json）。",
                   "登记块可被 collision_check 行式解析、key 在清单内且归属本线、单位可解析、anchor 在正文唯一",
                   '{"line": "<line>", "file": "collection/<line>.md", "registered": <条数>, "not_obtained": ["…"], "conflicts": <条数>, "escalations": ["…"]}')
    return Spec("equity-data-collector", first_message(params_block(brief, gates, line=line), task, docs), add)


# ------------------------------------------------------------------------------------
# G1 industry classification (small tool-less call)
# ------------------------------------------------------------------------------------

def g1(workdir: Path, brief: Dict) -> Spec:
    coll = workdir / "collection"
    d01 = sorted(coll.glob("01-*.md"))
    d04 = sorted(coll.glob("04-*.md"))
    docs = [ref("industry-routing.md", ["1", "2"])]
    if d01:
        t = read(d01[0])
        biz = extract(t, titles=[x for x in ("分部", "业务", "收入", "Business", "核心台账")])
        docs.append(Doc(f"collection/{d01[0].name}", "业务描述相关节", biz or keep_level2(t, ["发现"])))
    if d04:
        docs.append(Doc(f"collection/{d04[0].name}", "发现节", keep_level2(read(d04[0]), ["发现"])))
    slugs = sorted(p.stem for p in INDUSTRIES.glob("*.md"))
    task = ("执行 G1 行业分类（原编排者职责，现由你一次性完成，无需工具）：按 industry-routing.md §1–2 选**一个主附录**，"
            "仅当次业务改变 KPI/模型/估值方法时加一个次附录。只输出以下三部分，不要别的：\n"
            "主附录: <slug>\n次附录: <slug|none>\n理由：≤5 行\n"
            f"可选 slug：{', '.join(slugs)}")
    sysp = "你是投研流水线的行业分类员。只依据预载材料判断主利润池并按路由矩阵选附录。"
    return Spec("__inline__", first_message(params_block(brief, {}), task, docs), sysp, tools=[], max_turns=2)


# ------------------------------------------------------------------------------------
# W2 reconciler
# ------------------------------------------------------------------------------------

W2_SCHEMA = '{"csv_rows": <int>, "periods": ["FY…"], "conflicts": {"resolved": <n>, "dual": <n>, "pending": <n>}, "key_adjudication": "…", "data_gaps": ["…"], "escalations": ["…"]}'


def reconciler(workdir: Path, brief: Dict, gates: Dict, registry_report: str, rerun_issues: str = "") -> Spec:
    mode = brief.get("mode", "full")
    docs: List[Optional[Doc]] = [ref("data-sources.md", ["7", "8"]), ref("collision-metrics.json"), ref("derived-metrics.json")]
    if mode == "earnings":
        docs.append(ref("earnings-mode.md", ["4"], scope="§4（引导段＋子节）"))
    if brief.get("ah_listing") or brief.get("cn_adr"):
        docs.append(ref("markets-cn-hk.md", ["4", "5"]))
    coll = workdir / "collection" if (workdir / "collection").is_dir() else workdir / "collection-deprecated"
    for p in sorted(coll.glob("*.md")):
        docs.append(Doc(f"{coll.name}/{p.name}", "全文", read(p)))
    docs.append(wd(workdir, "forensic/collision-report.txt", "全文（harness 已运行 collision_check.py，原始产出）"))
    docs.append(Doc(".harness/registry-check.txt", "全文（harness 登记块校验）", registry_report))
    if rerun_issues:
        for rel in ("forensic/ledger.md", "forensic/adjudications.json", "forensic/financials.csv", "forensic/derived-inputs.json"):
            docs.append(wd(workdir, rel, "全文（上一轮产物，就地更新）"))
        task = ("执行 W2 补轮对账（W3 疑点重派，一轮）：针对下列疑点回源核验/补录/裁决，就地更新 ledger.md、financials.csv、"
                "adjudications.json、derived-inputs.json（Cxx 续编不重排）。疑点清单：\n" + rerun_issues)
    else:
        task = "执行 W2 对账：通读原料与对撞候选，完成对账四步裁决，写出 ledger.md、financials.csv、adjudications.json、derived-inputs.json。"
    scripts = ("collision_check.py 已由 harness 运行，原始报告即预载的 forensic/collision-report.txt（勿重跑、勿手改）；登记块校验结果见预载 "
               ".harness/registry-check.txt。你写完四个文件（forensic/ledger.md、forensic/financials.csv、forensic/adjudications.json、"
               "forensic/derived-inputs.json）后，harness 依次运行：check_research_output.py --financials（→ forensic/checker-financials.txt）、"
               "基准三元组自验（ledger §1「市值」行 vs derived-inputs 的 price_close×shares_outstanding）、reconcile_merge.py"
               "（→ reconciled-collection/，并把 collection/ 移入 collection-deprecated/）、derive_metrics.py（→ derived.csv / derived-summary.md），"
               "再把 derived-summary.md 原样并入 ledger §2.x「派生指标摘要」。**你不运行这些脚本，也不要自己写 §2.x 派生指标摘要小节。**"
               "（动作 2、6、8、10②–④ 由 harness 执行；动作 1、3、4、5、7、9、10① 归你。）")
    validators = ("financials.csv 列齐全与深度（lint 同源）；adjudications.json schema（reconcile_merge 同源）与锚——reconcile_merge P1；"
                  "derived-inputs 锚逐字出现在 ledger（derive_metrics fail-loud）；市值＝现价×总股本（±1%）")
    extra = ("7. ledger §4 末节请命名为「来源清单底稿」，直接写成 `| 数据项 | 来源（Tier） | 时间 |` 表格——harness 原样用作报告附录 A。\n"
             "8. derived-inputs.json 必须含最新期 `price_close` 与 `shares_outstanding`（总股本）——基准三元组自验与市值类派生指标依赖。")
    return Spec("equity-data-reconciler", first_message(params_block(brief, gates), task, docs),
                addendum(workdir, scripts, validators, W2_SCHEMA, extra), max_turns=50)


# ------------------------------------------------------------------------------------
# W3 forensic accountant
# ------------------------------------------------------------------------------------

W3_SCHEMA = ('{"grade": "A|B|C|D", "veto_action": null, "acceptance": "pass|fail", '
             '"escalations": [{"id": "E1", "severity": "高|中|低", "issue": "…", "needs_w2": true}]}')


def forensic(workdir: Path, brief: Dict, gates: Dict, handoff_note: str) -> Spec:
    docs: List[Optional[Doc]] = [ref("forensic-accounting.md"), wd(workdir, "forensic/ledger.md"),
                                 wd(workdir, "forensic/financials.csv"), wd(workdir, "forensic/checker-financials.txt")]
    docs += reconciled(workdir, ["01"], ("发现", "冲突", "未获取到", "原文附录"), "发现/冲突/未获取到/原文附录＋裁决戳（跳过指标登记）")
    docs += reconciled(workdir, ["02", "03", "04"])
    docs += industry_docs(brief, ["9"] + (["7"] if brief.get("mode") == "earnings" else []))
    if brief.get("mode") == "earnings":
        docs.append(ref("earnings-mode.md", ["4.2", "4.3", "8"]))
    if brief.get("ah_listing") or brief.get("cn_adr"):
        docs.append(ref("markets-cn-hk.md", ["4", "8"]))
    docs += [wd(workdir, "forensic/derived.csv"), wd(workdir, "forensic/derived-inputs.json")]
    task = "执行 W3 财报质量核查：交接验收（见下）→ 五项 forensic 检查 → A–D 评级，写 quality/earnings-quality.md 与 quality/grade.json。"
    scripts = ("交接验收 ①（financials.csv 列齐全/期间深度）与 ③（ledger §2.x ↔ derived-summary.md 逐字一致——该小节由 harness 脚本并入）"
               "已由 harness 用代码完成，结果见首条消息；你只做 ②（ledger↔CSV 抽查 3 行）。应计/M-Score 以预载 checker-financials.txt 为准。")
    validators = ("grade.json schema（grade∈A–D、veto_action 与等级一致、summary 非空、generated=YYYY-MM-DD HH:MM）；"
                  "earnings-quality.md 等级一致性——lint 对**每一行含「可信度」或「等级」的文字**提取孤立的 A–D 字母，"
                  "该行出现最终等级以外的任何字母都判 GRADE_MISMATCH（否定语境「不构成 D」、裁决编号「C19」同样计入）："
                  "这类行只写最终等级字母，其他等级用文字描述（如「未达最低档」）")
    extra = "7. 回报 JSON 的 escalations：needs_w2=true 且 severity 为 高/中 的条目会触发 harness 重派 W2 一轮（附你的疑点清单），之后你会在同一会话收到复核请求。"
    return Spec("equity-forensic-accountant",
                first_message(params_block(brief, gates), task, docs, "【harness 交接验收结果】\n" + handoff_note),
                addendum(workdir, scripts, validators, W3_SCHEMA, extra))


# ------------------------------------------------------------------------------------
# W4 chapter writers
# ------------------------------------------------------------------------------------

# chapters → (template section ids, industry-appendix section ids, reconciled lines, extra refs)
WRITER_FULL = {
    "2+3": (["二", "三"], ["3", "4", "8"], ["01", "03", "04"], []),
    "4":   (["四"], ["9"], ["01", "03"], []),
    "5":   (["五"], ["5", "9"], ["01"], []),
    "7":   (["七"], ["6"], ["02", "03"], [("expectations-investing.md", ["2"])]),
    "8":   (["八"], ["7", "9"], ["02", "03", "04"], [("industry-routing.md", ["4"])]),
}
WRITER_EARNINGS = {
    "2":   (["二", "4.1"], ["7"], ["01", "02", "03"], []),
    "3+4": (["三", "四", "4.2", "4.3"], ["4", "7"], ["01", "03"], []),
    "5":   (["五"], ["9"], ["01"], []),
    "6":   (["六", "4.4"], ["7"], ["02", "03"], []),
    "7":   (["七", "4.5"], ["6"], ["04", "02"], []),
}
CHAPTER_FILES = {
    "full": {2: "ch02-business.md", 3: "ch03-competition.md", 4: "ch04-governance.md", 5: "ch05-financials.md",
             7: "ch07-analyst-view.md", 8: "ch08-catalysts.md"},
    "earnings": {2: "ch02-expectations-gap.md", 3: "ch03-revenue.md", 4: "ch04-margins.md", 5: "ch05-cashflow.md",
                 6: "ch06-guidance.md", 7: "ch07-market-reaction.md"},
}
W4_SCHEMA = ('{"files": ["chapters/…"], "not_obtained": {"chNN": <项数>}, "data_gaps": ["…"], '
             '"critical_gaps": ["仅列使本章核心结论无法成立的缺口（触发定向补采）"], "escalations": ["…"]}')


def writer(workdir: Path, brief: Dict, gates: Dict, chapters: str) -> Spec:
    mode = brief.get("mode", "full")
    tmpl_ids, ind_ids, lines, extras = (WRITER_EARNINGS if mode == "earnings" else WRITER_FULL)[chapters]
    docs: List[Optional[Doc]] = [template_sections(brief, tmpl_ids), ref("output-format.md")]
    docs += industry_docs(brief, ["1", "4", "10", *ind_ids])
    for name, ids in extras:
        docs.append(ref(name, ids))
    if "4" in chapters.split("+") and brief.get("cn_adr"):
        docs.append(ref("markets-cn-hk.md", ["8"]))
    docs += [wd(workdir, "brief.json"), wd(workdir, "forensic/ledger.md"), wd(workdir, "forensic/financials.csv"),
             wd(workdir, "forensic/derived.csv")]
    nums = [int(x) for x in chapters.split("+")]
    if any(n in (4, 5) for n in nums) or mode == "earnings":
        docs.append(wd(workdir, "quality/earnings-quality.md"))
    docs.append(wd(workdir, "quality/grade.json"))
    docs += reconciled(workdir, lines)
    if brief.get("prior_report", "none") != "none" and 8 in nums:
        p = Path(brief["prior_report"])
        if p.exists():
            docs.append(Doc(p.as_posix(), "旧报告 8.1 预测登记节", extract(read(p), ["8.1"]) or read(p)))
    files = [f"chapters/{CHAPTER_FILES[mode][n]}" for n in nums]
    task = f"执行 W4 章节写作：chapters={chapters}，写出 {'、'.join(files)}（每章一个文件，同一回合并行 Write）。"
    validators = ("每章首非空行 `## <模板章节名>`、次非空行「本章要点：」、文件尾注 `<!-- data-gaps: … -->`（lint 同源）"
                  + ("；ch05 同 W3 的等级字母规则：含「可信度/等级」的行只出现最终等级字母" if 5 in nums else ""))
    kpi = industry_kpi_rule(brief)
    extra = (f"7. W8 检查器按行业附录验表格 KPI（缺任一组即 P1 回炉）：全报告表格须覆盖 {kpi}。与本章相关的组请在本章表格中用这些术语出现。"
             if kpi else "")
    return Spec("equity-chapter-writer", first_message(params_block(brief, gates, chapters=chapters), task, docs),
                addendum(workdir, "组稿（剥离 data-gaps 尾注后拼接）由 harness 完成；你只写章节文件。", validators, W4_SCHEMA, extra))


# ------------------------------------------------------------------------------------
# W5 valuation (first round and G3 revision)
# ------------------------------------------------------------------------------------

W5_SCHEMA = ('{"label": "<dcf.py 标定行标签，逐字>", "range": [<L>, <H>], "price": <现价>, "gap": "偏多|偏空|中性", '
             '"scenarios": [{"name": "bear", "p": 0.4, "strength": "中"}], "wacc": <x>, "terminal_g": <x>, '
             '"dcf_fix_attempts": <n>, "data_gaps": ["…"], "escalations": ["…"]}')


def valuation(workdir: Path, brief: Dict, gates: Dict, revision: bool = False) -> Spec:
    mode = brief.get("mode", "full")
    vch = "ch08-valuation.md" if mode == "earnings" else "ch06-valuation.md"
    dcf_src = Doc("<skill_root>/scripts/dcf.py", "全文（配置 schema 以源码为准）", read(SCRIPTS / "dcf.py"))
    if not revision:
        docs: List[Optional[Doc]] = [
            ref("valuation-methods.md"), ref("cost-of-capital.md"), ref("base-rates.md"),
            ref("expectations-investing.md", ["1", "2"]), ref("output-format.md", ["4"]),
            template_sections(brief, ["八"] if mode == "earnings" else ["六"]),
        ]
        if mode == "earnings":
            docs.append(ref("earnings-mode.md", ["5"]))
        if brief.get("ah_listing") or brief.get("cn_adr"):
            docs.append(ref("markets-cn-hk.md", ["5", "6", "8"]))
        docs += industry_docs(brief, ["4", "5", "6", "10"])
        docs += [dcf_src, wd(workdir, "brief.json"), wd(workdir, "forensic/ledger.md"), wd(workdir, "forensic/financials.csv"),
                 wd(workdir, "forensic/derived.csv"), wd(workdir, "quality/grade.json"), wd(workdir, "quality/earnings-quality.md")]
        for pat in ("ch03-*.md", "ch04-*.md"):
            hit = sorted((workdir / "chapters").glob(pat))
            if hit:
                docs.append(wd(workdir, f"chapters/{hit[0].name}"))
        anchor_line = "02" if mode == "earnings" else "03"
        docs += reconciled(workdir, [anchor_line], ("发现", "指标登记"), "发现＋指标登记节（可选锚定输入）")
        task = (f"执行 W5 估值（revision=false）：构建 valuation/assumptions.json → Bash 运行 dcf.py 落盘 valuation/dcf-output.txt → "
                f"写 chapters/{vch} 与 valuation/valuation-notes.md（thesis brief 置于开头）。")
        if gates.get("grade") == "D":
            task += " grade=D：估值章按否决重构（「估值在可信度恢复前无意义」为主结论）。"
        out_cfg, out_txt = "valuation/assumptions.json", "valuation/dcf-output.txt"
    else:
        docs = [ref("valuation-methods.md", ["5", "8", "9"]), ref("output-format.md", ["4"]), dcf_src,
                wd(workdir, "redteam/redteam-feedback.md"), wd(workdir, "redteam/redteam-findings.json"),
                wd(workdir, "valuation/assumptions.json"), wd(workdir, "valuation/dcf-output.txt"),
                wd(workdir, "valuation/valuation-notes.md"), wd(workdir, f"chapters/{vch}"), wd(workdir, "quality/grade.json")]
        task = ("执行 W5 修正轮（revision=true，G3 触发）：逐条吸收下列红队中强/强发现，输出 valuation/assumptions.v2.json 与 "
                "valuation/dcf-output.v2.txt（**不覆盖** v1），valuation-notes.md 追加「修正轮」节（变化前后对照），更新 "
                f"chapters/{vch}。G3 指令：\n{gates.get('g3_instructions', '')}")
        out_cfg, out_txt = "valuation/assumptions.v2.json", "valuation/dcf-output.v2.txt"
    scripts = (f"dcf.py 仍由你用 Bash 运行（`PYTHONUTF8=1 python <skill_root>/scripts/dcf.py --config {out_cfg} > {out_txt} 2>&1`），"
               "自修 ≤3 次；harness 事后对同一配置复跑 dcf.py 并逐行比对你落盘的输出。")
    validators = (f"{out_txt} 必须等于 dcf.py 对 {out_cfg} 的复跑输出（未设 montecarlo.seed 时蒙特卡洛块除外）且含「=== 标定 ===」行；"
                  f"chapters/{vch} 契约（标题/本章要点/data-gaps）；valuation-notes.md 含 thesis brief 节且逐字出现脚本标定标签"
                  + ("；v1 文件哈希不变；notes 含「修正轮」节" if revision else ""))
    return Spec("equity-valuation-analyst",
                first_message(params_block(brief, gates, revision=str(revision).lower()), task, docs),
                addendum(workdir, scripts, validators, W5_SCHEMA), max_turns=50)


# ------------------------------------------------------------------------------------
# W6 red team
# ------------------------------------------------------------------------------------

SIDECAR_SCHEMA = """{
  "generated": "YYYY-MM-DD HH:MM",
  "three_questions": {"q1": "已答|答非所问|未答", "q2": "…", "q3": "…", "verdict": "通过|不通过"},
  "findings": [
    {"id": "R1", "statement": "一句话", "strength": "弱|中|中强|强",
     "targets": ["回写目标，取值示例：情景概率 / 标定 / 估值假设 / ch1 风险 / ch9 动作节奏 / ch3 事实"],
     "evidence": "来源+时间戳"}
  ],
  "consistency": {"label_matches_dcf": true, "gap_consistent": true, "veto_chain_ok": true, "probabilities_match_evidence": true, "notes": "…"},
  "revision_recommended": true,
  "forecast_review": "none|produced"
}"""


def redteam(workdir: Path, brief: Dict, gates: Dict) -> Spec:
    docs = [ref("expectations-investing.md", ["3"]), ref("valuation-methods.md", ["9"]), ref("base-rates.md", ["5"]),
            ref("data-sources.md", ["0", "10"]), wd(workdir, "draft/report-draft.md"), wd(workdir, "valuation/valuation-notes.md"),
            wd(workdir, "valuation/dcf-output.txt"), wd(workdir, "quality/grade.json"), wd(workdir, "quality/earnings-quality.md")]
    fr = brief.get("prior_report", "none") != "none"
    if fr and Path(brief["prior_report"]).exists():
        docs.append(Doc(Path(brief["prior_report"]).as_posix(), "旧报告 8.1 预测登记节", extract(read(Path(brief["prior_report"])), ["8.1"])))
    task = ("执行 W6 红队：三问 → pre-mortem → web 反证搜索 → 一致性核对" + ("→ 预测复盘" if fr else "") +
            "；写 redteam/redteam-feedback.md 与机读旁车 redteam/redteam-findings.json（同一回合并行 Write）。")
    scripts = ("G3 仲裁由 harness 读 redteam/redteam-findings.json 用代码执行：任一 中强/强 发现的 targets 含 情景概率/标定/估值假设 → "
               "估值修正轮；含 chN（N=2–8）→ 该章写手回写；其余 → W7 结论回写；consistency 任一为 false → 修正轮必开。")
    validators = ("旁车 schema（三问 verdict、findings 的 id=R<n>/strength∈{弱,中,中强,强}/targets 非空、consistency 四个布尔）；"
                  "旁车与 redteam-feedback.md 发现清单表格逐条一致（表格行以 `| R<n> |` 开头、强度列逐字相同）")
    extra = f"7. 旁车 `redteam/redteam-findings.json` 的 schema：\n```json\n{SIDECAR_SCHEMA}\n```\n8. web 抓取优先用 mcp__web_reader__webReader（若可用），否则 WebFetch；WebSearch 在本机代理上可能报错，失败即换路，不阻塞。"
    params = params_block(brief, gates, forecast_review="expected" if fr else "none")
    return Spec("equity-red-team", first_message(params, task, docs),
                addendum(workdir, scripts, validators, '{"three_q": "通过|不通过", "counts": {"弱": 0, "中": 0, "中强": 0, "强": 0}, "revision_recommended": true}', extra),
                max_turns=50)


# ------------------------------------------------------------------------------------
# W7 verdict
# ------------------------------------------------------------------------------------

W7_SCHEMA = ('{"status": "ok|contradiction", "label": "<逐字>", "action": "…", "range": [<L>, <H>], "gap": "…", '
             '"writeback_ids": ["R1"], "contradictions": [{"a": "…", "b": "…", "source": "…"}], "data_gaps": ["…"]}')


def verdict(workdir: Path, brief: Dict, gates: Dict, dcf_rel: str) -> Spec:
    mode = brief.get("mode", "full")
    tmpl = template_sections(brief, ["一", "九"])
    docs: List[Optional[Doc]] = [ref("output-format.md", ["1", "7"]), ref("expectations-investing.md", ["2"]),
                                 ref("valuation-methods.md", ["9"]), tmpl, wd(workdir, "brief.json"),
                                 wd(workdir, dcf_rel, "全文（最新轮；标定行是标签唯一来源）"), wd(workdir, "valuation/valuation-notes.md"),
                                 wd(workdir, "quality/grade.json"), wd(workdir, "quality/earnings-quality.md"),
                                 wd(workdir, "redteam/redteam-feedback.md"), wd(workdir, "redteam/redteam-findings.json")]
    if (workdir / "redteam" / "forecast-review.md").exists():
        docs.append(wd(workdir, "redteam/forecast-review.md"))
    for pat in ("ch03-*.md", "ch05-*.md", "ch07-*.md", "ch08-valuation.md" if mode == "earnings" else "ch06-*.md"):
        hit = sorted((workdir / "chapters").glob(pat))
        if hit:
            docs.append(wd(workdir, f"chapters/{hit[0].name}"))
    fr = "redteam/forecast-review.md" if (workdir / "redteam" / "forecast-review.md").exists() else "none"
    task = (f"执行 W7 结论：写 chapters/ch01-summary.md 与 chapters/ch09-conclusion.md（同一回合并行 Write）。估值输入取最新轮 `{dcf_rel}`。"
            f"G3 回写清单（须在 ch9 回写映射表逐条落实）：\n{gates.get('g3_verdict', '无')}")
    validators = ("ch01/ch09 契约（标题/本章要点/data-gaps）；两章均逐字出现脚本标定标签；否决链动作上限（grade C→观望、D→规避、三问不通过→观望）"
                  "出现在 ch01 结论框；红队每条 中强/强 发现的编号（如 R1）出现在 ch09 回写映射表")
    extra = "7. 输入矛盾（硬规则 5）时：不写章节，HARNESS_REPORT 置 status=contradiction 并列 contradictions——harness 记 log 并按裁决重派。"
    params = params_block(brief, gates, forecast_review=fr)
    return Spec("equity-verdict-writer", first_message(params, task, docs),
                addendum(workdir, "组稿 F（ch1 最前、ch9 最后＋报告头）由 harness 完成。", validators, W7_SCHEMA, extra))


# ------------------------------------------------------------------------------------
# W8 deliverer (only when the checker reports P0/P1 content issues)
# ------------------------------------------------------------------------------------

W8_SCHEMA = ('{"fixed": [{"code": "…", "what": "…"}], '
             '"rework": [{"owner": "W7|W5|W4:<chapters>", "file": "chapters/…", "code": "…", "instruction": "给该 agent 的修正指令"}], '
             '"explain": [{"code": "…", "explanation": "写入附录 C 的显式解释"}]}')


def deliverer(workdir: Path, brief: Dict, gates: Dict, final_rel: str, round_no: int) -> Spec:
    docs = [ref("output-format.md", ["5", "6"]), wd(workdir, "checker/checker-output.txt"), wd(workdir, "checker/lint-output.txt"),
            wd(workdir, final_rel, "全文（终稿副本，你唯一可改的文件）")]
    task = (f"执行 W8 P0/P1 处置（第 {round_no} 轮，≤2 轮）：harness 已跑完 lint 与检查器（输出见预载），终稿副本为 `{final_rel}`。"
            "逐条处置每个 P0/P1：机械问题（标记拼写、表格列缺失、标题语言、格式降级）直接在终稿副本上改；内容问题（标签不一致、方法缺失、"
            "否决链违反、KPI 缺失等）不要自己编写内容——列入 rework（指明 owner 与修正指令）；确属工具误报或无法修复的列入 explain。")
    scripts = ("附录（来源/估值假设/检查器摘要/免责）、复跑检查器、md→PDF、命名均由 harness 完成；你只处置 P0/P1。"
               "chapters/ 等上游文件对你只读，rework 由 harness 派给原 owner。")
    params = params_block(brief, gates, orch_root=brief.get("orch_root"), format=brief.get("format", "pdf"))
    return Spec("equity-report-deliverer", first_message(params, task, docs),
                addendum(workdir, scripts, "harness 复跑 check_research_output.py 与 lint_contract.py", W8_SCHEMA), max_turns=30)


def doc_chars(prompt: str) -> int:
    return len(prompt)
