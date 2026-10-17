"""Small shared helpers: UTF-8 file IO, script runs, timestamps, hashing."""
from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence


def now(fmt: str = "%Y-%m-%d %H:%M") -> str:
    return _dt.datetime.now().strftime(fmt)


def today() -> str:
    return _dt.date.today().isoformat()


def read(path: Path | str) -> str:
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def write(path: Path | str, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def read_json(path: Path | str):
    return json.loads(read(path))


def write_json(path: Path | str, obj) -> None:
    write(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def sha256(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class ScriptResult:
    cmd: List[str]
    code: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return self.stdout + (("\n" + self.stderr) if self.stderr.strip() else "")


def run_py(args: Sequence[str], cwd: Path | str, tee: Optional[Path] = None, timeout: int = 600) -> ScriptResult:
    """Run a skill script with the same interpreter, PYTHONUTF8=1 (Windows Git Bash convention in SKILL.md)."""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, *map(str, args)]
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    res = ScriptResult(cmd, proc.returncode, proc.stdout or "", proc.stderr or "")
    if tee is not None:
        write(tee, res.output)
    return res


def first_existing(paths: Iterable[Path]) -> Optional[Path]:
    for p in paths:
        if p.exists():
            return p
    return None
