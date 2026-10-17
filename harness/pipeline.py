"""The wave/gate state machine (SKILL.md §3) with per-step checkpoints.

Every step is re-entrant: on resume the harness re-runs deterministic work (idempotent scripts)
and, for agent steps, either skips an agent that already returned, resumes the session of one that
was cut off, or dispatches it fresh. Every dispatch, gate decision and failure path is written to
the append-only orchestration-log.md.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import anyio

from . import roles, steps, validators as V
from .backend import AgentCall, AgentResult, RESUME_PROMPTS
from .config import INDUSTRIES, RuntimeConfig
from .orchlog import OrchLog
from .pdf import convert
from .state import STEPS, State
from .util import read, read_json, sha256, write, write_json

LINES = {"full": ["01-disclosure", "02-market", "03-consensus", "04-industry"],
         "earnings": ["01-disclosure", "02-consensus", "03-communication", "04-market"]}
WRITER_SPLITS = {"full": ["2+3", "4", "5", "7", "8"], "earnings": ["2", "3+4", "5", "6", "7"]}


def fix_prompt(problems: Sequence[V.Problem], extra: str = "") -> str:
    body = "\n".join(f"- {p}" for p in problems)
    return ("（harness 交接校验未通过）以下问题须在本会话内修正——只改被点名处，其他内容不动；改完按原回报格式小结并附 HARNESS_REPORT：\n"
            + body + (("\n" + extra) if extra else ""))


class Pipeline:
    def __init__(self, workdir: Path, cfg: RuntimeConfig, backend_factory: Callable[["Pipeline"], object],
                 fixture: bool = False, recollect: bool = True):
        self.workdir = workdir.resolve()
        self.cfg = cfg
        self.brief = read_json(self.workdir / "brief.json")
        self.state = State(self.workdir)
        self.log = OrchLog(self.workdir, f"{self.brief['company']}（{self.brief['ticker']}）{self.brief.get('mode')} 模式 · Python harness")
        self.fixture = fixture or bool(self.brief.get("fixture_source"))
        self.recollect = recollect and not self.fixture
        self.backend = backend_factory(self)
        self.limiter = anyio.CapacityLimiter(cfg.max_parallel)

    # ------------------------------------------------------------------ driver
    async def run(self, stop_after: Optional[str] = None) -> None:
        if not self.state.note("started"):
            self.state.note("started", True)
            self.log.add("Harness", f"启动（backend={getattr(self.backend, 'name', '?')}）", self.cfg.banner())
        while True:
            step = self.state.next_step()
            if step is None:
                return
            await getattr(self, f"step_{step}")()
            self.state.mark(step)
            if stop_after and step == stop_after:
                self.log.add("Harness", f"按 --stop-after 停在 {step} 之后", "检查点已保存，可 run --workdir 续跑")
                return

    @property
    def gates(self) -> Dict:
        return self.state.data["gates"]

    def mode(self) -> str:
        return self.brief.get("mode", "full")

    def reload_brief(self) -> None:
        self.brief = read_json(self.workdir / "brief.json")

    # ------------------------------------------------------------------ agent + fix loop
    async def agent(self, label: str, spec: roles.Spec, validate: Callable[[], List[V.Problem]],
                    kind: str = "dispatch", resume: Optional[str] = None,
                    max_fix: Optional[int] = None) -> Tuple[Optional[AgentResult], List[V.Problem]]:
        """Dispatch (or resume) one agent, then validate → same-session fix rounds (≤ max_fix)."""
        add_path = self.workdir / ".harness" / "addenda" / (re.sub(r"[^\w+.-]", "_", label) + ".md")
        if spec.addendum:
            if kind == "dispatch" or not add_path.exists():
                write(add_path, spec.addendum)
        elif add_path.exists():
            # A resumed session must get the same system prompt (it is not stored in the transcript).
            spec = roles.Spec(spec.agent, spec.prompt, read(add_path), spec.tools, spec.max_turns)
        status_key = f"agent:{label}:{kind}"
        status = self.state.note(status_key)
        res: Optional[AgentResult] = None
        if status != "returned":
            prior = self.state.session(label) if status == "running" else None
            if prior and kind == "dispatch":
                call = AgentCall(label, spec.agent, RESUME_PROMPTS["other"], spec.addendum, spec.tools,
                                 resume=prior, max_turns=spec.max_turns, kind="retry")
                self.log.add(f"{label}-恢复", "检查点显示该 agent 上次未返回，恢复原会话续跑（不重派）", f"session={prior[:8]}")
            else:
                call = AgentCall(label, spec.agent, spec.prompt, spec.addendum, spec.tools, resume=resume,
                                 max_turns=spec.max_turns, kind=kind)
            self.state.note(status_key, "running")
            async with self.limiter:
                res = await self.backend.run(call)
            self.state.set_session(label, res.session_id)
            self.state.note(status_key, "returned")
            self.state.note(f"report:{label}:{kind}", res.report() or {})
            self.state.note(f"text:{label}:{kind}", (res.text or "")[-4000:])
        problems = validate()
        rounds = self.cfg.max_fix_rounds if max_fix is None else max_fix
        r = 0
        while V.blocking(problems) and r < rounds:
            r += 1
            sid = self.state.session(label)
            self.log.add(f"{label}-校验", f"{len(V.blocking(problems))} 项阻断 → 同会话修正第 {r} 轮",
                         "；".join(p.code for p in V.blocking(problems))[:200])
            call = AgentCall(label, spec.agent, fix_prompt(V.blocking(problems)), spec.addendum, spec.tools,
                             resume=sid, max_turns=spec.max_turns, kind="fix")
            async with self.limiter:
                res = await self.backend.run(call)
            self.state.set_session(label, res.session_id)
            if res.report():
                self.state.note(f"report:{label}:{kind}", res.report())
            problems = validate()
        return res, problems

    def report(self, label: str, kind: str = "dispatch") -> Dict:
        return self.state.note(f"report:{label}:{kind}") or {}

    # ================================================================== W1 / G1 / H1
    async def step_W1(self) -> None:
        if self.fixture:
            self.log.add("W1", "跳过（fixture：沿用既有采集原件为 collection/）", "基准对照只重跑 W2→W8")
            return
        lines = LINES[self.mode()]
        self.log.add("W1", f"派发 equity-data-collector ×{len(lines)} 并行（{'/'.join(lines)}）", "单线失败不阻塞；API 失败在同会话退避续跑")

        async def one(line: str):
            spec = roles.collector(self.workdir, self.brief, self.gates, line)

            def validate():
                f = self.workdir / "collection" / f"{line}.md"
                if not f.exists():
                    return [V.Problem("P1", "COLLECTION_FILE_MISSING", f"缺 collection/{line}.md")]
                probs, _ = V.registry(self.workdir / "collection", self.mode(), normalize=False)
                return [p for p in probs if p.file.endswith(f"{line}.md")]
            _, probs = await self.agent(f"W1:{line}", spec, validate)
            self.log.add(f"W1:{line}", "返回" + (f"（遗留 {len(V.blocking(probs))} 项阻断，交 H1 机械修复/W2 手工勾稽）" if V.blocking(probs) else ""),
                         str(self.report(f"W1:{line}").get("registered", "")) + " 条登记")

        async with anyio.create_task_group() as tg:
            for ln in lines:
                tg.start_soon(one, ln)
        self.log.add("W1", "四线全部返回，进 G1", "")

    async def step_G1(self) -> None:
        ic = next((p for d in ("collection", "collection-deprecated") for p in [self.workdir / d / "industry-classification.md"] if p.exists()), None)
        if ic is not None:
            head = read(ic).splitlines()[:3]
            main = next((l.split(":", 1)[1].strip() for l in head if l.startswith("主附录:")), "")
            sec = next((l.split(":", 1)[1].strip() for l in head if l.startswith("次附录:")), "none")
            ind = main + (f",{sec}" if sec and sec != "none" else "")
            if ind and self.brief.get("industry") != ind:
                self.brief["industry"] = ind
                write_json(self.workdir / "brief.json", self.brief)
            self.log.add("G1", f"沿用已有分类：主附录 {main}、次附录 {sec}", "industry-classification.md 已存在（fixture）")
            return
        spec = roles.g1(self.workdir, self.brief)

        def validate():
            txt = self.state.note("text:G1:dispatch") or ""
            m = re.search(r"主附录:\s*([a-z-]+)", txt)
            if not m or not (INDUSTRIES / f"{m.group(1)}.md").exists():
                return [V.Problem("P1", "G1_SLUG_INVALID", "首行须为「主附录: <slug>」且 slug 存在于 industries/")]
            return []
        res, probs = await self.agent("G1", spec, validate)
        txt = res.text if res else self.state.note("text:G1:dispatch")
        main = re.search(r"主附录:\s*([a-z-]+)", txt).group(1)
        sm = re.search(r"次附录:\s*([a-z-]+)", txt)
        sec = sm.group(1) if sm and (INDUSTRIES / f"{sm.group(1)}.md").exists() else "none"
        reason = txt.split("理由", 1)[1].strip(" ：:\n") if "理由" in txt else ""
        write(self.workdir / "collection" / "industry-classification.md", f"主附录: {main}\n次附录: {sec}\n\n选择理由：{reason}\n")
        self.brief["industry"] = main + ("" if sec == "none" else f",{sec}")
        write_json(self.workdir / "brief.json", self.brief)
        self.log.add("G1", f"行业分类：主附录 {main}、次附录 {sec}，回填 brief.industry", reason[:120])

    async def step_H1(self) -> None:
        coll = self.workdir / "collection"
        probs, actions = V.registry(coll, self.mode(), normalize=True)
        for a in actions:
            self.log.add("H1-机械修复", a, "登记块语法改写不改值；否则该线条目漏出机器对撞（1388.HK 原跑 74 条即因此漏检）")
        report = "\n".join(actions + [str(p) for p in probs]) or "OK：登记块全部可被 collision_check 解析，key/单位/期间/锚均通过"
        write(self.workdir / ".harness" / "registry-check.txt", report)
        blocking = V.blocking(probs)
        if blocking and not self.fixture:
            by_line: Dict[str, List[V.Problem]] = {}
            for p in blocking:
                by_line.setdefault(Path(p.file).stem, []).append(p)
            for line, ps in by_line.items():
                sid = self.state.session(f"W1:{line}")
                if sid:
                    spec = roles.collector(self.workdir, self.brief, self.gates, line)
                    await self.agent(f"W1:{line}", spec,
                                     lambda line=line: [p for p in V.blocking(V.registry(coll, self.mode())[0]) if p.file.endswith(f"{line}.md")],
                                     kind="fix", resume=sid, max_fix=1)
        n2 = sum(1 for p in probs if p.severity in ("P2", "P3"))
        self.log.add("H1", f"登记块交接校验：阻断 {len(blocking)} 项、提示 {n2} 项" + ("；阻断项交 W2 手工勾稽" if blocking else ""),
                     ".harness/registry-check.txt")

    # ================================================================== W2
    def w2_post(self) -> List[V.Problem]:
        """Deterministic W2 tail: CSV/adjudication schema → checker --financials → market-cap triple →
        reconcile_merge → derive_metrics → ledger §2.x merge. Returns the problems to send back."""
        wd = self.workdir
        missing = [r for r in ("forensic/ledger.md", "forensic/financials.csv", "forensic/adjudications.json", "forensic/derived-inputs.json")
                   if not (wd / r).exists()]
        if missing:
            return [V.Problem("P1", "W2_OUTPUT_MISSING", f"缺 {m}", m) for m in missing]
        probs = V.financials(wd, self.mode()) + V.adjudications(wd)
        if V.blocking(probs):
            return probs
        steps.checker_financials(wd)
        probs += V.market_cap_identity(wd)
        rm = steps.reconcile_merge(wd)
        if rm.code != 0:
            for line in rm.output.splitlines():
                if line.startswith("[P1]") or line.startswith("[P0]"):
                    probs.append(V.Problem("P1", "RECONCILE_MERGE", line[:300], "forensic/adjudications.json"))
        dm = steps.derive_metrics(wd)
        if dm.code != 0:
            probs.append(V.Problem("P1", "DERIVED_ANCHOR_FAIL", dm.output.strip()[-1500:], "forensic/derived-inputs.json"))
        else:
            num = steps.merge_derived_summary(wd)
            self.state.note("ledger_summary_section", num)
        return probs

    async def step_W2(self) -> None:
        wd = self.workdir
        cc = steps.collision_check(wd)
        self.log.add("W2-脚本", f"collision_check.py exit {cc.code}（{'存在待裁决候选' if cc.code else '无候选'}）→ forensic/collision-report.txt",
                     "harness 运行，原始产出不经 LLM 上下文改写")
        spec = roles.reconciler(wd, self.brief, self.gates, read(wd / ".harness" / "registry-check.txt"))
        self.log.add("W2", "派发 equity-data-reconciler ×1（采集四线＋对撞报告＋登记校验已预载）", "脚本链 checker/三元组/reconcile_merge/derive_metrics 由 harness 执行")
        _, probs = await self.agent("W2", spec, self.w2_post)
        await self.w2_finish(probs)

    async def w2_finish(self, probs: List[V.Problem]) -> None:
        wd = self.workdir
        b = V.blocking(probs)
        if any(p.code == "DERIVED_ANCHOR_FAIL" for p in b):
            dm = steps.derive_metrics(wd)
            dropped = steps.drop_derived_inputs(wd, steps.failing_anchor_keys(dm, wd))
            dm = steps.derive_metrics(wd)
            if dm.code == 0:
                steps.merge_derived_summary(wd)
            self.log.add("W2-失败路径", f"派生层锚校验 2 轮未过：删除失败输入 {dropped} 后重跑 derive_metrics exit {dm.code}", "agent body 动作 10③")
        if any(p.code == "RECONCILE_MERGE" for p in b):
            self.log.add("W2-失败路径", "reconcile_merge 锚失败 2 轮未清：相关条目降级 ledger-only（不打戳），不阻塞波次",
                         "；".join(p.message[:60] for p in b if p.code == "RECONCILE_MERGE")[:200])
        if any(p.code.startswith("MARKET_") for p in b):
            self.log.add("W2-升级", "基准三元组自验未过，交 W3 交接验收", "；".join(p.message[:80] for p in b if p.code.startswith("MARKET_")))
        rep = self.report("W2")
        c = rep.get("conflicts", {})
        self.log.add("W2", f"对账完成：CSV {rep.get('csv_rows', '?')} 行 {rep.get('periods', '')}；冲突 裁决{c.get('resolved', '?')}/双值{c.get('dual', '?')}/悬置{c.get('pending', '?')}；"
                           f"reconciled-collection/ 生成，collection/ 已移入 collection-deprecated/={not (wd / 'collection').exists()}；"
                           f"派生层 §{self.state.note('ledger_summary_section') or '?'} 并入",
                     f"最重要裁决：{rep.get('key_adjudication', '')}；升级项：{rep.get('escalations', [])}")

    # ================================================================== W3 / G2
    def w3_handoff_note(self) -> str:
        wd = self.workdir
        fin = V.financials(wd, self.mode())
        cons = steps.ledger_summary_consistent(wd) if (wd / "forensic" / "derived-summary.md").exists() else False
        mc = V.market_cap_identity(wd)
        return "\n".join([
            f"① financials.csv 列齐全/深度：{'通过' if not fin else '未通过：' + '；'.join(p.message for p in fin)}",
            f"③ ledger §{self.state.note('ledger_summary_section') or '2.x'}「派生指标摘要」↔ derived-summary.md：{'逐字一致（harness 脚本并入）' if cons else '失配'}",
            f"（附）基准三元组 市值＝现价×总股本：{'通过' if not mc else '未通过：' + mc[0].message}",
        ])

    async def step_W3(self) -> None:
        wd = self.workdir
        spec = roles.forensic(wd, self.brief, self.gates, self.w3_handoff_note())
        self.log.add("W3", "派发 equity-forensic-accountant ×1（交接验收①③已由代码完成）", "")
        _, probs = await self.agent("W3", spec, lambda: V.grade(wd))
        rep = self.report("W3")
        esc = [e for e in rep.get("escalations", []) if isinstance(e, dict) and e.get("needs_w2") and e.get("severity") in ("高", "中")]
        if (esc or rep.get("acceptance") == "fail") and self.state.rounds("W3->W2") == 0:
            self.state.bump("W3->W2")
            issues = "\n".join(f"- {e.get('id', '')}（{e.get('severity')}）{e.get('issue', '')}" for e in esc) or "- 交接验收未通过（见 W3 回报）"
            self.log.add("W3-疑点重派W2", f"{len(esc)} 项疑点 → 重派 W2 补轮一轮", issues.replace("\n", " ")[:200])
            sid = self.state.session("W2")
            if sid:
                spec2 = roles.Spec("equity-data-reconciler", "", roles.reconciler(wd, self.brief, self.gates, "").addendum, max_turns=50)
                msg = ("（harness）W3 质检提出以下疑点，请在本会话做 W2 补轮：回源核验/补录/裁决，就地更新 ledger.md、financials.csv、"
                       "adjudications.json、derived-inputs.json（Cxx 续编不重排）；完成后照原格式回报。疑点：\n" + issues)
                call_spec = roles.Spec(spec2.agent, msg, spec2.addendum, max_turns=50)
                _, p2 = await self.agent("W2", call_spec, self.w2_post, kind="rerun", resume=sid)
            else:
                spec2 = roles.reconciler(wd, self.brief, self.gates, read(wd / ".harness" / "registry-check.txt"), rerun_issues=issues)
                _, p2 = await self.agent("W2", spec2, self.w2_post, kind="rerun")
            await self.w2_finish(p2)
            w2rep = self.report("W2", "rerun")
            review = ("（harness）W2 补轮已完成，派生层已重建并入 ledger。W2 回报摘要：" + json.dumps(w2rep, ensure_ascii=False)[:1500]
                      + "\n请做轻量复核：重读 forensic/ledger.md、forensic/financials.csv 的变动处（用 Read/Grep 只取相关片段），"
                        "确认或调整等级，必要时更新 quality/earnings-quality.md 与 grade.json；照原格式回报。\n交接验收复核：\n" + self.w3_handoff_note())
            _, probs = await self.agent("W3", roles.Spec(spec.agent, review, spec.addendum), lambda: V.grade(wd),
                                        kind="review", resume=self.state.session("W3"))
        elif esc:
            self.log.add("W3-升级", "W2 已补轮一次，剩余疑点按可得数据评级并在 grade.summary 注明", "失败路径表")
        if V.blocking(probs):
            self.log.add("W3-校验", f"{len(V.blocking(probs))} 项未修复（W8 显式解释）", "；".join(p.code for p in V.blocking(probs)))
        g = read_json(wd / "quality" / "grade.json")
        self.log.add("W3", f"质检返回：grade={g.get('grade')}（veto_action={g.get('veto_action')}）", g.get("summary", "")[:160])

    async def step_G2(self) -> None:
        g = read_json(self.workdir / "quality" / "grade.json")
        letter = str(g.get("grade", "")).upper()
        cap = {"C": "观望", "D": "规避"}.get(letter, "none")
        self.state.set_gate("grade", letter)
        self.state.set_gate("action_cap", cap)
        decision = {"C": "注入后续 PARAMS grade=C, action_cap=观望", "D": "注入 grade=D, action_cap=规避，W5 估值章按否决重构"}.get(
            letter, f"grade={letter}，无动作上限")
        self.log.add("G2", f"门禁裁决：{decision}", f"quality/grade.json {g.get('generated', '')}")

    # ================================================================== W4
    async def step_W4(self) -> None:
        wd, mode = self.workdir, self.mode()
        splits = WRITER_SPLITS[mode]
        self.log.add("W4", f"派发 equity-chapter-writer ×{len(splits)} 并行（{'/'.join(splits)}），PARAMS 注入 grade={self.gates.get('grade')}, action_cap={self.gates.get('action_cap')}",
                     "每写手预载：模板节＋output-format＋行业附录节＋ledger/CSV/derived/quality＋对账副本发现节")

        async def one(ch: str):
            spec = roles.writer(wd, self.brief, self.gates, ch)
            files = [f"chapters/{roles.CHAPTER_FILES[mode][int(n)]}" for n in ch.split("+")]

            def validate():
                out: List[V.Problem] = []
                for f in files:
                    out += V.chapter(wd, f)
                    if f.split("/")[1].startswith("ch05") and self.gates.get("grade"):
                        out += V.grade_letters(wd, f, self.gates["grade"])
                return out
            _, probs = await self.agent(f"W4:{ch}", spec, validate)
            gaps = sum((len(V.data_gaps(wd, f)) for f in files), 0)
            self.log.add(f"W4:{ch}", f"返回：{', '.join(files)}；data-gaps {gaps} 条" + (f"；遗留 {len(V.blocking(probs))} 项阻断" if V.blocking(probs) else ""), "")

        async with anyio.create_task_group() as tg:
            for ch in splits:
                tg.start_soon(one, ch)
        critical = []
        for ch in splits:
            for g in self.report(f"W4:{ch}").get("critical_gaps", []) or []:
                critical.append((ch, g))
        if critical:
            if self.recollect and self.state.rounds("recollect") == 0:
                await self.recollect_round(critical)
            else:
                self.log.add("W4-关键缺口", f"{len(critical)} 条关键缺口记录，不补采（{'fixture 模式' if self.fixture else '已补采过一轮'}）",
                             "；".join(str(g)[:60] for _, g in critical)[:200])
        self.log.add("W4", f"{len(splits)} 写手全部返回", "")

    async def recollect_round(self, critical: List[Tuple[str, object]]) -> None:
        """Failure path: targeted re-collection (one round) → W2 re-reconcile → W3 re-review → affected writers update."""
        self.state.bump("recollect")
        by_line: Dict[str, List[str]] = {}
        for _, g in critical:
            item = g if isinstance(g, str) else g.get("item", "")
            line = (g.get("line") if isinstance(g, dict) else None) or LINES[self.mode()][0]
            by_line.setdefault(line, []).append(item)
        self.log.add("W4-补采", f"关键缺口 → 定向补采一轮：{', '.join(by_line)}", "失败路径表：关键缺口定向补采一轮")
        for line, items in by_line.items():
            spec = roles.collector(self.workdir, self.brief, self.gates, line)
            spec = roles.Spec(spec.agent, spec.prompt + "\n\n补采轮：先读旧文件就地更新，只补以下缺口：\n" + "\n".join(f"- {i}" for i in items),
                              spec.addendum)
            await self.agent(f"W1:{line}", spec, lambda: [], kind="recollect")
        await self.step_H1()
        msg = "（harness）定向补采已落档 collection/ 单线新件，请做 W2 补轮：collection/ 新件优先、collection-deprecated/ 补缺，更新四个产物。"
        sid = self.state.session("W2")
        _, p2 = await self.agent("W2", roles.Spec("equity-data-reconciler", msg, roles.reconciler(self.workdir, self.brief, self.gates, "").addendum),
                                 self.w2_post, kind="recollect", resume=sid)
        await self.w2_finish(p2)
        for ch in {c for c, _ in critical}:
            sid = self.state.session(f"W4:{ch}")
            await self.agent(f"W4:{ch}", roles.Spec("equity-chapter-writer", "（harness）补采与对账已更新 forensic/ 与 reconciled-collection/，请据新数据更新本章缺口处（Read 相关片段），其余不动。", ""),
                             lambda: [], kind="recollect", resume=sid)

    # ================================================================== W5 / assembly D / W6 / G3 / W5R
    def valuation_validate(self, revision: bool) -> Callable[[], List[V.Problem]]:
        wd = self.workdir
        cfg, out = ("valuation/assumptions.v2.json", "valuation/dcf-output.v2.txt") if revision else ("valuation/assumptions.json", "valuation/dcf-output.txt")
        vch = "chapters/ch08-valuation.md" if self.mode() == "earnings" else "chapters/ch06-valuation.md"

        def validate():
            probs = V.dcf_provenance(wd, cfg, out)
            lab = V.dcf_label(read(wd / out)) if (wd / out).exists() else None
            probs += V.chapter(wd, vch)
            probs += V.valuation_notes(wd, lab["label"] if lab else "", revision)
            if revision:
                for rel, h in (self.state.note("v1_hashes") or {}).items():
                    if not (wd / rel).exists() or sha256(wd / rel) != h:
                        probs.append(V.Problem("P1", "V1_MODIFIED", f"{rel} 是审计轨迹，修正轮不得改写", rel))
            return probs
        return validate

    async def step_W5(self) -> None:
        self.log.add("W5", "派发 equity-valuation-analyst ×1（refs＋dcf.py 源码＋ledger/CSV/quality＋ch03/ch04 预载）",
                     f"grade={self.gates.get('grade')}, action_cap={self.gates.get('action_cap')}")
        spec = roles.valuation(self.workdir, self.brief, self.gates)
        _, probs = await self.agent("W5", spec, self.valuation_validate(False))
        out = self.workdir / "valuation" / "dcf-output.txt"
        lab = V.dcf_label(read(out)) if out.exists() else None
        if any(p.code == "DCF_CONFIG_ERROR" for p in V.blocking(probs)):
            self.log.add("W5-失败路径", "dcf.py 配置错误自修后仍败 → 显式降级（「无法给出可靠估值区间」路径）", probs[0].message[:160])
        rep = self.report("W5")
        self.log.add("W5", f"估值完成：标定「{lab['label'] if lab else '?'}」（区间 [{lab['low'] if lab else '?'}, {lab['high'] if lab else '?'}]×现价 {lab['price'] if lab else '?'}）；Gap {rep.get('gap', '?')}；WACC {rep.get('wacc', '?')}/g {rep.get('terminal_g', '?')}",
                     f"dcf 输出经 harness 复跑一致={not any(p.code == 'DCF_OUTPUT_NOT_REPRODUCIBLE' for p in probs)}；升级项：{rep.get('escalations', [])}")

    async def step_ASM_D(self) -> None:
        steps.write_header(self.workdir, self.brief)
        n = steps.assemble(self.workdir, steps.DRAFT_ORDER, "draft/report-draft.md")
        self.log.add("组装D", f"写 _header.md 并脚本拼接 ch02–ch08 → draft/report-draft.md（{n:,} 字符）", "内容不经 LLM")

    async def step_W6(self) -> None:
        self.log.add("W6", "派发 equity-red-team ×1（独立 subagent；草稿＋thesis brief＋dcf 输出＋质量文件预载）", "skill 纪律要求独立派发留痕")
        spec = roles.redteam(self.workdir, self.brief, self.gates)
        _, probs = await self.agent("W6", spec, lambda: V.redteam(self.workdir))
        if V.blocking(probs):
            self.log.add("W6-校验", f"旁车 {len(V.blocking(probs))} 项未修复：G3 按 md 表格回退解析", "；".join(p.code for p in V.blocking(probs)))
        sc = self.sidecar()
        cnt = {s: sum(1 for f in sc["findings"] if f.get("strength") == s) for s in V.STRENGTHS}
        self.log.add("W6", f"红队返回：三问 {sc['three_questions'].get('verdict', '?')}；" + "/".join(f"{k}{v}" for k, v in cnt.items()),
                     "；".join(f"{f['id']}({f['strength']}) {f.get('statement', '')[:40]}" for f in sc["findings"] if f.get("strength") in ("中强", "强"))[:240])

    def sidecar(self) -> Dict:
        path = self.workdir / V.SIDECAR_REL
        try:
            sc = read_json(path)
            if isinstance(sc.get("findings"), list):
                return sc
        except (OSError, ValueError):
            pass
        md = read(self.workdir / "redteam" / "redteam-feedback.md")
        found = V._md_strengths(md)
        return {"three_questions": {"verdict": "通过" if "不通过" not in md else "不通过"},
                "findings": [{"id": k, "strength": v, "targets": ["ch1 风险"]} for k, v in found.items()],
                "consistency": {}}

    async def step_G3(self) -> None:
        sc = self.sidecar()
        strong = [f for f in sc["findings"] if f.get("strength") in ("中强", "强")]
        val, writers, verdict = [], {}, []
        for f in strong:
            kinds = {V.target_kind(t) for t in f.get("targets", [])}
            if "valuation" in kinds:
                val.append(f)
            for k in kinds:
                if k.startswith("writer:"):
                    writers.setdefault(int(k.split(":")[1]), []).append(f)
            verdict.append(f)
        bad_cons = [k for k, v in (sc.get("consistency") or {}).items() if v is False]
        three_q_pass = sc["three_questions"].get("verdict") != "不通过"
        revision = bool(val) or bool(bad_cons)
        fmt = lambda fs: "\n".join(f"- {f['id']}（{f['strength']}）{f.get('statement', '')}｜回写目标：{'、'.join(f.get('targets', []))}" for f in fs)
        self.state.set_gate("g3_revision", revision)
        self.state.set_gate("g3_instructions", fmt(val) + (f"\n- 一致性核对失败项：{bad_cons}（修正轮必开）" if bad_cons else ""))
        self.state.set_gate("g3_verdict", (fmt(verdict) or "无中强/强发现") + ("" if three_q_pass else "\n- 红队三问不通过 → 动作降「观望」"))
        self.state.set_gate("g3_writers", {str(k): [f["id"] for f in v] for k, v in writers.items()})
        self.state.set_gate("g3_strong_ids", [f["id"] for f in strong])
        self.state.set_gate("three_q_pass", three_q_pass)
        decision = (f"派 W5 修正轮 revision=true（{', '.join(f['id'] for f in val) or '一致性核对失败'}）" if revision else "不开修正轮")
        self.log.add("G3", f"仲裁（代码执行）：中强/强 {len(strong)} 条；{decision}；章节回写 {dict(self.gates['g3_writers']) or '无'}；W7 回写 {len(verdict)} 条",
                     f"规则：中强/强且回写目标含 情景概率/标定/估值假设 → 修正轮；consistency 失败项 {bad_cons or '无'}")
        mode = self.mode()
        for n, ids in writers.items():
            split = next((s for s in WRITER_SPLITS[mode] if str(n) in s.split("+")), None)
            sid = self.state.session(f"W4:{split}") if split else None
            rel = f"chapters/{roles.CHAPTER_FILES[mode].get(n, '')}"
            msg = (f"（harness · G3 回写）红队发现需回写到 {rel}：\n{fmt([f for f in strong if f['id'] in ids])}\n"
                   "只做事实性回写（一两句＋来源），不改本章结论框架；其余内容不动。")
            if sid:
                await self.agent(f"W4:{split}", roles.Spec("equity-chapter-writer", msg, ""), lambda rel=rel: V.chapter(self.workdir, rel),
                                 kind=f"writeback-{n}", resume=sid)
                self.log.add("W4-回写", f"ch{n} 写手完成 G3 回写（{', '.join(ids)}）", "同会话续写，不重派")

    async def step_W5R(self) -> None:
        if not self.gates.get("g3_revision"):
            self.log.add("W5-修正轮", "未触发（G3 无估值类中强/强发现）", "")
            return
        wd = self.workdir
        if not self.state.note("v1_hashes"):
            self.state.note("v1_hashes", {r: sha256(wd / r) for r in ("valuation/assumptions.json", "valuation/dcf-output.txt") if (wd / r).exists()})
        self.log.add("W5-修正轮", "派发 equity-valuation-analyst（revision=true；红队旁车＋v1 全套预载）", self.gates.get("g3_instructions", "")[:200])
        spec = roles.valuation(wd, self.brief, self.gates, revision=True)
        _, probs = await self.agent("W5R", spec, self.valuation_validate(True))
        out = wd / "valuation" / "dcf-output.v2.txt"
        lab = V.dcf_label(read(out)) if out.exists() else None
        self.log.add("W5-修正轮", f"完成：v2 标定「{lab['label'] if lab else '?'}」区间 [{lab['low'] if lab else '?'}, {lab['high'] if lab else '?'}]；v1 未改动={not any(p.code == 'V1_MODIFIED' for p in probs)}",
                     "；".join(p.code for p in V.blocking(probs)) or "校验通过")

    # ================================================================== W7 / assembly F
    async def step_W7(self) -> None:
        wd = self.workdir
        dcf_rel = steps.latest_dcf_output(wd)
        lab = V.dcf_label(read(wd / dcf_rel)) or {}
        self.log.add("W7", f"派发 equity-verdict-writer ×1（输入 {dcf_rel}；G3 回写 {len(self.gates.get('g3_strong_ids', []))} 条）", "")
        spec = roles.verdict(wd, self.brief, self.gates, dcf_rel)
        validate = lambda: V.verdict(wd, lab.get("label", ""), self.gates.get("grade", ""), self.gates.get("g3_strong_ids", []),
                                     bool(self.gates.get("three_q_pass", True)))
        res, probs = await self.agent("W7", spec, validate, max_fix=0)
        rep = self.report("W7")
        if rep.get("status") == "contradiction":
            ruling = ("（harness 裁决，按否决链优先级）标签以 dcf.py 标定行为唯一来源（逐字）；动作上限依次服从 grade 否决→红队三问→action_cap；"
                      "矛盾双方须在 ch9 显式披露并说明取舍，不得抹平。请按此写出 ch01/ch09。")
            self.log.add("W7-输入矛盾", f"verdict 上报矛盾 {rep.get('contradictions')}", "编排裁决：脚本标定行＞grade 否决＞红队三问；写 log 后指示重写")
            res, probs = await self.agent("W7", roles.Spec(spec.agent, ruling, spec.addendum), validate, kind="ruling",
                                          resume=self.state.session("W7"))
        elif V.blocking(probs):
            _, probs = await self._fix_only("W7", spec, validate, probs)
        rep = self.report("W7") or rep
        self.log.add("W7", f"结论返回：标定「{rep.get('label', lab.get('label', '?'))}」区间 {rep.get('range', '')}；动作={rep.get('action', '?')}；Gap {rep.get('gap', '?')}",
                     ("遗留：" + "；".join(p.code for p in V.blocking(probs))) if V.blocking(probs) else "校验通过（标签逐字、否决链、回写映射）")

    async def _fix_only(self, label: str, spec: roles.Spec, validate, probs: List[V.Problem]):
        r = 0
        while V.blocking(probs) and r < self.cfg.max_fix_rounds:
            r += 1
            self.log.add(f"{label}-校验", f"{len(V.blocking(probs))} 项阻断 → 同会话修正第 {r} 轮", "；".join(p.code for p in V.blocking(probs)))
            add_path = self.workdir / ".harness" / "addenda" / (re.sub(r"[^\w+.-]", "_", label) + ".md")
            call = AgentCall(label, spec.agent, fix_prompt(V.blocking(probs)), read(add_path) if add_path.exists() else spec.addendum,
                             spec.tools, resume=self.state.session(label), max_turns=spec.max_turns, kind="fix")
            async with self.limiter:
                res = await self.backend.run(call)
            self.state.set_session(label, res.session_id)
            if res.report():
                self.state.note(f"report:{label}:dispatch", res.report())
            probs = validate()
        return None, probs

    async def step_ASM_F(self) -> None:
        steps.write_header(self.workdir, self.brief)
        n = steps.assemble(self.workdir, steps.FINAL_ORDER, "draft/report-final.md")
        self.log.add("组装F", f"脚本拼接 ch01–ch09＋报告头（含行业附录声明）→ draft/report-final.md（{n:,} 字符）", "内容不经 LLM")

    # ================================================================== W8
    REWORK_OWNER = [(re.compile(r"^(DCF_|EPV_|VALUATION_RANGE|SHARES_)"), "W5"), (re.compile(r"^REPORT_VALUATION_LABEL"), "W7")]

    async def step_W8(self) -> None:
        wd, brief = self.workdir, self.brief
        name = self.state.note("final_name") or self.state.note("final_name", steps.unique_final(wd, steps.final_basename(brief)))
        final_md, final_pdf = wd / "final" / f"{name}.md", wd / "final" / f"{name}.pdf"
        explanations: Dict[str, str] = {}
        llm_used = False
        while True:
            _, lint_issues = steps.lint(wd, tee=wd / "checker" / "lint-output.txt")
            chk = steps.checker(wd, "draft/report-final.md", brief, tee=wd / "checker" / "checker-output.txt")
            self.log.add("W8-检查", f"lint {len(lint_issues)} 项；checker " + " ".join(f"{k}={v}" for k, v in chk.counts.items()),
                         "harness 运行（无 LLM）")
            rnd = self.state.rounds("W8")
            if not chk.blocking() or rnd >= 2:
                if chk.blocking():
                    self.log.add("W8-失败路径", f"P0/P1 {len(chk.blocking())} 项 2 轮未清 → 显式解释入附录 C", "不静默")
                break
            self.state.bump("W8")
            shutil.copyfile(wd / "draft" / "report-final.md", final_md)
            llm_used = True
            self.log.add("W8", f"检查器报 P0/P1 {len(chk.blocking())} 项 → 派发 equity-report-deliverer（第 {rnd + 1} 轮）",
                         "；".join(i["code"] for i in chk.blocking())[:200])
            spec = roles.deliverer(wd, brief, self.gates, f"final/{name}.md", rnd + 1)
            await self.agent(f"W8:{rnd + 1}", spec, lambda: [], max_fix=0)
            rep = self.report(f"W8:{rnd + 1}")
            for e in rep.get("explain", []) or []:
                explanations[e.get("code", "")] = "显式解释：" + e.get("explanation", "")
            rework = rep.get("rework", []) or []
            if not rework:
                break  # mechanical fixes were applied to the final copy; continue to appendix from it
            for item in rework:
                await self.rework(item)
            await self.step_ASM_F()
        for code, msg in lint_issues:
            if code not in explanations and code == "GRADE_MISMATCH":
                explanations[code] = f"显式解释：lint 对含「可信度/等级」的行逐字取 A–D 字母，该行另含其他字母；等级以 quality/grade.json（{self.gates.get('grade')}）为准"
        base = read(final_md) if (llm_used and final_md.exists()) else read(wd / "draft" / "report-final.md")
        write(final_md, base)
        chk_final = steps.checker(wd, f"final/{name}.md", brief)
        text = base.rstrip() + "\n\n---\n\n" + steps.appendix(wd, brief, chk_final, lint_issues, explanations)
        write(final_md, text)
        chk_after = steps.checker(wd, f"final/{name}.md", brief, tee=wd / "checker" / "checker-final.txt")
        if chk_after.counts != chk_final.counts:
            write(final_md, base.rstrip() + "\n\n---\n\n" + steps.appendix(wd, brief, chk_after, lint_issues, explanations))
            chk_after = steps.checker(wd, f"final/{name}.md", brief, tee=wd / "checker" / "checker-final.txt")
        tool, note = (None, "format≠pdf") if brief.get("format", "pdf") != "pdf" else convert(
            final_md, final_pdf, wd / "checker" / "report_final.html", read(wd / "draft" / "_header.md").splitlines()[0].lstrip("# ").strip(),
            brief.get("language", "zh"))
        self.state.note("delivery", {"md": final_md.as_posix(), "pdf": final_pdf.as_posix() if tool else None, "pdf_tool": tool,
                                     "pdf_check": note, "checker_final": chk_after.counts, "lint": len(lint_issues),
                                     "deliverer_llm": llm_used})
        self.log.add("W8", f"交付：final/{name}.md" + (f"＋.pdf（{tool}；{note}）" if tool else f"（PDF 降级：{note}）") +
                     f"；终稿 checker " + " ".join(f"{k}={v}" for k, v in chk_after.counts.items()) + f"；lint {len(lint_issues)} 项显式解释",
                     "deliverer LLM " + ("已调用（P0/P1 内容问题）" if llm_used else "未调用（无 P0/P1）"))
        rep7 = self.report("W7")
        self.log.add("收尾", f"报告路径 final/{name}.{'pdf' if tool else 'md'}；结论：{rep7.get('label', '?')}×区间 {rep7.get('range', '')}、动作 {rep7.get('action', '?')}、Gap {rep7.get('gap', '?')}",
                     "流程闭环")

    async def rework(self, item: Dict) -> None:
        owner = str(item.get("owner", ""))
        msg = f"（harness · W8 回炉）检查器 {item.get('code', '')}：{item.get('instruction', '')}（文件 {item.get('file', '')}）。只修此处，其他不动。"
        mode = self.mode()
        if owner.startswith("W4"):
            split = owner.split(":", 1)[1] if ":" in owner else next((s for s in WRITER_SPLITS[mode] if re.search(r"ch0?(\d)", item.get("file", "")) and re.search(r"ch0?(\d)", item.get("file", "")).group(1) in s.split("+")), None)
            label = f"W4:{split}"
            agent = "equity-chapter-writer"
        elif owner == "W5":
            label, agent = ("W5R" if self.state.session("W5R") else "W5"), "equity-valuation-analyst"
        else:
            label, agent = "W7", "equity-verdict-writer"
        sid = self.state.session(label)
        self.log.add("W8-回炉", f"{owner} ← {item.get('code', '')}", item.get("instruction", "")[:160])
        if sid:
            await self.agent(label, roles.Spec(agent, msg, ""), lambda: [], kind=f"rework-{self.state.rounds('W8')}", resume=sid)
