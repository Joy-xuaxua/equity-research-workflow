"""Token accounting, measured the same way as the recorded baseline: sum `usage` per assistant message
id (max over the streamed copies of one message) from Claude Code transcripts.

Baseline: `~/.claude/projects/<proj>/<session>/subagents/*.jsonl` grouped by `meta.json` description
(`W1 …` … `W8 …`), plus the orchestrator's own transcript split at the first W2 dispatch.
Harness: the SDK sessions recorded in `<workdir>/.harness/runs.jsonl`, located by session id under
`~/.claude/projects/*/<session_id>.jsonl`.

    python -m harness.tokens --baseline-session 182f7618-9cf8-457c-bf0b-ab730c0e9653 --workdir <harness workdir>
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
from typing import Dict, Iterable, List, Optional, Tuple

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
    runs = [json.loads(l) for l in (workdir / ".harness" / "runs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
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
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-session", required=True)
    ap.add_argument("--workdir")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
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
