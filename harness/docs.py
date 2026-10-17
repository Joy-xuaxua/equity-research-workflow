"""Markdown section extraction for preloading exactly the reference sections an agent needs.

Headings inside fenced code blocks are ignored (collection registry YAML contains `# 说明` comment
lines that would otherwise look like H1s). Section ids are recognised in the three numbering
styles used across the skill: `## 7. 标题` / `### 7.1 标题`, `## §1 标题` (ledger) and
`## 二、标题` (report template).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from .util import read

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_NUM_ID = re.compile(r"^§?\s*(\d+(?:\.\d+)*)(?:[.、．:：]|\s|$)")
_CN_ID = re.compile(r"^([一二三四五六七八九十]+)、")


@dataclass
class Section:
    level: int
    title: str
    sid: Optional[str]
    start: int  # line index of the heading
    end: int    # exclusive line index (next heading of same or higher level, or EOF)


def section_id(title: str) -> Optional[str]:
    m = _NUM_ID.match(title)
    if m:
        return m.group(1)
    m = _CN_ID.match(title)
    if m:
        return m.group(1)
    return None


def sections(text: str) -> List[Section]:
    lines = text.splitlines()
    heads: List[Section] = []
    in_fence = False
    for i, line in enumerate(lines):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING.match(line)
        if m:
            title = m.group(2)
            heads.append(Section(len(m.group(1)), title, section_id(title), i, len(lines)))
    for k, h in enumerate(heads):
        for nxt in heads[k + 1:]:
            if nxt.level <= h.level:
                h.end = nxt.start
                break
    return heads


def _bare_title(title: str) -> str:
    t = re.sub(r"^§?\s*\d+(?:\.\d+)*[.、．:：]?\s*", "", title)
    return re.sub(r"^[一二三四五六七八九十]+、\s*", "", t).strip()


def extract(text: str, ids: Sequence[str] = (), titles: Sequence[str] = ()) -> str:
    """Concatenate every section whose id is in `ids` or whose bare title starts with one of `titles`.

    A requested section brings its subsections; overlapping picks are de-duplicated by line range.
    """
    lines = text.splitlines()
    picked: List[Section] = []
    for s in sections(text):
        if (s.sid is not None and s.sid in ids) or any(_bare_title(s.title).startswith(t) for t in titles):
            if not any(p.start <= s.start < p.end for p in picked):
                picked.append(s)
    return "\n\n".join("\n".join(lines[s.start:s.end]).rstrip() for s in picked)


def keep_level2(text: str, keep: Iterable[str]) -> str:
    """Keep the preamble (before the first `##`) plus the named level-2 sections, in file order."""
    keep = tuple(keep)
    lines = text.splitlines()
    secs = [s for s in sections(text) if s.level == 2]
    if not secs:
        return text
    out = ["\n".join(lines[:secs[0].start]).rstrip()]
    for s in secs:
        if _bare_title(s.title).startswith(keep):
            out.append("\n".join(lines[s.start:s.end]).rstrip())
    return "\n\n".join(x for x in out if x)


def drop_level2(text: str, drop: Iterable[str]) -> str:
    drop = tuple(drop)
    lines = text.splitlines()
    kill = [s for s in sections(text) if s.level == 2 and _bare_title(s.title).startswith(drop)]
    keep_mask = [True] * len(lines)
    for s in kill:
        for i in range(s.start, s.end):
            keep_mask[i] = False
    return "\n".join(l for l, k in zip(lines, keep_mask) if k).rstrip()


@dataclass
class Doc:
    """One preloaded file (or excerpt) for an agent's first message."""
    label: str      # path as the agent should cite it, e.g. `forensic/ledger.md` or `<skill_root>/references/x.md`
    scope: str      # "全文" or "§7–8（节选）"
    text: str

    def render(self) -> str:
        return f'<file path="{self.label}" scope="{self.scope}">\n{self.text.strip()}\n</file>'

    @property
    def chars(self) -> int:
        return len(self.text)


def load(path: Path, label: str, ids: Sequence[str] = (), titles: Sequence[str] = (), scope: str = "") -> Optional[Doc]:
    """Load a whole file, or only the given sections. Missing file → None (agent falls back to Read)."""
    if not path.exists():
        return None
    text = read(path)
    if ids or titles:
        body = extract(text, ids, titles)
        if not body.strip():
            return Doc(label, "全文（节选未命中，回退全文）", text)
        return Doc(label, scope or ("§" + "/".join(list(ids) + list(titles)) + "（节选）"), body)
    return Doc(label, scope or "全文", text)


def render_all(docs: Iterable[Optional[Doc]]) -> str:
    return "\n\n".join(d.render() for d in docs if d is not None)
