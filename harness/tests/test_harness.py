"""Unit tests for the deterministic layer (no LLM, no network).

    python -m unittest discover -s harness/tests -t .
"""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import anyio

from harness import docs, steps, tokens, validators as V
from harness.backend import AgentCall, AgentFailed, AgentResult, SDKBackend, classify, reset_wait
from harness.config import RuntimeConfig
from harness.runlog import RunLog, read_runs
from harness.util import read, write

FIXTURE = Path(__file__).resolve().parents[2] / "research" / "安莉芳_1388HK_20260923"


class DocsTest(unittest.TestCase):
    def test_section_ids_and_fences(self):
        text = "# T\n## 7. A\nx\n### 7.1 B\ny\n```yaml\n# not a heading\n```\n## 8. C\nz\n## 二、D\nw\n"
        self.assertEqual(docs.extract(text, ["7"]).splitlines()[0], "## 7. A")
        self.assertIn("# not a heading", docs.extract(text, ["7"]))
        self.assertEqual(docs.extract(text, ["二"]).strip(), "## 二、D\nw")
        self.assertEqual(docs.extract(text, ["7.1"]).splitlines()[0], "### 7.1 B")

    def test_keep_and_drop_level2(self):
        text = "# H\npre\n## 发现\na\n## 指标登记\nb\n## 原文附录\nc\n"
        kept = docs.keep_level2(text, ["发现"])
        self.assertIn("pre", kept)
        self.assertIn("a", kept)
        self.assertNotIn("原文附录", kept)
        self.assertNotIn("指标登记", docs.drop_level2(text, ["指标登记"]))


@unittest.skipUnless(FIXTURE.exists(), "1388.HK fixture not present")
class FixtureValidatorsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(FIXTURE / "collection-deprecated", self.tmp / "collection")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_registry_flow_style_detected_then_normalized(self):
        probs, _ = V.registry(self.tmp / "collection", "full")
        self.assertIn("REGISTRY_FORMAT_UNPARSEABLE", {p.code for p in probs})
        before = read(self.tmp / "collection" / "01-disclosure.md")
        probs, actions = V.registry(self.tmp / "collection", "full", normalize=True)
        self.assertEqual(len(actions), 1)
        self.assertFalse(V.blocking(probs))
        after = read(self.tmp / "collection" / "01-disclosure.md")
        # body outside the registry block is byte-identical
        self.assertEqual(before.split("## 指标登记")[0], after.split("## 指标登记")[0])
        self.assertEqual(before.split("## 冲突")[1], after.split("## 冲突")[1])

    def test_original_outputs(self):
        self.assertEqual(V.financials(FIXTURE, "full"), [])
        self.assertEqual(V.adjudications(FIXTURE), [])
        self.assertEqual(V.market_cap_identity(FIXTURE), [])
        self.assertEqual(V.dcf_provenance(FIXTURE, "valuation/assumptions.v2.json", "valuation/dcf-output.v2.txt"), [])
        codes = {p.code for p in V.grade(FIXTURE)}
        self.assertEqual(codes, {"GRADE_MISMATCH"})  # the false-positive lint hit the original run explained at W8
        self.assertEqual(V.verdict(FIXTURE, "合理", "C", ["R1", "R2"], True), [])
        self.assertEqual(V._md_strengths(read(FIXTURE / "redteam" / "redteam-feedback.md"))["R1"], "中强")

    def test_dcf_label(self):
        lab = V.dcf_label(read(FIXTURE / "valuation" / "dcf-output.v2.txt"))
        self.assertEqual((lab["low"], lab["high"], lab["price"], lab["label"]), (0.15, 0.55, 0.243, "合理"))


class SidecarTest(unittest.TestCase):
    def test_redteam_sidecar_cross_check(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            write(tmp / "redteam" / "redteam-feedback.md", "| 编号 | 陈述 | 强度 | 证据 | 回写目标 |\n|---|---|---|---|---|\n| R1 | x | 中强 | y | 情景概率 |\n")
            sc = {"three_questions": {"verdict": "通过"},
                  "findings": [{"id": "R1", "strength": "中", "targets": ["情景概率"]}],
                  "consistency": {"label_matches_dcf": True, "gap_consistent": True, "veto_chain_ok": True,
                                  "probabilities_match_evidence": True}}
            write(tmp / V.SIDECAR_REL, json.dumps(sc, ensure_ascii=False))
            self.assertIn("REDTEAM_SIDECAR_MD_MISMATCH", {p.code for p in V.redteam(tmp)})
            sc["findings"][0]["strength"] = "中强"
            write(tmp / V.SIDECAR_REL, json.dumps(sc, ensure_ascii=False))
            self.assertEqual(V.redteam(tmp), [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_target_kind(self):
        self.assertEqual(V.target_kind("情景概率→触发修正轮"), "valuation")
        self.assertEqual(V.target_kind("ch3 事实补充"), "writer:3")
        self.assertEqual(V.target_kind("ch9 动作节奏"), "verdict")
        self.assertEqual(V.target_kind("ch1 风险"), "verdict")


class StepsTest(unittest.TestCase):
    def test_merge_derived_summary_idempotent(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            write(tmp / "forensic" / "ledger.md", "# L\n## §1 基准\nx\n## §2 台账\n### 2.1 a\n### 2.2 b\n## §3 冲突\nc\n")
            write(tmp / "forensic" / "derived-summary.md", "# 派生指标摘要（ledger §2 底稿）\n| m | v |\n")
            self.assertEqual(steps.merge_derived_summary(tmp), "2.3")
            once = read(tmp / "forensic" / "ledger.md")
            self.assertEqual(steps.merge_derived_summary(tmp), "2.3")
            self.assertEqual(once, read(tmp / "forensic" / "ledger.md"))
            self.assertLess(once.index("2.3 派生指标摘要"), once.index("## §3"))
            self.assertTrue(steps.ledger_summary_consistent(tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_assemble_strips_data_gaps(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            write(tmp / "draft" / "_header.md", "# H\n")
            write(tmp / "chapters" / "ch02-business.md", "## 二\n本章要点：x\n<!-- data-gaps: a; b -->\n")
            steps.assemble(tmp, ["02"], "draft/out.md")
            self.assertNotIn("data-gaps", read(tmp / "draft" / "out.md"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_explain_eps_units(self):
        msg = steps.explain_issue({"code": "EPS_RECONCILIATION_MISMATCH",
                                   "detail": "expected=-0.0005993561266874152, provided=-0.5994, net_income=-253178.0"}, {"industry": "consumer"})
        self.assertIn("1,000", msg)


class BackendTest(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify(429, "rate limit"), "rate_limit")
        self.assertEqual(classify(400, "API Error 400 {\"code\":\"1301\"}"), "content_filter")
        self.assertEqual(classify(None, "Not logged in · Please run /login"), "auth")
        self.assertEqual(classify(529, "overloaded"), "server")

    def test_reset_wait(self):
        w = reset_wait("5-hour limit reached ∙ resets 5am", 6 * 3600)
        self.assertTrue(w is not None and 0 < w <= 6 * 3600)
        self.assertIsNone(reset_wait("no reset info", 100))

    def test_report_trailer(self):
        r = AgentResult("W3", "x", "s", "小结\n```json\n{\"grade\": \"C\"}\n```")
        self.assertEqual(r.report(), {"grade": "C"})


def _result(**over):
    """A `_once` return value: the untyped dict the SDK backend builds per attempt."""
    out = {"session_id": "sid", "result": "done", "is_error": False, "status": None, "text": "done",
           "usage": {"input_tokens": 100, "output_tokens": 20}, "num_turns": 3, "duration_ms": 1500,
           "tool_calls": 2, "exc": None}
    out.update(over)
    return out


class _FakeBackend(SDKBackend):
    """SDKBackend with the SDK call replaced: everything else (retry loop, accounting) is the real code."""

    def __init__(self, workdir, attempts, **cfg):
        self.rows = []
        super().__init__(RuntimeConfig(backoff_base=0.0, rate_limit_cap=0.0, **cfg), Path(workdir),
                         on_session=lambda *a: None, on_run_log=self.rows.append, on_retry=lambda *a: None)
        self._attempts = list(attempts)

    async def _once(self, call, prompt, resume, system_prompt, tools):
        return self._attempts.pop(0)


class BackendAccountingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _call(self):
        return AgentCall("W2", "__inline__", "p", max_turns=1)

    def test_retry_then_success_is_logged_per_attempt(self):
        b = _FakeBackend(self.tmp, [_result(is_error=True, status=429, result="rate limit · resets 5am"),
                                    _result(result="", text="", tool_calls=0),   # empty reply
                                    _result()])
        res = anyio.run(b.run, self._call())
        self.assertEqual((res.label, res.session_id, res.text), ("W2", "sid", "done"))
        self.assertEqual([r["kind"] for r in b.rows], ["rate_limit", "empty", "ok"])
        self.assertEqual([r["call_kind"] for r in b.rows], ["dispatch", "retry", "retry"])
        self.assertEqual([r["attempt"] for r in b.rows], [1, 2, 3])
        self.assertIn("rate limit", b.rows[0]["msg"])
        self.assertNotIn("msg", b.rows[2])                      # nothing to report on success
        self.assertEqual(b.rows[2]["usage"], {"input_tokens": 100, "output_tokens": 20})

    def test_wall_clock_fallback_when_sdk_reports_no_duration(self):
        b = _FakeBackend(self.tmp, [_result(duration_ms=0)])
        anyio.run(b.run, self._call())
        self.assertGreaterEqual(b.rows[0]["duration_ms"], 0)
        self.assertIsInstance(b.rows[0]["duration_ms"], int)

    def test_failure_message_keeps_last_kind_and_text(self):
        b = _FakeBackend(self.tmp, [_result(is_error=True, status=503, result="overloaded")] * 2, max_attempts=2)
        with self.assertRaises(AgentFailed) as ctx:
            anyio.run(b.run, self._call())
        self.assertIn("server: overloaded", str(ctx.exception))
        self.assertEqual(len(b.rows), 2)


class RunLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_open_ended_fields_and_defaults(self):
        log = RunLog(self.tmp)
        log.log(label="W2", foo="bar", obj=Path("x"))          # unknown keys and a non-JSON value
        log.log({"label": "W2", "ts": "fixed", "run_id": "mine"})  # caller wins over the defaults
        rows = read_runs(self.tmp)
        self.assertEqual(rows[0]["foo"], "bar")
        self.assertEqual(rows[0]["run_id"], log.run_id)
        self.assertTrue(rows[0]["ts"])
        self.assertEqual(rows[0]["obj"], str(Path("x")))        # default=str, not an exception
        self.assertEqual((rows[1]["ts"], rows[1]["run_id"]), ("fixed", "mine"))

    def test_write_failure_is_swallowed(self):
        log = RunLog(self.tmp, path=self.tmp / "nodir")
        log.path = self.tmp                                      # a directory: open() for append fails
        log.log(label="W2")                                      # must not raise

    def test_summary_sums_across_runs_and_latest_only(self):
        for rid, dur in (("r1", 1000), ("r2", 3000)):
            log = RunLog(self.tmp, run_id=rid)
            log.log(event="pipeline_start")                      # no label: not an agent row
            log.log(label="W2", agent="equity-data-reconciler", kind="server", attempt=1,
                    usage={"input_tokens": 10, "output_tokens": 5}, duration_ms=dur)
            log.log(label="W2", agent="equity-data-reconciler", kind="ok", attempt=2,
                    usage={"input_tokens": 10, "output_tokens": 5}, duration_ms=dur)
        # an old row, written before run_id / kind / msg existed
        with io.open(self.tmp / ".harness" / "runs.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"label": "W3", "agent": "a", "usage": {"input_tokens": 7}}) + "\n")
        total = {r["label"]: r for r in tokens.run_rows(self.tmp)}
        self.assertEqual(total["W2"]["attempts"], 4)
        self.assertEqual(total["W2"]["tokens"], 60)
        self.assertEqual(total["W2"]["retries"], 2)
        self.assertEqual(total["W2"]["duration_ms"], 8000)
        self.assertEqual(total["W2"]["kinds"], ["server", "ok"])
        self.assertEqual(total["W3"]["attempts"], 1)             # missing keys tolerated
        self.assertEqual(total["W3"]["retries"], 0)
        latest = {r["label"]: r for r in tokens.run_rows(self.tmp, latest_only=True)}
        self.assertEqual(latest["W3"]["attempts"], 1)            # the old row has no run_id of its own
        self.assertNotIn("W2", latest)                           # the last run_id is the old row's (None)
        self.assertIn("合计", tokens.run_summary(self.tmp))


if __name__ == "__main__":
    unittest.main()
