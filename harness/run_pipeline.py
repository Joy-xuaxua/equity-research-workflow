"""CLI for the Phase-1 harness.

    # fresh workdir from a finished run's archived collection, then W2→W8
    python -m harness.run_pipeline fixture --source research/安莉芳_1388HK_20260923 --workdir research/安莉芳_1388HK_20261017-harness

    # new research: Step 0 brief + tree, then W1→W8
    python -m harness.run_pipeline init --workdir research/X_0000HK_20261017 --company X --ticker 0000.HK --exchange HKEX --currency 港元
    python -m harness.run_pipeline run --workdir research/X_0000HK_20261017

    # resume after a crash / Ctrl-C: `run` always continues from the first unfinished step
    python -m harness.run_pipeline run --workdir <dir> [--from W5] [--stop-after W4]
    python -m harness.run_pipeline status --workdir <dir>

Backends: `sdk` (default; Claude Agent SDK, inherits ANTHROPIC_BASE_URL / ANTHROPIC_MODEL / auth from this
environment) or `replay --replay-source <finished run>` (no LLM; exercises gates, scripts, assembly, PDF).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import anyio

from .backend import AuthError, ReplayBackend, SDKBackend
from .config import RuntimeConfig
from .pipeline import Pipeline
from .state import STEPS, State
from .steps import make_tree, prepare_fixture, write_brief


def _backend_factory(args, cfg: RuntimeConfig):
    def make(p: Pipeline):
        if args.backend == "replay":
            src = Path(args.replay_source or p.brief.get("fixture_source", ""))
            return ReplayBackend(src.resolve(), p.workdir, p.state.log_run)

        def on_retry(label, kind, wait, attempt):
            p.log.add(f"{label}-重试", f"API {kind}（第 {attempt} 次）→ 退避 {wait:.0f}s 后在同一会话续跑（不重派）", "API 级重试")
        return SDKBackend(cfg, p.workdir, p.state.set_session, p.state.log_run, on_retry)
    return make


def _cfg(args) -> RuntimeConfig:
    return RuntimeConfig(model=args.model, effort=args.effort, cli_path=args.cli_path, max_parallel=args.max_parallel)


async def _run(args, workdir: Path, fixture: bool) -> int:
    cfg = _cfg(args)
    pipe = Pipeline(workdir, cfg, _backend_factory(args, cfg), fixture=fixture, recollect=not args.no_recollect)
    if args.from_step:
        pipe.state.reset_from(args.from_step)
        pipe.log.add("Harness", f"按 --from 从 {args.from_step} 重跑（其后检查点清除）", "")
    try:
        await pipe.run(stop_after=args.stop_after)
    except AuthError as exc:
        pipe.log.add("Harness-中止", "Claude Code CLI 未认证，无法派发 agent", str(exc)[:160])
        print("\n[harness] 认证失败：请在终端运行 `claude` 完成 /login，或设置 CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY 后用 run 续跑。", file=sys.stderr)
        return 3
    return 0


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m harness.run_pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--workdir", required=True)
        p.add_argument("--backend", choices=["sdk", "replay"], default="sdk")
        p.add_argument("--replay-source", help="finished run whose outputs the replay backend copies")
        p.add_argument("--model", help="override ANTHROPIC_MODEL")
        p.add_argument("--effort", help="override CLAUDE_EFFORT / settings effortLevel")
        p.add_argument("--cli-path", help="claude executable (default: HARNESS_CLI_PATH or the SDK-bundled one)")
        p.add_argument("--max-parallel", type=int, default=5)
        p.add_argument("--from", dest="from_step", choices=STEPS)
        p.add_argument("--stop-after", choices=STEPS)
        p.add_argument("--no-recollect", action="store_true", help="never run targeted re-collection")

    fx = sub.add_parser("fixture", help="prepare a workdir from a finished run's collection, then run W2→W8")
    fx.add_argument("--source", required=True)
    common(fx)

    it = sub.add_parser("init", help="Step 0: write brief.json and the workdir tree")
    it.add_argument("--workdir", required=True)
    for k in ("company", "ticker", "exchange", "currency"):
        it.add_argument(f"--{k}", required=True)
    it.add_argument("--mode", choices=["full", "earnings"], default="full")
    it.add_argument("--language", choices=["zh", "en"], default="zh")
    it.add_argument("--format", choices=["pdf", "md", "docx", "xlsx"], default="pdf")
    it.add_argument("--fiscal-year", default="")
    it.add_argument("--fiscal-period", default="")
    it.add_argument("--ah-listing", action="store_true")
    it.add_argument("--cn-adr", action="store_true")
    it.add_argument("--prior-report", default="none")

    rn = sub.add_parser("run", help="run / resume the pipeline from the first unfinished step")
    common(rn)

    st = sub.add_parser("status", help="show checkpoints")
    st.add_argument("--workdir", required=True)

    args = ap.parse_args(argv)
    workdir = Path(args.workdir).resolve()

    if args.cmd == "init":
        make_tree(workdir)
        brief = write_brief(workdir, {
            "company": args.company, "ticker": args.ticker, "exchange": args.exchange, "currency": args.currency,
            "mode": args.mode, "language": args.language, "format": args.format, "fiscal_year": args.fiscal_year,
            "fiscal_period": args.fiscal_period, "ah_listing": args.ah_listing, "cn_adr": args.cn_adr,
            "prior_report": args.prior_report, "coverage": "continuing" if args.prior_report != "none" else "initiation"})
        print(json.dumps(brief, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "status":
        s = State(workdir)
        for step in STEPS:
            print(f"{step:6s} {s.data['completed'].get(step, '-')}")
        print(json.dumps(s.data["gates"], ensure_ascii=False, indent=2)[:2000])
        return 0
    if args.cmd == "fixture":
        if not (workdir / "brief.json").exists():
            brief, notes = prepare_fixture(Path(args.source).resolve(), workdir)
            if args.backend == "replay" and not args.replay_source:
                args.replay_source = args.source
            from .orchlog import OrchLog
            log = OrchLog(workdir, f"{brief['company']}（{brief['ticker']}）{brief.get('mode')} 模式 · Python harness")
            log.add("Step 0", "fixture 工作目录建成：brief.json＋目录树", "；".join(notes))
        return anyio.run(_run, args, workdir, True)
    return anyio.run(_run, args, workdir, False)


if __name__ == "__main__":
    sys.exit(main())
