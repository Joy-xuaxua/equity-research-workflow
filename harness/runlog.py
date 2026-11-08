"""Open-ended run accounting: one JSONL row per thing worth remembering about a run.

`<workdir>/.harness/runs.jsonl` is the harness' only machine-readable record of *how* a run went
(API usage, turns, retries, error kinds) as opposed to *what* it decided — that stays in the
human-readable `orchestration-log.md`, which never gets LLM usage written into it.

The log is deliberately schema-less: `log()` takes any keyword/dict payload and writes it as-is.
Only `ts` and `run_id` are filled in automatically (a caller-supplied value wins), so new accounting
can be added at the call site without touching this module or any function signature. `run_id` is
minted once per pipeline start, which is what lets a resumed workdir be split by launch.

Writing must never be able to take the pipeline down: serialization falls back to `default=str`
and then to a repr-only row, and an IO failure is swallowed after one warning on stderr.
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

RUNS_REL = Path(".harness") / "runs.jsonl"

# One process-wide lock: W4 dispatches five writers in parallel, and append order does not matter
# as long as no two lines interleave inside the file.
_LOCK = threading.Lock()


def new_run_id() -> str:
    """Sortable, unique per pipeline start (two launches in the same second still differ)."""
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]


def runs_path(workdir: Path | str) -> Path:
    return Path(workdir) / RUNS_REL


class RunLog:
    def __init__(self, workdir: Path | str, run_id: Optional[str] = None, path: Optional[Path] = None):
        self.path = Path(path) if path else runs_path(workdir)
        self.run_id = run_id or new_run_id()
        self._warned = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # noqa: BLE001 — logging must not break the pipeline
            self._warn(exc)

    def log(self, record: Optional[Mapping[str, Any]] = None, **fields: Any) -> None:
        """Append one row. Any keys are accepted; `ts`/`run_id` are defaults the caller may override."""
        rec: Dict[str, Any] = {"ts": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "run_id": self.run_id}
        if record:
            rec.update(record)
        if fields:
            rec.update(fields)
        try:
            line = json.dumps(rec, ensure_ascii=False, default=str)
        except Exception as exc:  # noqa: BLE001 — e.g. a self-referencing value, which `default` cannot fix
            line = json.dumps({"ts": rec["ts"], "run_id": rec["run_id"], "log_error": f"{type(exc).__name__}: {exc}",
                               "repr": repr(rec)[:2000]}, ensure_ascii=False, default=str)
        try:
            with _LOCK, io.open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")
        except Exception as exc:  # noqa: BLE001 — a lost accounting row is never worth a failed run
            self._warn(exc)

    def _warn(self, exc: BaseException) -> None:
        if self._warned:
            return
        self._warned = True
        print(f"[harness] run log unavailable ({type(exc).__name__}: {exc}); accounting rows are being dropped",
              file=sys.stderr, flush=True)


def read_runs(workdir: Path | str, latest_only: bool = False) -> List[Dict[str, Any]]:
    """Every parsable row, oldest first. Missing keys are the reader's problem, never the writer's:
    old rows predating `run_id` / `kind` / `msg` are returned unchanged and must be read with `.get`.

    `latest_only` keeps the rows of the last `run_id` present in the file (rows without one are
    treated as belonging to a single anonymous pre-`run_id` run)."""
    path = runs_path(workdir)
    rows: List[Dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            rows.append(d)
    if latest_only and rows:
        last = rows[-1].get("run_id")
        rows = [r for r in rows if r.get("run_id") == last]
    return rows


def run_ids(rows: Iterable[Mapping[str, Any]]) -> List[Any]:
    seen: List[Any] = []
    for r in rows:
        rid = r.get("run_id")
        if rid not in seen:
            seen.append(rid)
    return seen
