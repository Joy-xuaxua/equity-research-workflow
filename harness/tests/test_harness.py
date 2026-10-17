"""Unit tests for the deterministic layer (no LLM, no network).

    python -m unittest discover -s harness/tests -t .
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from harness import docs, steps, validators as V
from harness.backend import AgentResult, classify, reset_wait
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
        r = AgentResult("W3", "x", "s", "小结\n```json\n{\"grade\": \"C\"}\n```", True)
        self.assertEqual(r.report(), {"grade": "C"})


if __name__ == "__main__":
    unittest.main()
