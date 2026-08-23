#!/usr/bin/env python3
"""equity-research skill · 对账后副本生成器（collection → reconciled/ 打裁决戳）

用法（Windows Git Bash 需 PYTHONUTF8=1）：
    PYTHONUTF8=1 python scripts/reconcile_merge.py <workdir> [--adjudications <path>] [--strict] [--strip-appendix]

读 <workdir>/forensic/adjudications.json（手动 schema 校验，不引入 jsonschema）→ 整体重建
<workdir>/reconciled/：逐个复制 collection/[0-9][0-9]-*.md（--strip-appendix 时截掉「## 原文附录」节），
前置头部章，并在每条裁决的锚点行后插入单行戳：
    ▶ 裁决@ledger Cxx｜采信：<value>｜<note>
    ▶ 双值@ledger Cxx｜<value（含 ‖ 分隔）>｜<note>
    ▶ 悬置@ledger Cxx｜<note>
戳引用一律用 id（canonical、可 grep）；空段省略尾竖线。

性质：
- collection/ 原件只读，永不修改；
- 幂等：每次全量重建；时间取 adj.generated、指纹取 adjudications 内容的规范序列化 sha256 前 8 位，
  同一 json 重跑逐字节一致；
- 锚点口径：剔除「指标登记」块后的正文中出现且仅出现 1 次（与 collision_check 一致）；
  0 次 → P1 ANCHOR_NOT_FOUND，>1 → P1 ANCHOR_AMBIGUOUS，该条降级 ledger-only（不打戳），
  其余戳照常写出（部分成功仍落盘便于核对）；
- 退出码：P0/P1 → 1；--strict 时 P2 也计入（当前无 P2 产出，预留对称性）。
"""

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import sys
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collision_check import Issue, add  # noqa: E402  复用 Issue/add 与 lint 家族惯例

STATUS_VERB = {"resolved": "裁决", "dual": "双值", "pending": "悬置"}
GEN_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
ID_RE = re.compile(r"^C\d{1,3}$")
FILE_RE = re.compile(r"^0[1-4]-[a-z-]+\.md$")


# ---------- adjudications 加载与校验 ----------

def load_adjudications(path: str, issues: List[Issue]) -> Optional[Dict]:
    """schema 违规 → P1 并返回 None（调用方不得重建，防止坏输入毁掉现有 reconciled/）。"""
    if not os.path.isfile(path):
        add(issues, "P1", "ADJUDICATIONS_MISSING", f"找不到 {path}")
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            adj = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        add(issues, "P1", "ADJUDICATIONS_SCHEMA", f"JSON 解析失败：{exc}")
        return None
    if adj.get("version") != 1:
        add(issues, "P1", "ADJUDICATIONS_SCHEMA", f"version 应为 1，实为 {adj.get('version')!r}")
        return None
    if not GEN_RE.match(str(adj.get("generated", ""))):
        add(issues, "P1", "ADJUDICATIONS_SCHEMA", f"generated 应为 YYYY-MM-DD HH:MM，实为 {adj.get('generated')!r}")
        return None
    records = adj.get("adjudications")
    if not isinstance(records, list):
        add(issues, "P1", "ADJUDICATIONS_SCHEMA", "adjudications 应为数组")
        return None
    seen_ids = set()
    for i, rec in enumerate(records):
        where = f"adjudications[{i}]"
        if not isinstance(rec, dict):
            add(issues, "P1", "ADJUDICATIONS_SCHEMA", f"{where} 应为对象")
            return None
        for field in ("id", "status", "metric", "files"):
            if field not in rec:
                add(issues, "P1", "ADJUDICATIONS_SCHEMA", f"{where} 缺必填字段 {field}")
                return None
        if not ID_RE.match(str(rec["id"])):
            add(issues, "P1", "ADJUDICATIONS_SCHEMA", f"{where}.id 应匹配 C\\d{{1,3}}：{rec['id']!r}")
            return None
        if rec["id"] in seen_ids:
            add(issues, "P1", "ADJUDICATIONS_SCHEMA", f"{where}.id 重复：{rec['id']}")
            return None
        seen_ids.add(rec["id"])
        if rec["status"] not in STATUS_VERB:
            add(issues, "P1", "ADJUDICATIONS_SCHEMA",
                f"{where}.status 应为 resolved|dual|pending：{rec['status']!r}")
            return None
        if not str(rec["metric"]).strip():
            add(issues, "P1", "ADJUDICATIONS_SCHEMA", f"{where}.metric 不得为空")
            return None
        note = str(rec.get("note", ""))
        if len(note) > 120:
            add(issues, "P1", "ADJUDICATIONS_SCHEMA", f"{where}.note 超过 120 字（{len(note)}）")
            return None
        files = rec["files"]
        if not isinstance(files, list) or not files:
            add(issues, "P1", "ADJUDICATIONS_SCHEMA", f"{where}.files 应为非空数组")
            return None
        for j, fref in enumerate(files):
            if not isinstance(fref, dict) or not FILE_RE.match(str(fref.get("file", ""))):
                add(issues, "P1", "ADJUDICATIONS_SCHEMA",
                    f"{where}.files[{j}].file 应匹配 0[1-4]-<slug>.md：{fref.get('file') if isinstance(fref, dict) else fref!r}")
                return None
            if len(str(fref.get("anchor", ""))) < 8:
                add(issues, "P1", "ADJUDICATIONS_SCHEMA", f"{where}.files[{j}].anchor 至少 8 字符")
                return None
            if fref.get("side") not in ("A", "B", "neutral"):
                add(issues, "P1", "ADJUDICATIONS_SCHEMA",
                    f"{where}.files[{j}].side 应为 A|B|neutral：{fref.get('side')!r}")
                return None
    return adj


def canonical_sha8(adj: Dict) -> str:
    blob = json.dumps(adj, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:8]


# ---------- 戳与头部章 ----------

def compose_stamp(rec: Dict) -> str:
    verb = STATUS_VERB[rec["status"]]
    value = str(rec.get("value", "")).strip()
    note = str(rec.get("note", "")).strip()
    segs: List[str] = []
    if value:
        segs.append(f"采信：{value}" if rec["status"] == "resolved" else value)
    if note:
        segs.append(note)
    return f"▶ {verb}@ledger {rec['id']}｜" + "｜".join(segs)


def header_stamp(generated: str, sha8: str) -> List[str]:
    return [
        f"> 【对账后副本】本文件由 forensic/adjudications.json 经 scripts/reconcile_merge.py 自动生成",
        f">（裁决指纹 sha256:{sha8}，生成于 {generated}）。内容与 collection/ 同名原件一致，",
        f"> 仅在裁决锚点后追加「▶」单行裁决戳；collection/ 原件永不修改，冲突以本副本戳与 forensic/ledger.md 为准。",
        f"> 戳读法：▶ 裁决@ledger Cxx＝已裁决｜▶ 双值@＝两值并存引用须注明｜▶ 悬置@＝未决。",
        f"> 手改本文件即失效：改 adjudications.json 后重跑脚本重建。",
    ]


# ---------- 行级工具 ----------

def find_registry_span(lines: List[str]) -> Optional[Tuple[int, int]]:
    """「## 指标登记」标题到其 fenced 块结束的行区间（含端点）；无则 None。"""
    h = None
    for i, line in enumerate(lines):
        if re.match(r"^##\s*指标登记\s*$", line):
            h = i
            break
    if h is None:
        return None
    open_i = None
    for i in range(h + 1, len(lines)):
        if re.match(r"^```[a-zA-Z]*\s*$", lines[i]):
            open_i = i
            break
    if open_i is None:
        return (h, h)
    for i in range(open_i + 1, len(lines)):
        if re.match(r"^```\s*$", lines[i]):
            return (h, i)
    return (h, open_i)


def strip_appendix_lines(lines: List[str]) -> List[str]:
    """截掉「## 原文附录」节（至下一个 ## 标题或文件末尾）。"""
    for i, line in enumerate(lines):
        if re.match(r"^##\s*原文附录\s*$", line):
            for j in range(i + 1, len(lines)):
                if re.match(r"^##\s", lines[j]):
                    return lines[:i] + lines[j:]
            return lines[:i]
    return lines


# ---------- 重建与打戳 ----------

def load_collection(workdir: str, strip: bool, issues: List[Issue]) -> Dict[str, List[str]]:
    files = sorted(glob.glob(os.path.join(workdir, "collection", "[0-9][0-9]-*.md")))
    if not files:
        add(issues, "P1", "NO_COLLECTION", f"{workdir}/collection/ 下没有 [0-9][0-9]-*.md 采集文件")
        return {}
    copies: Dict[str, List[str]] = {}
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        if strip:
            lines = strip_appendix_lines(lines)
        copies[os.path.basename(path)] = lines
    return copies


def apply_stamps(copies: Dict[str, List[str]], adj: Dict, issues: List[Issue]) -> Tuple[int, int]:
    """返回 (成功戳数, 失败锚点数)。同一锚点行已含同 id 戳则跳过；已插入的戳行（▶ 开头）不参与后续锚点定位。"""
    ok = fail = 0
    for rec in adj["adjudications"]:
        stamp = compose_stamp(rec)
        for fref in rec["files"]:
            fname = fref["file"]
            anchor = fref["anchor"]
            if fname not in copies:
                add(issues, "P1", "TARGET_FILE_MISSING",
                    f"{rec['id']} 指向 {fname}，但 collection/ 无此文件", file=fname)
                fail += 1
                continue
            lines = copies[fname]
            span = find_registry_span(lines)
            hits = [
                i for i, line in enumerate(lines)
                if anchor in line and not line.startswith("▶ ")
                and (span is None or not (span[0] <= i <= span[1]))
            ]
            if len(hits) == 0:
                add(issues, "P1", "ANCHOR_NOT_FOUND",
                    f"{rec['id']} 锚点在 {fname} 正文中未找到（剔除登记块计）：{anchor[:30]}…", file=fname)
                fail += 1
                continue
            if len(hits) > 1:
                add(issues, "P1", "ANCHOR_AMBIGUOUS",
                    f"{rec['id']} 锚点在 {fname} 正文出现 {len(hits)} 次（应为 1）：{anchor[:30]}…", file=fname)
                fail += 1
                continue
            i = hits[0]
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if f"@ledger {rec['id']}" in nxt:
                continue  # 同 id 已打，跳过
            lines.insert(i + 1, stamp)
            ok += 1
    return ok, fail


def run(workdir: str, adj_path: Optional[str] = None, strip: bool = False, strict: bool = False) -> Tuple[int, List[Issue]]:
    issues: List[Issue] = []
    path = adj_path or os.path.join(workdir, "forensic", "adjudications.json")
    adj = load_adjudications(path, issues)
    if adj is None:
        return 1, issues
    copies = load_collection(workdir, strip, issues)
    if not copies:
        return 1, issues
    sha8 = canonical_sha8(adj)
    header = header_stamp(adj["generated"], sha8)
    out_dir = os.path.join(workdir, "reconciled")
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    total_before = len(adj["adjudications"])
    ok, fail = apply_stamps(copies, adj, issues)
    for fname, lines in copies.items():
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(header + ["", ""] + lines).rstrip("\n") + "\n")
    summary = f"reconcile_merge｜副本 {len(copies)} 文件｜裁决 {total_before} 条｜戳 {ok} 成功 / {fail} 失败｜指纹 sha256:{sha8}"
    print(summary)
    for i in issues:
        print(i.line(), file=sys.stderr)
    fail_levels = {"P0", "P1"} if not strict else {"P0", "P1", "P2"}
    return (1 if any(i.severity in fail_levels for i in issues) else 0), issues


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="collection → reconciled/ 对账后副本生成（打裁决戳）")
    ap.add_argument("workdir", help="研究工作目录（含 collection/ 与 forensic/adjudications.json）")
    ap.add_argument("--adjudications", help="adjudications.json 路径（默认 <workdir>/forensic/adjudications.json）")
    ap.add_argument("--strict", action="store_true", help="P2 也返回非零退出码（当前无 P2 产出，预留）")
    ap.add_argument("--strip-appendix", action="store_true", help="副本截掉「## 原文附录」节")
    args = ap.parse_args()
    code, _ = run(args.workdir, args.adjudications, args.strip_appendix, args.strict)
    sys.exit(code)


if __name__ == "__main__":
    main()
