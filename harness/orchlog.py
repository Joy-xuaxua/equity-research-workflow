"""Append-only orchestration-log.md (SKILL.md §0: `时间戳 | 波次/派发标签 | 产出或决策一句话 | 依据`)."""
from __future__ import annotations

import io
import threading
from pathlib import Path

from .util import now

_LOCK = threading.Lock()


def _clean(s: str) -> str:
    # One log row per event: no newlines, and '|' inside a field would break the column contract.
    return " ".join(str(s).split()).replace("|", "｜")


class OrchLog:
    def __init__(self, workdir: Path, title: str):
        self.path = Path(workdir) / "orchestration-log.md"
        if not self.path.exists():
            with io.open(self.path, "w", encoding="utf-8", newline="\n") as f:
                f.write(f"# 编排日志 · {title}\n\n")

    def add(self, tag: str, output: str, basis: str = "") -> None:
        line = f"{now()} | {_clean(tag)} | {_clean(output)} | {_clean(basis) or '—'}\n"
        with _LOCK, io.open(self.path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line)
        print(line, end="", flush=True)
