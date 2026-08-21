#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lint_contract.py — 投研流水线工作目录契约存在性检查。

用法（Windows Git Bash 需 PYTHONUTF8=1）：
    PYTHONUTF8=1 python lint_contract.py <workdir> [--json]

检查项（缺失/不一致 → 非零退出，输出缺失清单）：
  1. collection/ 四条采集线文件齐（01–04），各含「冲突」「未获取到」小节；industry-classification.md 存在且含 主附录 行。
  2. chapters/ch*.md：首非空行为章节标题（# 开头），次非空行为「本章要点：」/“Key takeaways:”，尾注 data-gaps 注释存在。
  3. ah_listing=true 时分市场结论块：full→ch01/04/06/09，earnings→ch01/04/08/09，各含「分市场」或「A/H」标记。
  4. forensic/financials.csv 列齐全（deferred_revenue 可选），行数 full≥5 / earnings≥4。
  5. forensic/grade.json 可解析，grade∈{A,B,C,D}，且 veto_action 与等级一致（C→观望，D→规避）。
  6. ch05 章与 forensic/earnings-quality.md 中的可信度等级均与 grade.json 一致。
  7. 结构存在：brief.json、ledger、earnings-quality、grade.json、估值四件套（assumptions/dcf-output/valuation-notes/估值章）、
     redteam-feedback、ch01/ch09、draft/_header.md、report-draft.md、report-final.md。
  8. 新流水线标记（forensic/adjudications.json 存在或 quality/ 目录存在）时：质量产物在 quality/（grade.json、
     earnings-quality.md）；reconciled/ 含与 collection/01–04 同名 4 文件、首 10 行含【对账后副本】头部章、
     adjudications 非空时每副本 ≥1 个 ▶ 裁决戳。标记不存在（旧 workdir）按旧布局检查，零影响。
"""
import argparse
import csv
import glob
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


def read_text(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def nonempty_lines(text):
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def add(issues, code, msg):
    issues.append((code, msg))


def check_collection(workdir, issues):
    cdir = os.path.join(workdir, "collection")
    if not os.path.isdir(cdir):
        add(issues, "COLLECTION_DIR_MISSING", "缺少 collection/ 目录")
        return
    files = sorted(glob.glob(os.path.join(cdir, "[0-9][0-9]-*.md")))
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
    ic = os.path.join(cdir, "industry-classification.md")
    if not os.path.isfile(ic):
        add(issues, "INDUSTRY_CLASSIFICATION_MISSING", "缺少 collection/industry-classification.md")
    else:
        head = nonempty_lines(read_text(ic))[:3]
        if not any(ln.startswith("主附录:") for ln in head):
            add(issues, "INDUSTRY_CLASSIFICATION_FORMAT", "industry-classification.md 首部缺「主附录: <slug>」机读行")


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


def check_ah(workdir, mode, ah_listing, issues):
    if not ah_listing:
        return
    for nn in AH_CHAPTERS.get(mode, AH_CHAPTERS["full"]):
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


def grade_letter_hits(text):
    """返回 [(行, 该行中出现的等级字母集合)]，仅统计含等级关键词的行。"""
    hits = []
    for line in text.splitlines():
        if ("可信度" in line or "等级" in line
                or "Earnings credibility" in line or "Grade" in line):
            letters = set(re.findall(r"(?<![A-Za-z/])([A-D])(?![A-Za-z/])", line))
            if letters:
                hits.append((line.strip(), letters))
    return hits


def check_grade_consistency(workdir, grade, issues, new_pipeline=False):
    if grade is None:
        return
    eq_rel = "quality/earnings-quality.md" if new_pipeline else "forensic/earnings-quality.md"
    targets = [
        (eq_rel, glob.glob(os.path.join(workdir, *eq_rel.split("/")))),
        ("chapters/ch05-*", glob.glob(os.path.join(workdir, "chapters", "ch05-*.md"))),
    ]
    for label, hits in targets:
        if not hits:
            add(issues, "GRADE_CONSISTENCY_TARGET_MISSING", f"等级一致性核对缺文件：{label}")
            continue
        text = read_text(hits[0])
        found = grade_letter_hits(text)
        if not any(grade in letters for _, letters in found):
            add(issues, "GRADE_NOT_EMBEDDED",
                f"{os.path.relpath(hits[0], workdir)} 未发现可信度等级 {grade}（应逐字嵌入证据表）")
        for line, letters in found:
            if letters != {grade} and "A/B/C/D" not in line:
                add(issues, "GRADE_MISMATCH",
                    f"{os.path.relpath(hits[0], workdir)} 等级行与 grade.json 不一致：{letters} vs {grade}｜行：{line[:60]}")


def check_structure(workdir, mode, issues, new_pipeline=False):
    eq_rel = "quality/earnings-quality.md" if new_pipeline else "forensic/earnings-quality.md"
    required_files = [
        "brief.json",
        "forensic/ledger.md",
        eq_rel,
        "redteam/redteam-feedback.md",
        "draft/_header.md",
        "draft/report-draft.md",
        "draft/report-final.md",
    ]
    if new_pipeline:
        required_files.append("forensic/adjudications.json")
    for rel in required_files:
        if not os.path.isfile(os.path.join(workdir, rel)):
            add(issues, "FILE_MISSING", f"缺少 {rel}")
    val_ch = "chapters/ch06-*.md" if mode == "full" else "chapters/ch08-*.md"
    for pat, label in [
        ("chapters/ch01-*.md", "第一章（速览）"),
        ("chapters/ch09-*.md", "第九章（结论）"),
        (val_ch, "估值章"),
        ("valuation/assumptions*.json", "估值假设 JSON"),
        ("valuation/dcf-output*.txt", "dcf.py 输出"),
        ("valuation/valuation-notes.md", "valuation-notes.md"),
    ]:
        if not glob.glob(os.path.join(workdir, pat)):
            add(issues, "FILE_MISSING", f"缺少 {label}（{pat}）")


def has_new_pipeline(workdir):
    """新流水线标记：forensic/adjudications.json 存在，或 quality/ 目录存在（其一即按新布局检查）。"""
    return (os.path.isfile(os.path.join(workdir, "forensic", "adjudications.json"))
            or os.path.isdir(os.path.join(workdir, "quality")))


def check_reconciled(workdir, issues):
    """新流水线专属：reconciled/ 副本与 collection/01–04 同名、含头部章、adjudications 非空时有 ≥1 个 ▶ 戳。"""
    cdir = os.path.join(workdir, "collection")
    rdir = os.path.join(workdir, "reconciled")
    if not os.path.isdir(rdir):
        add(issues, "RECONCILED_MISSING", "缺少 reconciled/ 目录（应由 W2 跑 reconcile_merge.py 生成）")
        return
    stamps_required = False
    adj_path = os.path.join(workdir, "forensic", "adjudications.json")
    if os.path.isfile(adj_path):
        try:
            adj = json.loads(read_text(adj_path))
            stamps_required = bool(adj.get("adjudications"))
        except (ValueError, UnicodeDecodeError) as e:
            add(issues, "ADJUDICATIONS_UNPARSEABLE", f"forensic/adjudications.json 解析失败：{e}")
    for f in sorted(glob.glob(os.path.join(cdir, "[0-9][0-9]-*.md"))):
        base = os.path.basename(f)
        rel = f"reconciled/{base}"
        rfile = os.path.join(rdir, base)
        if not os.path.isfile(rfile):
            add(issues, "RECONCILED_MISSING", f"缺少 {rel}（应与 collection/ 同名）")
            continue
        text = read_text(rfile)
        head = nonempty_lines(text)[:10]
        if not any("【对账后副本】" in ln for ln in head):
            add(issues, "RECONCILED_HEADER_MISSING", f"{rel} 首 10 行缺【对账后副本】头部章（应由脚本生成）")
        if stamps_required and not any(ln.startswith("▶ ") for ln in text.splitlines()):
            add(issues, "RECONCILED_STAMP_MISSING", f"{rel} 无任何 ▶ 裁决戳（adjudications 非空时应至少 1 个）")


def main():
    ap = argparse.ArgumentParser(description="投研工作目录契约存在性检查")
    ap.add_argument("workdir", help="研究工作目录（含 brief.json 的目录）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    workdir = os.path.abspath(args.workdir)
    issues = []
    if not os.path.isdir(workdir):
        print(f"[FAIL] WORKDIR_MISSING: 工作目录不存在：{workdir}")
        return 2

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

    check_collection(workdir, issues)
    check_chapters(workdir, issues)
    check_ah(workdir, mode, ah_listing, issues)
    check_financials(workdir, mode, issues)
    new_pipeline = has_new_pipeline(workdir)
    grade = check_grade(workdir, issues, new_pipeline)
    check_grade_consistency(workdir, grade, issues, new_pipeline)
    check_structure(workdir, mode, issues, new_pipeline)
    if new_pipeline:
        check_reconciled(workdir, issues)

    if args.json:
        print(json.dumps({
            "workdir": workdir, "mode": mode, "ah_listing": ah_listing,
            "new_pipeline": new_pipeline,
            "grade": grade, "issue_count": len(issues),
            "issues": [{"code": c, "message": m} for c, m in issues],
        }, ensure_ascii=False, indent=2))
    else:
        for code, msg in issues:
            print(f"[FAIL] {code}: {msg}")
        if not issues:
            print(f"OK: 契约检查通过（workdir={workdir}, mode={mode}, ah_listing={ah_listing}, "
                  f"new_pipeline={new_pipeline}）")
        else:
            print(f"共 {len(issues)} 项缺失/不一致")
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
