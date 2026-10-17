"""Agent execution backends.

`SDKBackend` runs one agent through the Claude Agent SDK and owns API-level resilience:
a failed call (429 / 400 content filter / 5xx / empty reply / crashed CLI) is retried with
backoff by *resuming the same session* — the work already done stays in context and on disk —
instead of re-launching the agent from scratch (the 1388.HK run needed 10 collector launches for
4 lines because every failure meant a fresh agent).

`ReplayBackend` copies a finished run's outputs into the workdir; it exercises the whole state
machine (validators, gates, assembly, lint, checker, PDF) without any LLM call.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import anyio

from .config import AGENTS_DIR, RuntimeConfig
from .util import now, read, write


class AuthError(RuntimeError):
    """The CLI cannot authenticate — retrying will not help; the pipeline stops with a clear message."""


class AgentFailed(RuntimeError):
    pass


@dataclass
class AgentCall:
    label: str                      # e.g. "W4:2+3"
    agent: str                      # agent file stem, e.g. "equity-chapter-writer"
    prompt: str                     # first user message (PARAMS + task + preloaded files)
    addendum: str = ""              # appended to the agent body (harness-mode overrides)
    tools: Optional[List[str]] = None
    resume: Optional[str] = None    # session id to continue (fix rounds, write-backs, retries)
    max_turns: int = 40
    kind: str = "dispatch"          # dispatch | fix | writeback | retry


@dataclass
class AgentResult:
    label: str
    agent: str
    session_id: Optional[str]
    text: str
    ok: bool
    num_turns: int = 0
    usage: Dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0
    attempts: int = 1
    errors: List[str] = field(default_factory=list)
    tool_calls: int = 0

    def report(self) -> Optional[dict]:
        """The HARNESS_REPORT trailer: the last ```json fenced block of the final message."""
        blocks = re.findall(r"```json\s*(?:HARNESS_REPORT)?\s*\n(.*?)```", self.text or "", flags=re.S)
        for b in reversed(blocks):
            try:
                return json.loads(b)
            except ValueError:
                continue
        return None


def load_agent(name: str) -> tuple[str, List[str]]:
    """(body without frontmatter, tools from frontmatter) of `.claude/agents/<name>.md`."""
    text = read(AGENTS_DIR / f"{name}.md")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, flags=re.S)
    tools: List[str] = []
    if m:
        tm = re.search(r"^tools:\s*(.+)$", m.group(1), flags=re.M)
        if tm:
            tools = [t.strip() for t in tm.group(1).split(",") if t.strip()]
        text = text[m.end():]
    return text.strip(), tools


# ---- error classification -----------------------------------------------------------

_AUTH = re.compile(r"not logged in|please run /login|invalid api key|authentication_error|401", re.I)
_RATE = re.compile(r"429|rate.?limit|usage limit|too many requests|quota|限流|额度", re.I)
_FILTER = re.compile(r"1301|content.?filter|sensitive|敏感|inappropriate", re.I)
_RESET = re.compile(r"reset[s]?\s*(?:at)?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(am|pm)?", re.I)
_RESET_AMPM = re.compile(r"reset[s]?\s*(?:at)?\s*(\d{1,2})\s*(am|pm)", re.I)


def classify(status: Optional[int], text: str) -> str:
    if _AUTH.search(text or ""):
        return "auth"
    if status == 429 or _RATE.search(text or ""):
        return "rate_limit"
    if _FILTER.search(text or ""):
        return "content_filter"
    if status in (500, 502, 503, 504, 529) or re.search(r"overloaded|5\d\d|timeout|ECONNRESET|socket", text or "", re.I):
        return "server"
    return "other"


def reset_wait(text: str, cap: float) -> Optional[float]:
    """Seconds until a usage-window reset quoted in a 429 message ("resets 5am", "resets at 05:13:50")."""
    m = _RESET.search(text or "") or _RESET_AMPM.search(text or "")
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.re is _RESET and m.group(2) else 0
    ampm = (m.group(4) if m.re is _RESET else m.group(2)) or ""
    if ampm.lower() == "pm" and hour < 12:
        hour += 12
    if ampm.lower() == "am" and hour == 12:
        hour = 0
    nowdt = _dt.datetime.now()
    target = nowdt.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
    if target <= nowdt:
        target += _dt.timedelta(days=1)
    return min((target - nowdt).total_seconds() + 60, cap)


RESUME_PROMPTS = {
    "rate_limit": "（harness）上一次 API 调用被限流，已等待后恢复本会话。请从中断处继续完成原任务；已落盘的文件不要重写，除非尚未完成。",
    "content_filter": "（harness）上一次 API 调用被内容过滤拦截（400）。请从中断处继续，但控制单次读取与引用体量：只摘录最小必要片段，避免整段转贴外部原文。",
    "server": "（harness）上一次 API 调用因服务端错误中断，已恢复本会话。请从中断处继续完成原任务。",
    "empty": "（harness）你的上一轮回复为空或在完成前结束。请继续完成原任务：写出全部输出文件，并按回报格式给出小结与 HARNESS_REPORT JSON。",
    "other": "（harness）上一次调用异常中断，已恢复本会话。请从中断处继续完成原任务。",
}


# ---- SDK backend ---------------------------------------------------------------------

class SDKBackend:
    name = "sdk"

    def __init__(self, cfg: RuntimeConfig, workdir: Path, on_session: Callable[[str, str], None],
                 on_run: Callable[[dict], None], on_retry: Callable[[str, str, float, int], None]):
        self.cfg, self.workdir = cfg, workdir
        self.on_session, self.on_run, self.on_retry = on_session, on_run, on_retry
        self.logdir = workdir / ".harness" / "logs"
        self.logdir.mkdir(parents=True, exist_ok=True)

    def _options(self, call: AgentCall, system_prompt: str, tools: List[str], resume: Optional[str]):
        from claude_agent_sdk import ClaudeAgentOptions
        from .config import ORCH_ROOT, SKILL_ROOT
        builtin = [t for t in tools if not t.startswith("mcp__")]
        kwargs = dict(
            system_prompt=system_prompt,
            tools=builtin,
            allowed_tools=tools,
            permission_mode="acceptEdits",
            cwd=str(self.workdir),
            add_dirs=[str(SKILL_ROOT), str(ORCH_ROOT)],
            setting_sources=[],          # isolation: no CLAUDE.md / user hooks; model & auth still come from env
            max_turns=call.max_turns,
            resume=resume,
            env=dict(self.cfg.env_overrides),
            stderr=lambda s: self._log(call.label, f"[stderr] {s.rstrip()[:400]}"),
        )
        if self.cfg.resolved_model():
            kwargs["model"] = self.cfg.resolved_model()
        if self.cfg.resolved_effort():
            kwargs["effort"] = self.cfg.resolved_effort()
        if self.cfg.resolved_cli_path():
            kwargs["cli_path"] = self.cfg.resolved_cli_path()
        return ClaudeAgentOptions(**kwargs)

    def _log(self, label: str, line: str) -> None:
        safe = re.sub(r"[^\w+.-]", "_", label)
        with open(self.logdir / f"{safe}.log", "a", encoding="utf-8") as f:
            f.write(f"{now('%H:%M:%S')} {line}\n")

    async def _once(self, call: AgentCall, prompt: str, resume: Optional[str], system_prompt: str, tools: List[str]) -> dict:
        from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage, query
        from claude_agent_sdk.types import TextBlock, ToolUseBlock
        out = {"session_id": resume, "result": None, "is_error": False, "status": None, "text": "",
               "usage": {}, "num_turns": 0, "duration_ms": 0, "tool_calls": 0, "exc": None}
        texts: List[str] = []
        try:
            async for m in query(prompt=prompt, options=self._options(call, system_prompt, tools, resume)):
                if isinstance(m, SystemMessage) and m.subtype == "init":
                    sid = (m.data or {}).get("session_id")
                    if sid:
                        out["session_id"] = sid
                        self.on_session(call.label, sid)
                elif isinstance(m, AssistantMessage):
                    for b in m.content:
                        if isinstance(b, ToolUseBlock):
                            out["tool_calls"] += 1
                            arg = b.input.get("file_path") or b.input.get("command") or b.input.get("pattern") or b.input.get("url") or ""
                            self._log(call.label, f"tool {b.name} {str(arg)[:160]}")
                        elif isinstance(b, TextBlock) and b.text.strip():
                            texts.append(b.text)
                            self._log(call.label, f"text {b.text.strip()[:200]!r}")
                elif isinstance(m, ResultMessage):
                    out.update(session_id=m.session_id or out["session_id"], is_error=m.is_error,
                               status=m.api_error_status, usage=m.usage or {}, num_turns=m.num_turns,
                               duration_ms=m.duration_ms, result=m.result)
                    if m.session_id:
                        self.on_session(call.label, m.session_id)
        except Exception as exc:  # noqa: BLE001 — classified below; SDK raises after an error result
            out["exc"] = f"{type(exc).__name__}: {exc}"
            self._log(call.label, f"exception {out['exc'][:400]}")
        out["text"] = out["result"] if out["result"] else ("\n".join(texts[-1:]) if texts else "")
        return out

    async def run(self, call: AgentCall) -> AgentResult:
        body, fm_tools = ("", []) if call.agent == "__inline__" else load_agent(call.agent)
        tools = call.tools if call.tools is not None else fm_tools
        system_prompt = (body + "\n\n" + call.addendum).strip()
        prompt, resume = call.prompt, call.resume
        total: Dict[str, int] = {}
        errors: List[str] = []
        turns = dur = tcalls = 0
        attempt = 0
        while True:
            attempt += 1
            t0 = time.time()
            r = await self._once(call, prompt, resume, system_prompt, tools)
            for k, v in (r["usage"] or {}).items():
                if isinstance(v, int):
                    total[k] = total.get(k, 0) + v
            turns += r["num_turns"] or 0
            dur += r["duration_ms"] or int((time.time() - t0) * 1000)
            tcalls += r["tool_calls"]
            self.on_run({"ts": now(), "label": call.label, "agent": call.agent, "kind": call.kind if attempt == 1 else "retry",
                         "attempt": attempt, "session_id": r["session_id"], "num_turns": r["num_turns"],
                         "usage": r["usage"], "duration_ms": r["duration_ms"], "is_error": r["is_error"],
                         "api_error_status": r["status"], "exc": r["exc"], "tool_calls": r["tool_calls"]})
            failed = r["is_error"] or r["exc"] is not None
            empty = not failed and not (r["text"] or "").strip() and r["tool_calls"] == 0
            if not failed and not empty:
                return AgentResult(call.label, call.agent, r["session_id"], r["text"] or "", True, turns, total,
                                   dur, attempt, errors, tcalls)
            msg = " ".join(x for x in [r["result"] or "", r["exc"] or ""] if x)
            kind = "empty" if empty else classify(r["status"], msg)
            errors.append(f"{kind}: {msg[:300]}")
            if kind == "auth":
                raise AuthError(msg.strip()[:300])
            if attempt >= self.cfg.max_attempts:
                raise AgentFailed(f"{call.label}: {attempt} 次尝试后仍失败：{errors[-1]}")
            if kind == "rate_limit":
                wait = reset_wait(msg, self.cfg.rate_limit_cap) or min(self.cfg.backoff_base * 4 * 2 ** (attempt - 1), self.cfg.rate_limit_cap)
            else:
                wait = min(self.cfg.backoff_base * 2 ** (attempt - 1), self.cfg.backoff_cap)
            self.on_retry(call.label, kind, wait, attempt)
            await anyio.sleep(wait)
            if r["session_id"]:
                resume, prompt = r["session_id"], RESUME_PROMPTS[kind]
            # else: the session never started — resend the original prompt as a fresh call


# ---- Replay backend ------------------------------------------------------------------

class ReplayBackend:
    """Deterministic stand-in for the LLM: copies a finished run's agent outputs (test fixture only)."""
    name = "replay"

    OUTPUTS = {
        "W2": ["forensic/ledger.md", "forensic/financials.csv", "forensic/adjudications.json", "forensic/derived-inputs.json"],
        "W3": ["quality/earnings-quality.md", "quality/grade.json"],
        "W5": ["valuation/assumptions.json", "valuation/dcf-output.txt", "valuation/valuation-notes.md", "chapters/ch06-*.md"],
        "W5R": ["valuation/assumptions.v2.json", "valuation/dcf-output.v2.txt", "valuation/valuation-notes.md", "chapters/ch06-*.md"],
        "W6": ["redteam/redteam-feedback.md"],
        "W7": ["chapters/ch01-*.md", "chapters/ch09-*.md"],
    }

    def __init__(self, source: Path, workdir: Path, on_run: Callable[[dict], None]):
        self.source, self.workdir, self.on_run = source, workdir, on_run

    def _copy(self, pattern: str) -> List[str]:
        done = []
        for src in sorted(self.source.glob(pattern)):
            dst = self.workdir / src.relative_to(self.source)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            done.append(dst.relative_to(self.workdir).as_posix())
        return done

    async def run(self, call: AgentCall) -> AgentResult:
        base = call.label.split(":")[0]
        copied: List[str] = []
        report: dict = {}
        if call.kind == "dispatch":
            if base == "W4":
                for nn in call.label.split(":")[1].split("+"):
                    copied += self._copy(f"chapters/ch{int(nn):02d}-*.md")
            else:
                for pat in self.OUTPUTS.get(base, []):
                    copied += self._copy(pat)
            if base == "W6":
                copied.append(self._sidecar())
            if base == "W3":
                report = {"grade": json.loads(read(self.workdir / "quality/grade.json"))["grade"],
                          "acceptance": "pass", "escalations": []}
            if base == "W7":
                report = {"status": "ok"}
        self.on_run({"ts": now(), "label": call.label, "agent": call.agent, "kind": call.kind, "attempt": 1,
                     "session_id": f"replay-{call.label}", "num_turns": 0, "usage": {}, "duration_ms": 0,
                     "is_error": False, "api_error_status": None, "exc": None, "tool_calls": len(copied)})
        text = f"replay: {', '.join(copied) or '无改动（回放后端不执行修正指令）'}\n```json\n{json.dumps(report, ensure_ascii=False)}\n```"
        return AgentResult(call.label, call.agent, f"replay-{call.label}", text, True)

    def _sidecar(self) -> str:
        """Build redteam-findings.json from the replayed markdown table (the replayed run predates the sidecar)."""
        from .validators import STRENGTHS
        md = read(self.workdir / "redteam" / "redteam-feedback.md")
        findings = []
        for line in md.splitlines():
            m = re.match(r"^\|\s*(R\d+)\s*\|", line)
            if not m:
                continue
            cells = [c.strip().strip("*") for c in line.strip().strip("|").split("|")]
            strength = next((c for c in cells[1:] if c in STRENGTHS), None)
            if strength is None:
                continue
            target = cells[-1] if len(cells) > 4 else "ch1 风险"
            findings.append({"id": m.group(1), "statement": cells[1][:120], "strength": strength,
                             "targets": [t.strip() for t in re.split(r"[；;、/]", target) if t.strip()] or ["ch1 风险"]})
        sc = {"generated": now(), "three_questions": {"verdict": "通过"}, "findings": findings,
              "consistency": {"label_matches_dcf": True, "gap_consistent": True, "veto_chain_ok": True,
                              "probabilities_match_evidence": True},
              "revision_recommended": any(f["strength"] in ("中强", "强") for f in findings),
              "forecast_review": "none"}
        write(self.workdir / "redteam" / "redteam-findings.json", json.dumps(sc, ensure_ascii=False, indent=2) + "\n")
        return "redteam/redteam-findings.json"
