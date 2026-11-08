"""Token accounting, measured the same way as the recorded baseline: sum `usage` per assistant message
id (max over the streamed copies of one message) from Claude Code transcripts.

Baseline: `~/.claude/projects/<proj>/<session>/subagents/*.jsonl` grouped by `meta.json` description
(`W1 …` … `W8 …`), plus the orchestrator's own transcript split at the first W2 dispatch.
Harness: the SDK sessions recorded in `<workdir>/.harness/runs.jsonl`, located by session id under
`~/.claude/projects/*/<session_id>.jsonl`.

`run_summary()` is the other, independent reader of that same log: it aggregates the rows themselves
(no transcripts, no in-memory objects) into the per-label table the pipeline prints when it ends, so
the numbers survive a crash and a resume. Every key is read with `.get`: rows written by an older
harness have no `run_id` / `kind` / `msg`, and callers may add keys this module has never heard of.

    python -m harness.tokens --baseline-session 182f7618-9cf8-457c-bf0b-ab730c0e9653 --workdir <harness workdir>
    python -m harness.tokens --runs --workdir <harness workdir> [--latest-run]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .runlog import read_runs, run_ids

PROJECTS = Path.home() / ".claude" / "projects"
FIELDS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")


def _ts(s: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def message_usage(path: Path, after: Optional[_dt.datetime] = None, before: Optional[_dt.datetime] = None) -> Dict[str, Dict]:
    """message id → {fields…, ts}; streamed partial copies of one message are collapsed with max()."""
    per: Dict[str, Dict] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "assistant":
                continue
            m = d.get("message") or {}
            mid, u = m.get("id"), m.get("usage") or {}
            if not mid:
                continue
            ts = _ts(d["timestamp"]) if d.get("timestamp") else None
            if ts and ((after and ts < after) or (before and ts >= before)):
                continue
            cur = per.setdefault(mid, {k: 0 for k in FIELDS} | {"ts": ts})
            for k in FIELDS:
                cur[k] = max(cur[k], int(u.get(k) or 0))
    return per


def summarize(per: Dict[str, Dict]) -> Dict[str, int]:
    tot = {k: sum(v[k] for v in per.values()) for k in FIELDS}
    tot["total"] = sum(tot[k] for k in FIELDS)
    tot["turns"] = len(per)
    tot["peak_ctx"] = max((v["input_tokens"] + v["cache_read_input_tokens"] + v["cache_creation_input_tokens"] for v in per.values()), default=0)
    return tot


def _add(a: Dict[str, int], b: Dict[str, int]) -> Dict[str, int]:
    out = dict(a)
    for k, v in b.items():
        if k == "peak_ctx":
            out[k] = max(out.get(k, 0), v)
        elif isinstance(v, int):
            out[k] = out.get(k, 0) + v
    return out


WAVES = ["W1", "G1", "W2", "W3", "W4", "W5", "W6", "W7", "W8"]


def baseline(session_id: str) -> Tuple[Dict[str, Dict], Dict[str, Dict]]:
    """(per-wave subagent totals incl. n agents, orchestrator totals split into W1-phase / W2–W8-phase)."""
    sess = next(PROJECTS.glob(f"*/{session_id}"), None)
    if sess is None:
        raise FileNotFoundError(f"baseline session {session_id} not found under {PROJECTS}")
    waves: Dict[str, Dict] = OrderedDict()
    first_w2: Optional[_dt.datetime] = None
    for meta in sorted((sess / "subagents").glob("*.meta.json")):
        md = json.loads(meta.read_text(encoding="utf-8"))
        m = re.match(r"(W\d)", md.get("description", ""))
        wave = m.group(1) if m else "?"
        per = message_usage(meta.with_name(meta.name.replace(".meta.json", ".jsonl")))
        tot = summarize(per)
        tot["agents"] = 1
        waves[wave] = _add(waves.get(wave, {}), tot)
        if wave == "W2":
            t0 = min((v["ts"] for v in per.values() if v["ts"]), default=None)
            if t0 and (first_w2 is None or t0 < first_w2):
                first_w2 = t0
    main = sess.with_suffix(".jsonl")
    orch = {"W1-phase": summarize(message_usage(main, before=first_w2)),
            "W2–W8-phase": summarize(message_usage(main, after=first_w2))}
    return waves, orch


def wave_of(label: str) -> str:
    base = label.split(":")[0]
    return {"W5R": "W5"}.get(base, base)


def find_transcript(session_id: str) -> Optional[Path]:
    hits = list(PROJECTS.glob(f"*/{session_id}.jsonl"))
    return hits[0] if hits else None


def harness(workdir: Path) -> Tuple[Dict[str, Dict], Dict[str, Dict], Dict[str, Dict]]:
    """(per-wave totals from transcripts, per-label totals, per-wave totals from ResultMessage.usage)."""
    runs = [r for r in read_runs(workdir) if r.get("label")]
    sessions: Dict[str, str] = OrderedDict()
    sdk: Dict[str, Dict] = OrderedDict()
    for r in runs:
        if r.get("session_id"):
            sessions.setdefault(r["session_id"], r["label"])
        u = r.get("usage") or {}
        rec = {k: int(u.get(k) or 0) for k in FIELDS}
        rec["total"] = sum(rec.values())
        rec["calls"] = 1
        rec["num_turns"] = int(r.get("num_turns") or 0)
        sdk[wave_of(r["label"])] = _add(sdk.get(wave_of(r["label"]), {}), rec)
    by_label: Dict[str, Dict] = OrderedDict()
    waves: Dict[str, Dict] = OrderedDict()
    for sid, label in sessions.items():
        path = find_transcript(sid)
        if path is None:
            continue
        tot = summarize(message_usage(path))
        tot["agents"] = 1
        by_label[label] = _add(by_label.get(label, {}), tot)
        waves[wave_of(label)] = _add(waves.get(wave_of(label), {}), tot)
    return waves, by_label, sdk


def row_tokens(record: Mapping[str, Any]) -> int:
    u = record.get("usage") or {}
    return sum(int(u.get(k) or 0) for k in FIELDS) if isinstance(u, dict) else 0


def dur(ms: int) -> str:
    s = (ms or 0) / 1000.0
    if s < 90:
        return f"{s:.1f}s"
    if s < 3600:
        return f"{int(s // 60)}m{int(s % 60):02d}s"
    return f"{int(s // 3600)}h{int(s % 3600 // 60):02d}m"


def run_rows(workdir: Path, latest_only: bool = False) -> List[Dict[str, Any]]:
    """Per-label accounting, aggregated from `.harness/runs.jsonl` alone (never from live objects)."""
    agg: Dict[str, Dict[str, Any]] = OrderedDict()
    for r in read_runs(workdir, latest_only=latest_only):
        label = r.get("label")
        if not label:            # pipeline_start and other non-call rows
            continue
        a = agg.setdefault(label, {"label": label, "agent": r.get("agent") or "—", "attempts": 0,
                                   "tokens": 0, "duration_ms": 0, "retries": 0, "kinds": []})
        if r.get("agent"):
            a["agent"] = r["agent"]
        a["attempts"] += 1
        a["tokens"] += row_tokens(r)
        try:
            a["duration_ms"] += int(r.get("duration_ms") or 0)
        except (TypeError, ValueError):
            pass
        try:
            if int(r.get("attempt") or 1) > 1:
                a["retries"] += 1
        except (TypeError, ValueError):
            pass
        kind = r.get("kind")
        if kind and kind not in a["kinds"]:
            a["kinds"].append(str(kind))
    return list(agg.values())


def run_summary(workdir: Path, latest_only: bool = False) -> str:
    """The short table printed when the pipeline ends (also on a failed exit)."""
    all_rows = read_runs(workdir)
    if not all_rows:
        return f"运行记账：{Path(workdir) / '.harness' / 'runs.jsonl'} 无记录。"
    ids = run_ids(all_rows)
    rows = run_rows(workdir, latest_only=latest_only)
    scope = f"仅最近一次启动 run_id={ids[-1]}" if latest_only else f"{len(ids)} 次启动累计"
    out = [f"运行记账汇总（.harness/runs.jsonl · {scope}）",
           "| 标签 | agent | 尝试 | 总 token | 总耗时 | 重试 | kind |",
           "|---|---|---|---:|---:|---:|---|"]
    tot = {"attempts": 0, "tokens": 0, "duration_ms": 0, "retries": 0}
    for a in rows:
        for k in tot:
            tot[k] += a[k]
        out.append(f"| {a['label']} | {a['agent']} | {a['attempts']} | {fmt(a['tokens'])} | "
                   f"{dur(a['duration_ms'])} | {a['retries']} | {'/'.join(a['kinds']) or '—'} |")
    out.append(f"| **合计** | {len(rows)} 个标签 | {tot['attempts']} | **{fmt(tot['tokens'])}** | "
               f"**{dur(tot['duration_ms'])}** | {tot['retries']} | |")
    return "\n".join(out)


def fmt(n: Optional[int]) -> str:
    return "—" if n is None else f"{n:,}"


def table(base_w: Dict[str, Dict], orch: Dict[str, Dict], h_w: Dict[str, Dict]) -> str:
    rows = ["| 波次 | 基线 agents | 基线 turns | 基线 tokens | harness 会话 | harness turns | harness tokens | 变化 |",
            "|---|---|---|---|---|---|---|---|"]
    bt = ht = 0
    for w in ["W2", "W3", "W4", "W5", "W6", "W7", "W8"]:
        b, h = base_w.get(w, {}), h_w.get(w, {})
        bt += b.get("total", 0)
        ht += h.get("total", 0)
        delta = f"{(h.get('total', 0) / b['total'] - 1):+.0%}" if b.get("total") else "—"
        rows.append(f"| {w} | {b.get('agents', 0)} | {b.get('turns', 0)} | {fmt(b.get('total'))} | {h.get('agents', 0)} | "
                    f"{h.get('turns', 0)} | {fmt(h.get('total', 0))} | {delta} |")
    o = orch.get("W2–W8-phase", {}).get("total", 0)
    rows.append(f"| 编排者（W2–W8 段） | LLM | {orch.get('W2–W8-phase', {}).get('turns', 0)} | {fmt(o)} | Python | 0 | 0 | −100% |")
    rows.append(f"| **W2→W8 合计** | | | **{fmt(bt + o)}** | | | **{fmt(ht)}** | **{(ht / (bt + o) - 1):+.0%}** |" if bt + o else "")
    return "\n".join(rows)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):      # argparse errors are Chinese too
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-session", help="required unless --runs")
    ap.add_argument("--workdir")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--runs", action="store_true", help="only the run-log accounting summary (no transcripts)")
    ap.add_argument("--latest-run", action="store_true", help="with --runs: only the last pipeline start")
    a = ap.parse_args(argv)
    if a.runs:
        if not a.workdir:
            ap.error("--runs 需要 --workdir")
        if a.json:
            print(json.dumps(run_rows(Path(a.workdir), a.latest_run), ensure_ascii=False, indent=2, default=str))
        else:
            print(run_summary(Path(a.workdir), a.latest_run))
        return 0
    if not a.baseline_session:
        ap.error("--baseline-session 必填（或用 --runs 只看运行记账汇总）")
    bw, orch = baseline(a.baseline_session)
    hw, hl, sdk = harness(Path(a.workdir)) if a.workdir else ({}, {}, {})
    if a.json:
        print(json.dumps({"baseline": bw, "orchestrator": orch, "harness": hw, "harness_by_label": hl, "harness_sdk_usage": sdk},
                         ensure_ascii=False, indent=2, default=str))
    else:
        print(table(bw, orch, hw))
    return 0


if __name__ == "__main__":
    sys.exit(main())
