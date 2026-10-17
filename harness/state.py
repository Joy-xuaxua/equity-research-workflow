"""Per-wave checkpoints and resume.

`<workdir>/.harness/state.json` records which steps finished, gate decisions and the agent
session ids, so `run_pipeline resume` restarts at the first unfinished step and an agent that
died mid-task is *resumed in its own session* instead of being re-launched from scratch.
`<workdir>/.harness/runs.jsonl` gets one row per SDK query invocation (usage, turns, retries).
"""
from __future__ import annotations

import io
import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from .util import now, read_json, write_json

# Strict wave order (SKILL.md §3). H1 = W1→W2 handoff validation (registry YAML); ASM_* = assembly.
STEPS = ["W1", "G1", "H1", "W2", "W3", "G2", "W4", "W5", "ASM_D", "W6", "G3", "W5R", "W7", "ASM_F", "W8"]

_LOCK = threading.Lock()


class State:
    def __init__(self, workdir: Path):
        self.dir = Path(workdir) / ".harness"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "state.json"
        self.runs_path = self.dir / "runs.jsonl"
        if self.path.exists():
            self.data: Dict[str, Any] = read_json(self.path)
        else:
            self.data = {"version": 1, "completed": {}, "gates": {}, "sessions": {}, "rounds": {}, "notes": {}}
            self.save()

    # ---- persistence ----
    def save(self) -> None:
        with _LOCK:
            write_json(self.path, self.data)

    def log_run(self, record: Dict[str, Any]) -> None:
        with _LOCK, io.open(self.runs_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ---- steps ----
    def done(self, step: str) -> bool:
        return step in self.data["completed"]

    def mark(self, step: str) -> None:
        self.data["completed"][step] = now()
        self.save()

    def reset_from(self, step: str) -> None:
        """Forget `step` and everything after it (used by `--from` and by W3→W2 re-dispatch)."""
        idx = STEPS.index(step)
        for s in STEPS[idx:]:
            self.data["completed"].pop(s, None)
        self.save()

    def next_step(self) -> Optional[str]:
        for s in STEPS:
            if not self.done(s):
                return s
        return None

    # ---- gates / sessions / counters ----
    def gate(self, key: str, default=None):
        return self.data["gates"].get(key, default)

    def set_gate(self, key: str, value) -> None:
        self.data["gates"][key] = value
        self.save()

    def session(self, label: str) -> Optional[str]:
        return self.data["sessions"].get(label)

    def set_session(self, label: str, sid: Optional[str]) -> None:
        if sid:
            self.data["sessions"][label] = sid
            self.save()

    def bump(self, key: str) -> int:
        self.data["rounds"][key] = self.data["rounds"].get(key, 0) + 1
        self.save()
        return self.data["rounds"][key]

    def rounds(self, key: str) -> int:
        return self.data["rounds"].get(key, 0)

    def note(self, key: str, value=None):
        if value is None:
            return self.data["notes"].get(key)
        self.data["notes"][key] = value
        self.save()
        return value
