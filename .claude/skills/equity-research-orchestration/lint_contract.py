#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lint_contract.py — 投研流水线工作目录契约存在性检查（按波次分段）。

用法（Windows Git Bash 需 PYTHONUTF8=1）：
    PYTHONUTF8=1 python lint_contract.py <workdir> [--stage w1|w2|w3|w4|w5|w6|w7|final] [--json]

--stage 只跑「到该波次为止应已产出的产物」相关检查（累进）；默认 final＝W8 deliverer 全量终检。
编排者在每波次全部 agent 回报后、派发下一波次前跑对应 stage（SKILL.md §3「波次门槛」）：
  w1     采集线 01–04（检查 1）＋指标登记块可解析、报告条目数（检查 9，仅 w1）
  w2     ＋industry-classification（G1）、ledger、financials.csv、adjudications、reconciled-collection/
  w3     ＋grade.json、earnings-quality.md 及其等级一致
  w4     ＋章节格式、W4 写手章节齐、ch05 等级一致、A/H ch04
  w5     ＋估值四件套、估值章（A/H 同）
  w6     ＋draft/_header.md、report-draft.md（组装 D）、redteam-feedback.md
  w7     ＋ch01/ch09（A/H 同）
  final  ＋draft/report-final.md（组装 F）

检查项（缺失/不一致 → 非零退出，输出缺失清单）：
  1. 采集线文件齐（01–04，collection/ 优先、collection-deprecated/ 补缺——与 collision_check 同一定位口径），
     各含「冲突」「未获取到」小节；industry-classification.md 存在且含 主附录 行（w2 起）。
  2. chapters/ch*.md：首非空行为章节标题（# 开头），次非空行为「本章要点：」/“Key takeaways:”，尾注 data-gaps 注释存在。
  3. ah_listing=true 时分市场结论块：full→ch01/04/06/09，earnings→ch01/04/08/09，各含「分市场」或「A/H」标记。
  4. forensic/financials.csv 列齐全（deferred_revenue 可选），行数 full≥5 / earnings≥4。
  5. forensic/grade.json 可解析，grade∈{A,B,C,D}，且 veto_action 与等级一致（C→观望，D→规避）。
  6. ch05 章与 forensic/earnings-quality.md 中的可信度等级均与 grade.json 一致。
  7. 结构存在：brief.json、ledger、earnings-quality、grade.json、估值四件套（assumptions/dcf-output/valuation-notes/估值章）、
     redteam-feedback、ch01/ch09、draft/_header.md、report-draft.md、report-final.md；
     assumptions 为 schema 3 时另须 valuation/inputs.json（旧配置零影响）。
  8. 新流水线标记（forensic/adjudications.json 存在或 quality/ 目录存在）时：质量产物在 quality/（grade.json、
     earnings-quality.md）；reconciled-collection/ 含与采集原件 01–04 同名 4 文件、首 10 行含【对账后副本】头部章、
     adjudications 非空时每副本 ≥1 个 ▶ 裁决戳（兼容旧版 reconciled/ 目录名）。标记不存在（旧 workdir）按旧布局检查，零影响。
  9. （仅 w1）指标登记块：用 <skill_root>/scripts/collision_check.py 的同一解析器解析；registry 要求登记的线缺块/
     块未闭合/零条目/有 P0–P1 条目（W2 对撞会丢弃，如 flow 风格 `- {key: …}`）→ 失败；每线解析条数以 [INFO] 报告。
"""
import argparse
import collections
import csv
import glob
import importlib.util
import io
import json
import os
import re
import sys

REQUIRED_CSV_COLS = [
    "period", "revenue", "gross_profit", "operating_income", "net_income",
    "cfo", "capex", "fcf", "shares", "eps", "total_assets", "receivables",
    "ppe", "current_assets", "depreciation", "sga", "total_liabilities",
]
GRADES = {"A", "B", "C", "D"}
AH_CHAPTERS = {"full": ["01", "04", "06", "09"], "earnings": ["01", "04", "08", "09"]}
KEYLINE_RE = re.compile(r"^(本章要点：|Key takeaways:)")

STAGES = ("w1", "w2", "w3", "w4", "w5", "w6", "w7", "final")
# 章节号 → 产出波次：W4 写手 / W5 估值 agent（full ch06、earnings ch08）/ W7 verdict（ch01、ch09）
CHAPTER_STAGE = {
    "full": {"01": "w7", "02": "w4", "03": "w4", "04": "w4", "05": "w4",
             "06": "w5", "07": "w4", "08": "w4", "09": "w7"},
    "earnings": {"01": "w7", "02": "w4", "03": "w4", "04": "w4", "05": "w4",
                 "06": "w4", "07": "w4", "08": "w5", "09": "w7"},
}
CHAPTER_LABELS = {"01": "第一章（速览）", "09": "第九章（结论）"}

# 显式等级陈述：只认「可信度等级 / 最终等级 / credibility grade」后紧跟的等级字母（允许冒号、表格竖线、加粗等装饰）。
# 同行其他位置的孤立 A–D 不计入——旧版抓整行字母，「不构成 D」「C19–C21」被误报 GRADE_MISMATCH。
# 字母后紧跟字母或 /（A/B/C/D 占位）或区间（A–D）不算陈述。
GRADE_STMT_RE = re.compile(
    r"(?:可信度等级|最终等级|(?i:credibility\s+grade))"
    r"[\s*_`「“\"']*(?:[:：|=＝]|为|是|is)?[\s*_`「“\"']*"
    r"([A-D])(?![A-Za-z/])(?!\s*[–—~～-]\s*[A-D](?![A-Za-z]))"
)

ORCH_ROOT = os.path.dirname(os.path.abspath(__file__))


def read_text(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def nonempty_lines(text):
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def add(issues, code, msg):
    issues.append((code, msg))


def reached(stage, since):
    """stage 是否已到达产物 since 的产出波次（累进）。"""
    return STAGES.index(stage) >= STAGES.index(since)


COLLECTION_DIRS = ("collection", "collection-deprecated")


def collection_files(workdir):
    """采集线原件：collection/ 优先、collection-deprecated/ 补缺（同名以 collection/ 为准）。

    与 collision_check / reconcile_merge 同一定位口径：对账完成后原件被移入 collection-deprecated/；
    补采轮只重建 collection/ 单线时，其余线从弃用目录补齐。
    """
    found = {}
    for sub in reversed(COLLECTION_DIRS):  # collection/ 后扫＝同名覆盖＝优先
        for p in glob.glob(os.path.join(workdir, sub, "[0-9][0-9]-*.md")):
            found[os.path.basename(p)] = p
    return [found[k] for k in sorted(found)]


def find_collection_file(workdir, name):
    for sub in COLLECTION_DIRS:
        p = os.path.join(workdir, sub, name)
        if os.path.isfile(p):
            return p
    return None


def check_collection(workdir, stage, issues):
    if not any(os.path.isdir(os.path.join(workdir, sub)) for sub in COLLECTION_DIRS):
        add(issues, "COLLECTION_DIR_MISSING", "缺少 collection/ 目录（对账后应移入 collection-deprecated/，两者皆无）")
        return
    files = collection_files(workdir)
    nums = sorted(os.path.basename(f)[:2] for f in files)
    if nums != ["01", "02", "03", "04"]:
        add(issues, "COLLECTION_LINES_INCOMPLETE",
            f"采集线文件应为 01–04 四份，实际：{nums or '无'}")
    for f in files:
        name = os.path.relpath(f, workdir)
        text = read_text(f)
        for sec in ("冲突", "未获取到"):
            if not re.search(r"^#{2,3}\s*.*" + sec, text, flags=re.M):
                add(issues, "COLLECTION_SECTION_MISSING", f"{name} 缺「{sec}」小节")
    if not reached(stage, "w2"):
        return  # industry-classification.md 由 G1 写，W2 派发前才存在
    ic = find_collection_file(workdir, "industry-classification.md")
    if ic is None:
        add(issues, "INDUSTRY_CLASSIFICATION_MISSING",
            "缺少 industry-classification.md（collection/ 或 collection-deprecated/）")
    else:
        head = nonempty_lines(read_text(ic))[:3]
        if not any(ln.startswith("主附录:") for ln in head):
            add(issues, "INDUSTRY_CLASSIFICATION_FORMAT", "industry-classification.md 首部缺「主附录: <slug>」机读行")


def resolve_skill_root(brief):
    """skill_root：brief.json 的 skill_root（存在时）→ 本目录同级 equity-research-skill/ → 仓库根 equity-research-skill/。"""
    candidates = [
        brief.get("skill_root") or "",
        os.path.join(ORCH_ROOT, "..", "equity-research-skill"),
        os.path.join(ORCH_ROOT, "..", "..", "..", "equity-research-skill"),
    ]
    for c in candidates:
        if c and os.path.isfile(os.path.join(c, "scripts", "collision_check.py")):
            return os.path.abspath(c)
    return None


def load_collision_check(skill_root):
    path = os.path.join(skill_root, "scripts", "collision_check.py")
    spec = importlib.util.spec_from_file_location("collision_check", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_registry(workdir, mode, skill_root, issues, info):
    """W1：各采集文件「## 指标登记」块用 W2 对撞脚本的同一解析器解析，报告条目数；W2 会丢弃的条目在此即失败。"""
    if skill_root is None:
        add(issues, "REGISTRY_PARSER_UNAVAILABLE",
            "找不到 <skill_root>/scripts/collision_check.py（brief.skill_root 与默认路径均无），无法校验指标登记块")
        return
    try:
        cc = load_collision_check(skill_root)
        registry = cc.load_registry()
    except Exception as e:  # noqa: BLE001 — 解析器或清单加载失败即本项无法检查
        add(issues, "REGISTRY_PARSER_UNAVAILABLE", f"加载 collision_check / collision-metrics.json 失败：{e}")
        return
    expected = cc.expected_registry_lines(registry).get(mode, set())
    for path in collection_files(workdir):
        base = os.path.basename(path)
        name = os.path.relpath(path, workdir)
        required = base[:-3] in expected
        text = read_text(path)
        block, body = cc.extract_registry_block(text)
        if block is None:
            if not required:
                info.append(f"{name} 指标登记：无块（本线按 registry 不要求登记）")
            elif re.search(r"^##\s*指标登记\s*$", text, flags=re.M):
                add(issues, "REGISTRY_BLOCK_UNPARSEABLE",
                    f"{name} 有「## 指标登记」标题但其后无闭合的 ``` fenced 块")
            else:
                add(issues, "REGISTRY_BLOCK_MISSING", f"{name} 缺「## 指标登记」块（registry 要求本线登记）")
            continue
        entry_issues = []
        entries = cc.parse_metric_block(block, base, entry_issues)
        valid = cc.validate_entries(entries, base, body, registry, entry_issues)
        sev = collections.Counter(i.severity for i in entry_issues)
        info.append(f"{name} 指标登记：解析 {len(entries)} 条，W2 可用 {len(valid)} 条"
                    + (f"（{', '.join(f'{k}×{v}' for k, v in sorted(sev.items()))}）" if sev else ""))
        if required and not entries:
            add(issues, "REGISTRY_EMPTY", f"{name} 指标登记块解析出 0 条（registry 要求本线登记）")
            continue
        blocking = [i for i in entry_issues if i.severity in ("P0", "P1")]
        if blocking:
            codes = collections.Counter(i.code for i in blocking)
            hint = ""
            if re.search(r"^\s*-\s*\{", block, flags=re.M):
                hint = "；疑似 flow 风格 `- {key: …}`，须改为行式 `- key: x` 起条目、缩进字段逐行"
            add(issues, "REGISTRY_ENTRY_INVALID",
                f"{name} 指标登记 {len(blocking)}/{len(entries)} 条 W2 对撞会丢弃"
                f"（{', '.join(f'{k}×{v}' for k, v in codes.most_common())}）{hint}")


def check_chapters(workdir, issues):
    chdir = os.path.join(workdir, "chapters")
    if not os.path.isdir(chdir):
        add(issues, "CHAPTERS_DIR_MISSING", "缺少 chapters/ 目录")
        return
    files = sorted(glob.glob(os.path.join(chdir, "ch[0-9][0-9]-*.md")))
    if not files:
        add(issues, "CHAPTERS_EMPTY", "chapters/ 下没有任何章节文件")
    for f in files:
        name = os.path.relpath(f, workdir)
        lines = nonempty_lines(read_text(f))
        if len(lines) < 2:
            add(issues, "CHAPTER_FILE_TOO_SHORT", f"{name} 内容过短（不足标题+要点两行）")
            continue
        if not lines[0].startswith("#"):
            add(issues, "CHAPTER_HEADING_MISSING", f"{name} 首非空行不是章节标题（应以 # 开头）")
        if not KEYLINE_RE.match(lines[1] if len(lines) > 1 else ""):
            add(issues, "CHAPTER_KEYLINE_MISSING", f"{name} 次非空行不是「本章要点：」/“Key takeaways:”")
        if "<!-- data-gaps:" not in read_text(f):
            add(issues, "CHAPTER_DATAGAPS_MISSING", f"{name} 缺尾注 <!-- data-gaps: ... -->")


def check_ah(workdir, mode, ah_listing, stage, issues):
    if not ah_listing:
        return
    for nn in AH_CHAPTERS.get(mode, AH_CHAPTERS["full"]):
        if not reached(stage, CHAPTER_STAGE[mode][nn]):
            continue
        hits = glob.glob(os.path.join(workdir, "chapters", f"ch{nn}-*.md"))
        if not hits:
            add(issues, "AH_CHAPTER_MISSING", f"A/H 标的缺第 {nn} 章文件，无法核对分市场结论")
            continue
        text = read_text(hits[0])
        if not re.search(r"分市场|A/H|A\+H", text):
            add(issues, "AH_BLOCK_MISSING",
                f"{os.path.relpath(hits[0], workdir)} 缺分市场结论块（应含「分市场」或「A/H」）")


def check_financials(workdir, mode, issues):
    path = os.path.join(workdir, "forensic", "financials.csv")
    if not os.path.isfile(path):
        add(issues, "FINANCIALS_MISSING", "缺少 forensic/financials.csv")
        return
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        add(issues, "FINANCIALS_EMPTY", "financials.csv 为空")
        return
    cols = {c.strip() for c in rows[0]}
    missing = [c for c in REQUIRED_CSV_COLS if c not in cols]
    if missing:
        add(issues, "FINANCIALS_COLUMNS_MISSING", f"financials.csv 缺列：{', '.join(missing)}")
    data_rows = [r for r in rows[1:] if any(x.strip() for x in r)]
    need = 5 if mode == "full" else 4
    if len(data_rows) < need:
        add(issues, "FINANCIALS_ROWS_SHORT",
            f"financials.csv 数据行 {len(data_rows)} < 最低要求 {need}（mode={mode}）")


def check_grade(workdir, issues, new_pipeline=False):
    rel = "quality/grade.json" if new_pipeline else "forensic/grade.json"
    path = os.path.join(workdir, *rel.split("/"))
    if not os.path.isfile(path):
        add(issues, "GRADE_JSON_MISSING", f"缺少 {rel}")
        return None
    try:
        g = json.loads(read_text(path))
    except (ValueError, UnicodeDecodeError) as e:
        add(issues, "GRADE_JSON_UNPARSEABLE", f"grade.json 解析失败：{e}")
        return None
    grade = str(g.get("grade", "")).upper()
    if grade not in GRADES:
        add(issues, "GRADE_INVALID", f"grade.json 的 grade={g.get('grade')!r} 不在 {{A,B,C,D}}")
        return None
    veto = g.get("veto_action")
    expect = {"C": "观望", "D": "规避"}.get(grade)
    if expect and veto != expect:
        add(issues, "GRADE_VETO_INCONSISTENT",
            f"grade={grade} 应 veto_action={expect!r}，实际 {veto!r}")
    if not expect and veto not in (None, ""):
        add(issues, "GRADE_VETO_INCONSISTENT",
            f"grade={grade} 不应设 veto_action，实际 {veto!r}")
    return grade


def grade_statement_hits(text):
    """返回 [(行, 该行显式等级陈述的字母集合)]，只收录含显式等级陈述的行（见 GRADE_STMT_RE）。"""
    hits = []
    for line in text.splitlines():
        letters = {m.group(1) for m in GRADE_STMT_RE.finditer(line)}
        if letters:
            hits.append((line.strip(), letters))
    return hits


def check_grade_consistency(workdir, grade, issues, new_pipeline=False, stage="final"):
    if grade is None:
        return
    eq_rel = "quality/earnings-quality.md" if new_pipeline else "forensic/earnings-quality.md"
    targets = [(eq_rel, glob.glob(os.path.join(workdir, *eq_rel.split("/"))))]
    if reached(stage, "w4"):
        targets.append(("chapters/ch05-*", glob.glob(os.path.join(workdir, "chapters", "ch05-*.md"))))
    for label, hits in targets:
        if not hits:
            add(issues, "GRADE_CONSISTENCY_TARGET_MISSING", f"等级一致性核对缺文件：{label}")
            continue
        text = read_text(hits[0])
        found = grade_statement_hits(text)
        if not any(grade in letters for _, letters in found):
            add(issues, "GRADE_NOT_EMBEDDED",
                f"{os.path.relpath(hits[0], workdir)} 未发现可信度等级 {grade}（应逐字嵌入证据表）")
        for line, letters in found:
            if letters != {grade}:
                add(issues, "GRADE_MISMATCH",
                    f"{os.path.relpath(hits[0], workdir)} 等级行与 grade.json 不一致：{letters} vs {grade}｜行：{line[:60]}")


def check_structure(workdir, mode, stage, issues, new_pipeline=False):
    eq_rel = "quality/earnings-quality.md" if new_pipeline else "forensic/earnings-quality.md"
    required_files = [
        ("brief.json", "w1"),
        ("forensic/ledger.md", "w2"),
        (eq_rel, "w3"),
        ("draft/_header.md", "w6"),
        ("draft/report-draft.md", "w6"),
        ("redteam/redteam-feedback.md", "w6"),
        ("draft/report-final.md", "final"),
    ]
    if new_pipeline:
        required_files.append(("forensic/adjudications.json", "w2"))
    for rel, since in required_files:
        if reached(stage, since) and not os.path.isfile(os.path.join(workdir, rel)):
            add(issues, "FILE_MISSING", f"缺少 {rel}")
    val_nn = "06" if mode == "full" else "08"
    patterns = []
    for nn, since in sorted(CHAPTER_STAGE[mode].items()):
        label = CHAPTER_LABELS.get(nn, "估值章" if nn == val_nn else f"第 {int(nn)} 章")
        patterns.append((f"chapters/ch{nn}-*.md", label, since))
    patterns += [
        ("valuation/assumptions*.json", "估值假设 JSON", "w5"),
        ("valuation/dcf-output*.txt", "dcf.py 输出", "w5"),
        ("valuation/valuation-notes.md", "valuation-notes.md", "w5"),
    ]
    for pat, label, since in patterns:
        if reached(stage, since) and not glob.glob(os.path.join(workdir, pat)):
            add(issues, "FILE_MISSING", f"缺少 {label}（{pat}）")
    check_valuation_schema3(workdir, issues)


def check_valuation_schema3(workdir, issues):
    """schema 3 估值件（任一 assumptions*.json 含 "schema": 3）须有事实层 valuation/inputs.json；
    旧配置（无 schema 字段）零影响。"""
    for path in sorted(glob.glob(os.path.join(workdir, "valuation", "assumptions*.json"))):
        try:
            with io.open(path, encoding="utf-8") as f:
                schema = json.load(f).get("schema")
        except (ValueError, OSError):
            continue
        if schema == 3:
            if not os.path.isfile(os.path.join(workdir, "valuation", "inputs.json")):
                add(issues, "FILE_MISSING", "schema 3 估值缺少事实层 valuation/inputs.json（scripts/valuation_inputs.py 产出）")
            return


def has_new_pipeline(workdir):
    """新流水线标记：forensic/adjudications.json 存在，或 quality/ 目录存在（其一即按新布局检查）。"""
    return (os.path.isfile(os.path.join(workdir, "forensic", "adjudications.json"))
            or os.path.isdir(os.path.join(workdir, "quality")))


def check_reconciled(workdir, issues):
    """新流水线专属：reconciled-collection/ 副本与采集原件 01–04 同名、含头部章；adjudications 指向的文件须有 ≥1 个 ▶ 戳。

    兼容旧版 reconciled/ 目录名（改名前的 workdir）；采集原件定位与 check_collection 同一口径。
    """
    rdir = os.path.join(workdir, "reconciled-collection")
    if not os.path.isdir(rdir):
        rdir = os.path.join(workdir, "reconciled")  # 旧版输出目录名，向后兼容
    if not os.path.isdir(rdir):
        add(issues, "RECONCILED_MISSING", "缺少 reconciled-collection/ 目录（应由 W2 跑 reconcile_merge.py 生成）")
        return
    rname = os.path.basename(rdir)
    stamp_targets = set()
    adj_path = os.path.join(workdir, "forensic", "adjudications.json")
    if os.path.isfile(adj_path):
        try:
            adj = json.loads(read_text(adj_path))
            for rec in adj.get("adjudications", []):
                for fref in rec.get("files", []):
                    if isinstance(fref, dict) and fref.get("file"):
                        stamp_targets.add(fref["file"])
        except (ValueError, UnicodeDecodeError) as e:
            add(issues, "ADJUDICATIONS_UNPARSEABLE", f"forensic/adjudications.json 解析失败：{e}")
    for f in collection_files(workdir):
        base = os.path.basename(f)
        rel = f"{rname}/{base}"
        rfile = os.path.join(rdir, base)
        if not os.path.isfile(rfile):
            add(issues, "RECONCILED_MISSING", f"缺少 {rel}（应与采集原件同名）")
            continue
        text = read_text(rfile)
        head = nonempty_lines(text)[:10]
        if not any("【对账后副本】" in ln for ln in head):
            add(issues, "RECONCILED_HEADER_MISSING", f"{rel} 首 10 行缺【对账后副本】头部章（应由脚本生成）")
        if base in stamp_targets and not any(ln.startswith("▶ ") for ln in text.splitlines()):
            add(issues, "RECONCILED_STAMP_MISSING", f"{rel} 无任何 ▶ 裁决戳（adjudications 指向此文件）")


def lint(workdir, stage="final"):
    """跑 stage 及之前波次产物的检查，返回结果 dict（issues 为 [(code, msg)]，info 为报告行）。"""
    issues, info = [], []
    brief = {}
    brief_path = os.path.join(workdir, "brief.json")
    if os.path.isfile(brief_path):
        try:
            brief = json.loads(read_text(brief_path))
        except (ValueError, UnicodeDecodeError) as e:
            add(issues, "BRIEF_UNPARSEABLE", f"brief.json 解析失败：{e}")
    else:
        add(issues, "BRIEF_MISSING", "缺少 brief.json（无法判定 mode/ah_listing，按 full/否 处理）")

    mode = brief.get("mode", "full")
    if mode not in ("full", "earnings"):
        add(issues, "BRIEF_MODE_INVALID", f"brief.json mode={mode!r} 应为 full|earnings")
        mode = "full"
    ah_listing = bool(brief.get("ah_listing", False))
    new_pipeline = has_new_pipeline(workdir)
    grade = None

    check_collection(workdir, stage, issues)
    if stage == "w1":
        check_registry(workdir, mode, resolve_skill_root(brief), issues, info)
    if reached(stage, "w4"):
        check_chapters(workdir, issues)
    check_ah(workdir, mode, ah_listing, stage, issues)
    if reached(stage, "w2"):
        check_financials(workdir, mode, issues)
    if reached(stage, "w3"):
        grade = check_grade(workdir, issues, new_pipeline)
        check_grade_consistency(workdir, grade, issues, new_pipeline, stage)
    check_structure(workdir, mode, stage, issues, new_pipeline)
    if new_pipeline and reached(stage, "w2"):
        check_reconciled(workdir, issues)
    return {"workdir": workdir, "stage": stage, "mode": mode, "ah_listing": ah_listing,
            "new_pipeline": new_pipeline, "grade": grade, "issues": issues, "info": info}


def main():
    ap = argparse.ArgumentParser(description="投研工作目录契约存在性检查（按波次分段）")
    ap.add_argument("workdir", help="研究工作目录（含 brief.json 的目录）")
    ap.add_argument("--stage", choices=STAGES, default="final",
                    help="只检查到该波次为止应已产出的产物（默认 final＝W8 全量终检）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    workdir = os.path.abspath(args.workdir)
    if not os.path.isdir(workdir):
        print(f"[FAIL] WORKDIR_MISSING: 工作目录不存在：{workdir}")
        return 2

    r = lint(workdir, args.stage)
    issues = r["issues"]
    if args.json:
        print(json.dumps({
            "workdir": workdir, "stage": r["stage"], "mode": r["mode"], "ah_listing": r["ah_listing"],
            "new_pipeline": r["new_pipeline"],
            "grade": r["grade"], "issue_count": len(issues),
            "issues": [{"code": c, "message": m} for c, m in issues],
            "info": r["info"],
        }, ensure_ascii=False, indent=2))
    else:
        for line in r["info"]:
            print(f"[INFO] {line}")
        for code, msg in issues:
            print(f"[FAIL] {code}: {msg}")
        if not issues:
            print(f"OK: 契约检查通过（stage={r['stage']}, workdir={workdir}, mode={r['mode']}, "
                  f"ah_listing={r['ah_listing']}, new_pipeline={r['new_pipeline']}）")
        else:
            print(f"共 {len(issues)} 项缺失/不一致（stage={r['stage']}）")
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
