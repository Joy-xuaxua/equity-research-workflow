"""Handoff validators. Each returns a list of `Problem`s; an empty list means the handoff passes.

Where a rule already lives in a skill script (collision_check / reconcile_merge / lint_contract),
the validator imports and reuses it so there is one definition of the rule. Problems with
severity P0/P1 block the handoff and are sent back to the owning agent as a fix round; P2/P3
are logged and passed downstream as notes.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import yaml

from .config import ORCH_ROOT, REFS, SCRIPTS
from .docs import sections
from .util import read, read_json, run_py, write

for _p in (str(SCRIPTS), str(ORCH_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import collision_check as cc  # noqa: E402  (skill script, reused as a library)
import lint_contract as lc  # noqa: E402
import reconcile_merge as rm  # noqa: E402


@dataclass
class Problem:
    severity: str  # P0..P3
    code: str
    message: str
    file: str = ""

    def __str__(self) -> str:
        loc = f" [{self.file}]" if self.file else ""
        return f"[{self.severity}] {self.code}{loc}: {self.message}"


def blocking(problems: Sequence[Problem]) -> List[Problem]:
    return [p for p in problems if p.severity in ("P0", "P1")]


def render(problems: Sequence[Problem]) -> str:
    return "\n".join(str(p) for p in problems) or "OK"


# =====================================================================================
# 1. Collector metric-registry YAML (W1 → W2 handoff)
# =====================================================================================

def _yaml_entries(block: str) -> Tuple[Optional[List[Dict[str, str]]], str]:
    """Parse with a real YAML parser, all scalars as strings (dates/ints must stay verbatim)."""
    try:
        data = yaml.load(block, Loader=yaml.BaseLoader)
    except yaml.YAMLError as exc:
        return None, f"YAML 解析失败：{str(exc).splitlines()[0]}"
    if isinstance(data, dict) and isinstance(data.get("metrics"), list):
        data = data["metrics"]
    if data is None:
        return [], ""
    if not isinstance(data, list) or not all(isinstance(e, dict) for e in data):
        return None, "登记块顶层应为条目列表（或 metrics: 列表）"
    return [{str(k): ("" if v is None else str(v)) for k, v in e.items()} for e in data], ""


def _emit_scalar(v: str) -> str:
    """Quote so that both PyYAML and collision_check's line parser (which strips outer quotes) read `v`."""
    if v == "":
        return '""'
    if '"' not in v and "\\" not in v:
        return '"' + v + '"'
    if "'" not in v:
        return "'" + v + "'"
    return v  # rare: both quote kinds inside; left raw and reported if the round-trip differs


def _emit_block(entries: List[Dict[str, str]]) -> str:
    order = ["key", "name", "value", "unit", "period", "scope", "source", "tier", "ts", "anchor", "note"]
    out = []
    for e in entries:
        keys = [k for k in order if k in e] + [k for k in e if k not in order]
        first = True
        for k in keys:
            out.append(f"{'- ' if first else '  '}{k}: {_emit_scalar(e[k])}")
            first = False
    return "\n".join(out) + "\n"


def _replace_block(text: str, new_block: str) -> str:
    m = re.search(r"^##\s*指标登记\s*$", text, flags=re.M)
    after = text[m.end():]
    fence = re.search(r"^```[a-zA-Z]*\s*$", after, flags=re.M)
    start = fence.end()
    close = re.search(r"^```\s*$", after[start:], flags=re.M)
    return text[:m.end()] + after[:start] + "\n" + new_block + after[start + close.start():]


def registry(collection_dir: Path, mode: str, normalize: bool = False) -> Tuple[List[Problem], List[str]]:
    """Validate every `## 指标登记` block against references/collision-metrics.json.

    Checks: block present where lines_by_mode expects one; parseable by collision_check's line
    parser (flow-style `- {key: …}` is valid YAML but invisible to the script — the 1388.HK run lost
    74 entries this way); keys in the registry and on the right line; units parseable and of the
    registry dimension; periods canonical; anchors present, ≥10 chars and unique in the body.
    With `normalize=True` a parser-invisible block is rewritten in the canonical line style
    (syntax only — every value is round-trip checked), which is a mechanical fix, not a data edit.
    Returns (problems, actions_taken).
    """
    reg = cc.load_registry()
    metrics = reg["metrics"]
    expected = cc.expected_registry_lines(reg).get(mode, set())
    problems: List[Problem] = []
    actions: List[str] = []
    for f in sorted(collection_dir.glob("[0-9][0-9]-*.md")):
        line_name = f.stem
        rel = f"{collection_dir.name}/{f.name}"
        text = read(f)
        block, body = cc.extract_registry_block(text)
        if block is None:
            if line_name in expected:
                problems.append(Problem("P1", "REGISTRY_MISSING", "缺「## 指标登记」fenced 块（该线在 lines_by_mode 中有应登记指标）", rel))
            continue
        y_entries, err = _yaml_entries(block)
        if y_entries is None:
            problems.append(Problem("P1", "REGISTRY_YAML_INVALID", err, rel))
            continue
        scratch: list = []
        l_entries = cc.parse_metric_block(block, rel, scratch)
        invisible = len(l_entries) != len(y_entries) or any(
            not re.fullmatch(r"[a-z_0-9]+", e.get("key", "")) for e in l_entries)
        if invisible and y_entries:
            if normalize:
                new_block = _emit_block(y_entries)
                check = cc.parse_metric_block(new_block, rel, [])
                lossy = [i for i, (a, b) in enumerate(zip(y_entries, check)) if a != b]
                if len(check) == len(y_entries) and not lossy:
                    write(f, _replace_block(text, new_block))
                    actions.append(f"{rel}: 登记块 {len(y_entries)} 条由 flow-style 机械改写为脚本可读的行式 YAML（值逐条往返校验一致）")
                    text = read(f)
                    block, body = cc.extract_registry_block(text)
                else:
                    problems.append(Problem("P1", "REGISTRY_FORMAT_UNPARSEABLE",
                                            f"{len(y_entries)} 条为 collision_check 不可读格式，且自动改写不可无损（{len(lossy)} 条往返失配）", rel))
            else:
                problems.append(Problem("P1", "REGISTRY_FORMAT_UNPARSEABLE",
                                        f"YAML 有 {len(y_entries)} 条，collision_check 行式解析只认出 {len(l_entries)} 条有效 key（flow-style 不可读，条目将漏出机器对撞）", rel))
        for e in y_entries:
            problems.extend(_entry_problems(e, rel, line_name, mode, metrics, reg["units"], body))
    return problems, actions


def _entry_problems(e: Dict[str, str], rel: str, line_name: str, mode: str, metrics: Dict,
                    units: Dict, body: str) -> List[Problem]:
    out: List[Problem] = []
    key = e.get("key", "")
    tag = f"{key}@{e.get('period', '?')}"
    meta = metrics.get(key)
    if meta is None:
        out.append(Problem("P2", "REGISTRY_KEY_UNKNOWN", f"{tag}: key 不在 collision-metrics.json 清单（清单外指标不登记）", rel))
    else:
        lines = meta.get("lines_by_mode", {}).get(mode, [])
        if lines and line_name not in lines:
            out.append(Problem("P2", "REGISTRY_KEY_WRONG_LINE", f"{tag}: {mode} 模式下该指标归属 {lines}", rel))
        if meta.get("scope_required") and not e.get("scope"):
            out.append(Problem("P2", "REGISTRY_SCOPE_REQUIRED", f"{tag}: 该指标须填 scope", rel))
        u = cc.parse_unit(e.get("unit", ""), units)
        want = cc.parse_unit(meta.get("unit", ""), units)
        if u is None:
            out.append(Problem("P2", "REGISTRY_UNIT_UNKNOWN", f"{tag}: 单位「{e.get('unit', '')}」无法解析", rel))
        elif want is not None and u[0] != want[0]:
            out.append(Problem("P2", "REGISTRY_UNIT_DIM_MISMATCH", f"{tag}: 单位维度 {u[0]} ≠ 清单 {want[0]}", rel))
    if cc.canonical_period(e.get("period", "")) is None:
        out.append(Problem("P3", "REGISTRY_PERIOD_UNRECOGNIZED", f"{tag}: 期间「{e.get('period', '')}」不规范", rel))
    lo, _ = cc.parse_number_loose(e.get("value", ""))
    if lo is None:
        out.append(Problem("P2", "REGISTRY_VALUE_UNPARSEABLE", f"{tag}: 值「{e.get('value', '')}」无法解析", rel))
    anchor = e.get("anchor", "")
    if not anchor:
        out.append(Problem("P1", "REGISTRY_ANCHOR_MISSING", f"{tag}: 缺 anchor", rel))
    else:
        if len(anchor) < 10:
            out.append(Problem("P2", "REGISTRY_ANCHOR_SHORT", f"{tag}: anchor 不足 10 字符", rel))
        n = body.count(anchor)
        if n == 0:
            out.append(Problem("P1", "REGISTRY_ANCHOR_NOT_FOUND", f"{tag}: anchor 未在正文出现：{anchor[:40]}", rel))
        elif n > 1:
            out.append(Problem("P2", "REGISTRY_ANCHOR_NOT_UNIQUE", f"{tag}: anchor 在正文出现 {n} 次：{anchor[:40]}", rel))
    return out


# =====================================================================================
# 2. W2 outputs: financials.csv / adjudications.json / market-cap triple / ledger §2.x
# =====================================================================================

def financials(workdir: Path, mode: str) -> List[Problem]:
    issues: list = []
    lc.check_financials(str(workdir), mode, issues)
    return [Problem("P1", c, m, "forensic/financials.csv") for c, m in issues]


def adjudications(workdir: Path) -> List[Problem]:
    issues: list = []
    rm.load_adjudications(str(workdir / "forensic" / "adjudications.json"), issues)
    return [Problem(i.severity, i.code, i.message, "forensic/adjudications.json") for i in issues]


_MAG = {"万": 1e4, "百万": 1e6, "千万": 1e7, "亿": 1e8, "千": 1e3}


def _numbers_with_magnitude(text: str) -> List[float]:
    out = []
    for m in re.finditer(r"(-?\d[\d,]*(?:\.\d+)?)\s*(百万|千万|万|亿|千)?", text):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        out.append(v * _MAG.get(m.group(2) or "", 1.0))
        out.append(v)
    return out


def market_cap_identity(workdir: Path, tol: float = 0.01) -> List[Problem]:
    """W2 action 6: 市值＝现价×总股本 in ledger §1, computed from derived-inputs (ledger-anchored)."""
    di_path = workdir / "forensic" / "derived-inputs.json"
    if not di_path.exists():
        return [Problem("P1", "DERIVED_INPUTS_MISSING", "缺 forensic/derived-inputs.json", "forensic/derived-inputs.json")]
    try:
        di = read_json(di_path)
    except ValueError as exc:
        return [Problem("P1", "DERIVED_INPUTS_UNPARSEABLE", str(exc), "forensic/derived-inputs.json")]
    vals = {}
    for i in di.get("inputs", []):
        if i.get("key") in ("price_close", "shares_outstanding") and str(i.get("period", "")) in ("最新", "latest", ""):
            try:
                vals[i["key"]] = float(str(i["value"]).replace(",", ""))
            except (TypeError, ValueError):
                pass
    missing = [k for k in ("price_close", "shares_outstanding") if k not in vals]
    if missing:
        return [Problem("P1", "MARKET_TRIPLE_INPUT_MISSING",
                        f"derived-inputs 缺最新期 {missing}（总股本/收盘价必须转录，市值类指标依赖）", "forensic/derived-inputs.json")]
    mcap = vals["price_close"] * vals["shares_outstanding"]
    ledger = read(workdir / "forensic" / "ledger.md")
    lines = ledger.splitlines()
    sec1 = next((s for s in sections(ledger) if s.sid == "1" and s.level <= 2), None)
    scope = "\n".join(lines[sec1.start:sec1.end]) if sec1 else ledger
    cap_lines = [l for l in scope.splitlines() if "市值" in l]
    if not cap_lines:
        return [Problem("P1", "MARKET_CAP_NOT_IN_LEDGER", "ledger §1 基准节未发现「市值」行", "forensic/ledger.md")]
    for l in cap_lines:
        if any(abs(n - mcap) <= tol * abs(mcap) for n in _numbers_with_magnitude(l) if n):
            return []
    return [Problem("P1", "MARKET_CAP_IDENTITY_FAIL",
                    f"ledger §1 市值行中没有与 现价 {vals['price_close']} × 总股本 {vals['shares_outstanding']:,.0f} = {mcap:,.0f} 相符（±{tol:.0%}）的值",
                    "forensic/ledger.md")]


# =====================================================================================
# 3. W3 outputs: grade.json + grade-letter consistency (lint rule, applied at the handoff)
# =====================================================================================

GEN_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")


def grade(workdir: Path) -> List[Problem]:
    rel = "quality/grade.json"
    path = workdir / rel
    if not path.exists():
        return [Problem("P1", "GRADE_JSON_MISSING", "缺 quality/grade.json", rel)]
    try:
        g = read_json(path)
    except ValueError as exc:
        return [Problem("P1", "GRADE_JSON_UNPARSEABLE", str(exc), rel)]
    out: List[Problem] = []
    letter = str(g.get("grade", "")).upper()
    if letter not in {"A", "B", "C", "D"}:
        out.append(Problem("P1", "GRADE_INVALID", f"grade={g.get('grade')!r} 不在 A–D", rel))
    expect = {"C": "观望", "D": "规避"}.get(letter)
    if expect and g.get("veto_action") != expect:
        out.append(Problem("P1", "GRADE_VETO_INCONSISTENT", f"grade={letter} 应 veto_action={expect!r}，实际 {g.get('veto_action')!r}", rel))
    if not expect and g.get("veto_action") not in (None, ""):
        out.append(Problem("P1", "GRADE_VETO_INCONSISTENT", f"grade={letter} 不应设 veto_action", rel))
    if not str(g.get("summary", "")).strip():
        out.append(Problem("P1", "GRADE_SUMMARY_EMPTY", "summary 为空（须一句话依据）", rel))
    if g.get("evidence_ref") != "quality/earnings-quality.md":
        out.append(Problem("P2", "GRADE_EVIDENCE_REF", f"evidence_ref 应为 quality/earnings-quality.md，实际 {g.get('evidence_ref')!r}", rel))
    if not GEN_RE.match(str(g.get("generated", ""))):
        out.append(Problem("P2", "GRADE_GENERATED_FORMAT", "generated 应为 YYYY-MM-DD HH:MM", rel))
    if letter in {"A", "B", "C", "D"}:
        out.extend(grade_letters(workdir, "quality/earnings-quality.md", letter))
    return out


def grade_letters(workdir: Path, rel: str, letter: str) -> List[Problem]:
    """lint_contract GRADE_NOT_EMBEDDED / GRADE_MISMATCH, enforced at the handoff instead of at W8."""
    path = workdir / rel
    if not path.exists():
        return [Problem("P1", "GRADE_TARGET_MISSING", f"缺 {rel}", rel)]
    hits = lc.grade_letter_hits(read(path))
    out: List[Problem] = []
    if not any(letter in letters for _, letters in hits):
        out.append(Problem("P1", "GRADE_NOT_EMBEDDED", f"未发现可信度等级 {letter}（须逐字嵌入）", rel))
    for line, letters in hits:
        if letters != {letter} and "A/B/C/D" not in line:
            out.append(Problem("P1", "GRADE_MISMATCH",
                               f"含「可信度/等级」的行出现其他等级字母 {sorted(letters)}（lint 逐行取字母，否定语境如「不构成 D」、编号如「C19」同样计入；改写该行使其只含 {letter}）：{line[:80]}",
                               rel))
    return out


# =====================================================================================
# 4. Chapter files (lint contract per file, checked when each writer hands off)
# =====================================================================================

def chapter(workdir: Path, rel: str) -> List[Problem]:
    path = workdir / rel
    if not path.exists():
        return [Problem("P1", "CHAPTER_MISSING", f"缺 {rel}", rel)]
    text = read(path)
    lines = lc.nonempty_lines(text)
    out: List[Problem] = []
    if len(lines) < 2:
        return [Problem("P1", "CHAPTER_FILE_TOO_SHORT", "不足标题+要点两行", rel)]
    if not lines[0].startswith("## "):
        out.append(Problem("P1", "CHAPTER_HEADING_MISSING", "首非空行应为 `## <模板章节名>`", rel))
    if not lc.KEYLINE_RE.match(lines[1]):
        out.append(Problem("P1", "CHAPTER_KEYLINE_MISSING", "次非空行应以「本章要点：」/“Key takeaways:”开头", rel))
    if "<!-- data-gaps:" not in text:
        out.append(Problem("P1", "CHAPTER_DATAGAPS_MISSING", "缺尾注 <!-- data-gaps: ... -->", rel))
    return out


def data_gaps(workdir: Path, rel: str) -> List[str]:
    path = workdir / rel
    if not path.exists():
        return []
    m = re.search(r"<!--\s*data-gaps:(.*?)-->", read(path), flags=re.S)
    if not m:
        return []
    items = [x.strip() for x in re.split(r"[;；]", m.group(1)) if x.strip()]
    return [] if items == ["none"] else items


# =====================================================================================
# 5. Valuation: dcf output provenance, calibration line
# =====================================================================================

LABEL_RE = re.compile(r"===\s*标定\s*===.*?\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\].*?现价\s*(-?[\d.]+).*?\*\*(.+?)\*\*")


def dcf_label(output_text: str) -> Optional[Dict]:
    m = LABEL_RE.search(output_text)
    if not m:
        return None
    return {"low": float(m.group(1)), "high": float(m.group(2)), "price": float(m.group(3)),
            "label": m.group(4).strip(), "line": m.group(0).splitlines()[0]}


def _strip_mc(text: str, seeded: bool) -> str:
    if seeded:
        return text.strip()
    keep, skip = [], False
    for line in text.splitlines():
        if line.startswith("=== 蒙特卡洛"):
            skip = True
            continue
        if skip and line.startswith("==="):
            skip = False
        if not skip:
            keep.append(line.rstrip())
    return "\n".join(keep).strip()


def dcf_provenance(workdir: Path, config_rel: str, output_rel: str) -> List[Problem]:
    """Re-run dcf.py on the saved config: the saved output must be that script's output (禁止心算/手改)."""
    cfg, outp = workdir / config_rel, workdir / output_rel
    if not cfg.exists():
        return [Problem("P1", "ASSUMPTIONS_MISSING", f"缺 {config_rel}", config_rel)]
    if not outp.exists():
        return [Problem("P1", "DCF_OUTPUT_MISSING", f"缺 {output_rel}", output_rel)]
    try:
        conf = read_json(cfg)
    except ValueError as exc:
        return [Problem("P1", "ASSUMPTIONS_UNPARSEABLE", str(exc), config_rel)]
    res = run_py([SCRIPTS / "dcf.py", "--config", str(cfg.resolve())], cwd=workdir)
    if res.code != 0:
        return [Problem("P1", "DCF_CONFIG_ERROR", f"dcf.py 退出码 {res.code}：{res.output.strip()[-300:]}", config_rel)]
    seeded = isinstance(conf.get("montecarlo"), dict) and "seed" in conf["montecarlo"]
    if _strip_mc(res.stdout, seeded) != _strip_mc(read(outp), seeded):
        return [Problem("P1", "DCF_OUTPUT_NOT_REPRODUCIBLE",
                        f"{output_rel} 与 dcf.py 对 {config_rel} 的复跑输出不一致（须为脚本原始 stdout，改假设后须重跑落盘）", output_rel)]
    if dcf_label(res.stdout) is None:
        return [Problem("P1", "DCF_LABEL_LINE_MISSING", "dcf.py 输出无「=== 标定 ===」行（assumptions 缺 range_low/range_high？）", output_rel)]
    return []


def valuation_notes(workdir: Path, label: str, revision: bool = False) -> List[Problem]:
    rel = "valuation/valuation-notes.md"
    path = workdir / rel
    if not path.exists():
        return [Problem("P1", "VALUATION_NOTES_MISSING", f"缺 {rel}", rel)]
    text = read(path)
    out = []
    if "thesis brief" not in text.lower():
        out.append(Problem("P1", "THESIS_BRIEF_MISSING", "缺 thesis brief 显式节（红队攻击面）", rel))
    if label and label not in text:
        out.append(Problem("P1", "THESIS_LABEL_MISSING", f"notes 未逐字出现脚本标定标签「{label}」", rel))
    if revision and "修正轮" not in text:
        out.append(Problem("P1", "REVISION_SECTION_MISSING", "修正轮须在 notes 追加「修正轮」节", rel))
    return out


# =====================================================================================
# 6. Red-team sidecar (G3 becomes code)
# =====================================================================================

STRENGTHS = ["弱", "中", "中强", "强"]
SIDECAR_REL = "redteam/redteam-findings.json"


def target_kind(target: str) -> str:
    """Map a free-text write-back target to the G3 branch it triggers."""
    t = target.replace(" ", "")
    if re.search(r"情景概率|标定|估值假设|估值章|ch0?6|修正轮|区间", t):
        return "valuation"
    m = re.search(r"ch0?([2-8])", t)
    if m:
        return f"writer:{int(m.group(1))}"
    if re.search(r"ch0?1|ch0?9|动作|仓位|风险|结论", t):
        return "verdict"
    return "verdict"


def _md_strengths(md: str) -> Dict[str, str]:
    """Finding id → strength as written in the redteam-feedback.md findings table."""
    found = {}
    for line in md.splitlines():
        m = re.match(r"^\|\s*(R\d+)\s*\|", line)
        if not m:
            continue
        cells = [c.strip().strip("*") for c in line.strip().strip("|").split("|")]
        for c in cells[1:]:
            if c in STRENGTHS:
                found[m.group(1)] = c
                break
    return found


def redteam(workdir: Path) -> List[Problem]:
    out: List[Problem] = []
    md_path, sc_path = workdir / "redteam" / "redteam-feedback.md", workdir / SIDECAR_REL
    if not md_path.exists():
        out.append(Problem("P1", "REDTEAM_FEEDBACK_MISSING", "缺 redteam/redteam-feedback.md", "redteam/redteam-feedback.md"))
    if not sc_path.exists():
        return out + [Problem("P1", "REDTEAM_SIDECAR_MISSING", f"缺 {SIDECAR_REL}", SIDECAR_REL)]
    try:
        sc = read_json(sc_path)
    except ValueError as exc:
        return out + [Problem("P1", "REDTEAM_SIDECAR_UNPARSEABLE", str(exc), SIDECAR_REL)]
    tq = sc.get("three_questions", {})
    if tq.get("verdict") not in ("通过", "不通过"):
        out.append(Problem("P1", "REDTEAM_THREE_Q_VERDICT", "three_questions.verdict 须为 通过|不通过", SIDECAR_REL))
    findings = sc.get("findings")
    if not isinstance(findings, list) or not findings:
        return out + [Problem("P1", "REDTEAM_FINDINGS_EMPTY", "findings 须为非空列表", SIDECAR_REL)]
    ids = set()
    for f in findings:
        fid = f.get("id", "?")
        if not re.fullmatch(r"R\d+", str(fid)):
            out.append(Problem("P1", "REDTEAM_FINDING_ID", f"id={fid!r} 应为 R<n>", SIDECAR_REL))
        if fid in ids:
            out.append(Problem("P1", "REDTEAM_FINDING_DUP", f"{fid} 重复", SIDECAR_REL))
        ids.add(fid)
        if f.get("strength") not in STRENGTHS:
            out.append(Problem("P1", "REDTEAM_STRENGTH_INVALID", f"{fid}: strength={f.get('strength')!r} 不在 {STRENGTHS}", SIDECAR_REL))
        tg = f.get("targets")
        if not isinstance(tg, list) or not tg or not all(isinstance(x, str) and x.strip() for x in tg):
            out.append(Problem("P1", "REDTEAM_TARGETS_INVALID", f"{fid}: targets 须为非空字符串列表（回写目标）", SIDECAR_REL))
    cons = sc.get("consistency", {})
    for k in ("label_matches_dcf", "gap_consistent", "veto_chain_ok", "probabilities_match_evidence"):
        if not isinstance(cons.get(k), bool):
            out.append(Problem("P1", "REDTEAM_CONSISTENCY_FIELD", f"consistency.{k} 须为 true/false", SIDECAR_REL))
    if md_path.exists():
        md_s = _md_strengths(read(md_path))
        for f in findings:
            fid = f.get("id")
            if fid not in md_s:
                out.append(Problem("P1", "REDTEAM_SIDECAR_MD_MISMATCH", f"{fid} 未出现在 redteam-feedback.md 发现清单表格行", SIDECAR_REL))
            elif md_s[fid] != f.get("strength"):
                out.append(Problem("P1", "REDTEAM_SIDECAR_MD_MISMATCH", f"{fid} 强度 md={md_s[fid]} vs json={f.get('strength')}", SIDECAR_REL))
        extra = sorted(set(md_s) - ids)
        if extra:
            out.append(Problem("P1", "REDTEAM_SIDECAR_MD_MISMATCH", f"md 表格有而 json 缺：{extra}", SIDECAR_REL))
    return out


# =====================================================================================
# 7. Verdict chapters
# =====================================================================================

def verdict(workdir: Path, label: str, grade_letter: str, strong_ids: Sequence[str], three_q_pass: bool) -> List[Problem]:
    out: List[Problem] = []
    ch1, ch9 = "chapters/ch01-summary.md", "chapters/ch09-conclusion.md"
    for rel in (ch1, ch9):
        out.extend(chapter(workdir, rel))
    if out:
        return out
    t1, t9 = read(workdir / ch1), read(workdir / ch9)
    for rel, t in ((ch1, t1), (ch9, t9)):
        if label and label not in t:
            out.append(Problem("P1", "VERDICT_LABEL_NOT_RESTATED", f"未逐字出现脚本标定标签「{label}」", rel))
    cap = {"C": "观望", "D": "规避"}.get(grade_letter)
    if not three_q_pass and cap is None:
        cap = "观望"
    if cap and cap not in t1:
        out.append(Problem("P1", "VERDICT_VETO_NOT_APPLIED", f"否决链要求动作上限「{cap}」，ch01 结论框未出现", ch1))
    # Not \b: CJK characters count as \w, so "见R1" has no word boundary before R.
    missing = [i for i in strong_ids if not re.search(rf"(?<![A-Za-z0-9]){re.escape(i)}(?![0-9])", t9)]
    if missing:
        out.append(Problem("P1", "VERDICT_WRITEBACK_MISSING", f"红队中强/强发现未在 ch09 回写映射表出现：{missing}", ch9))
    return out
