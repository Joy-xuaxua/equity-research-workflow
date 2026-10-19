import glob
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "lint_contract.py")
SPEC = importlib.util.spec_from_file_location("lint_contract", SCRIPT)
LINT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LINT)

REPO = os.path.abspath(os.path.join(ROOT, "..", "..", ".."))
# 两份真实运行：旧版 GRADE_MISMATCH 在二者上都把否定句/编号误报为等级不一致
REAL_WORKDIRS = [
    os.path.join(REPO, "research", "安莉芳_1388HK_20260923"),
    os.path.join(REPO, "research", "Zhipu_02513HK_20260901"),
]


def codes(issues):
    return [c for c, _ in issues]


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


class GradeStatementTests(unittest.TestCase):
    def letters(self, line):
        hits = LINT.grade_statement_hits(line)
        return set().union(*(ls for _, ls in hits)) if hits else set()

    def test_explicit_statements_are_read(self):
        self.assertEqual({"C"}, self.letters("### 最终等级：**C**（veto_action＝观望）"))
        self.assertEqual({"C"}, self.letters("- **结论：财报可信度等级 C（veto_action＝观望）**"))
        self.assertEqual({"C"}, self.letters("| **财报可信度等级** | **C（veto_action＝观望）** | — |"))
        self.assertEqual({"B"}, self.letters("| **Earnings credibility grade** | **B** | |"))
        self.assertEqual({"A"}, self.letters("Earnings credibility grade: A-"))

    def test_negations_ids_and_placeholders_are_ignored(self):
        # 等级陈述后的否定句：只取紧跟关键词的字母
        self.assertEqual({"C"}, self.letters("**结论：财报可信度等级 C（veto_action＝观望）**——不构成 D。"))
        # 含「等级」但无显式陈述：编号/波次/否定句均不计
        self.assertEqual(set(), self.letters("**补轮影响说明**：E1 定性反转（C19–C21）后对治理评价小幅正面；等级不构成 D"))
        self.assertEqual(set(), self.letters("W4 第一章须载明等级 C 与警示；W5 不得以低倍数论证"))
        # 模板占位与区间
        self.assertEqual(set(), self.letters("| **可信度等级** | A/B/C/D | | 接入第九章否决项 |"))
        self.assertEqual(set(), self.letters("产出财报可信度等级 A–D：C 级动作最高观望"))
        self.assertEqual(set(), self.letters("## 4. 可信度等级（预注册表裁定，补轮复核后维持）"))


class RealWorkdirGradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def copy_grade_inputs(self, workdir):
        """只复制等级一致性核对所需的三件（grade.json / earnings-quality.md / ch05），不动 research/ 原件。"""
        dst = os.path.join(self.tmp.name, os.path.basename(workdir))
        for rel in ["quality/grade.json", "quality/earnings-quality.md"] + [
                os.path.relpath(p, workdir) for p in glob.glob(os.path.join(workdir, "chapters", "ch05-*.md"))]:
            os.makedirs(os.path.dirname(os.path.join(dst, rel)), exist_ok=True)
            shutil.copy(os.path.join(workdir, rel), os.path.join(dst, rel))
        return dst

    def grade_issues(self, workdir):
        issues = []
        grade = LINT.check_grade(workdir, issues, new_pipeline=True)
        LINT.check_grade_consistency(workdir, grade, issues, new_pipeline=True, stage="final")
        return grade, issues

    def test_no_false_positive_on_real_runs(self):
        for wd in REAL_WORKDIRS:
            if not os.path.isdir(wd):
                self.skipTest(f"workdir 不存在：{wd}")
            with self.subTest(workdir=os.path.basename(wd)):
                grade, issues = self.grade_issues(wd)
                self.assertIsNotNone(grade)
                self.assertNotIn("GRADE_MISMATCH", codes(issues))
                self.assertNotIn("GRADE_NOT_EMBEDDED", codes(issues))
                result = LINT.lint(wd, "final")
                self.assertNotIn("GRADE_MISMATCH", codes(result["issues"]))

    def test_wrong_grade_line_still_fires(self):
        for wd in REAL_WORKDIRS:
            if not os.path.isdir(wd):
                self.skipTest(f"workdir 不存在：{wd}")
            with self.subTest(workdir=os.path.basename(wd)):
                dst = self.copy_grade_inputs(wd)
                grade = json.loads(LINT.read_text(os.path.join(dst, "quality", "grade.json")))["grade"]
                wrong = "D" if grade != "D" else "A"
                ch05 = glob.glob(os.path.join(dst, "chapters", "ch05-*.md"))[0]
                with io.open(ch05, "a", encoding="utf-8") as f:
                    f.write(f"\n\n### 最终等级：**{wrong}**（故意写错）\n")
                _, issues = self.grade_issues(dst)
                mismatches = [m for c, m in issues if c == "GRADE_MISMATCH"]
                self.assertEqual(1, len(mismatches), mismatches)
                self.assertIn(os.path.basename(ch05), mismatches[0])

    def test_negation_line_does_not_fire(self):
        for wd in REAL_WORKDIRS:
            if not os.path.isdir(wd):
                self.skipTest(f"workdir 不存在：{wd}")
            with self.subTest(workdir=os.path.basename(wd)):
                dst = self.copy_grade_inputs(wd)
                eq = os.path.join(dst, "quality", "earnings-quality.md")
                with io.open(eq, "a", encoding="utf-8") as f:
                    f.write("\n\n可信度方面无审计非标与造假证据，等级不构成 D；C19–C21 已撤销。\n")
                _, issues = self.grade_issues(dst)
                self.assertNotIn("GRADE_MISMATCH", codes(issues))


class StageTests(unittest.TestCase):
    def test_every_stage_runs_on_real_runs(self):
        for wd in REAL_WORKDIRS:
            if not os.path.isdir(wd):
                self.skipTest(f"workdir 不存在：{wd}")
            for stage in LINT.STAGES:
                with self.subTest(workdir=os.path.basename(wd), stage=stage):
                    result = LINT.lint(wd, stage)
                    self.assertEqual(stage, result["stage"])

    def test_early_stage_skips_later_artifacts(self):
        with tempfile.TemporaryDirectory() as wd:
            write(os.path.join(wd, "brief.json"), json.dumps({"mode": "full"}))
            os.makedirs(os.path.join(wd, "quality"))
            os.makedirs(os.path.join(wd, "collection"))
            result = LINT.lint(wd, "w1")
            later = {"FINANCIALS_MISSING", "GRADE_JSON_MISSING", "CHAPTERS_DIR_MISSING",
                     "INDUSTRY_CLASSIFICATION_MISSING", "RECONCILED_MISSING"}
            self.assertFalse(later & set(codes(result["issues"])), result["issues"])
            self.assertFalse(any("report-final" in m or "ledger" in m for _, m in result["issues"]))
            final = LINT.lint(wd, "final")
            self.assertTrue(later <= set(codes(final["issues"])), final["issues"])


REGISTRY_HEAD = "# 采集文件：02-market（full 模式）\n\n## 发现\n\n| 最新收盘价 | 0.243 港元 | 2026-09-23 收盘 |\n\n## 指标登记\n\n```yaml\n"
REGISTRY_TAIL = "```\n\n## 冲突\n\n未发现冲突\n\n## 未获取到\n\n无\n"
LINE_STYLE = ("- key: price_close\n  value: 0.243\n  unit: 港元/股\n  period: 最新\n  source: HKEX\n"
              "  tier: 1\n  ts: 2026-09-23\n  anchor: \"| 最新收盘价 | 0.243 港元 | 2026-09-23 收盘 |\"\n")
FLOW_STYLE = ("metrics:\n  - {key: price_close, value: 0.243, unit: 港元/股, period: 最新, source: HKEX, tier: 1, "
              "ts: 2026-09-23, anchor: \"| 最新收盘价 | 0.243 港元 | 2026-09-23 收盘 |\"}\n")


class RegistryTests(unittest.TestCase):
    def run_w1(self, block):
        with tempfile.TemporaryDirectory() as wd:
            write(os.path.join(wd, "brief.json"), json.dumps({"mode": "full"}))
            write(os.path.join(wd, "collection", "02-market.md"), REGISTRY_HEAD + block + REGISTRY_TAIL)
            return LINT.lint(wd, "w1")

    def test_line_style_block_parses_and_reports_count(self):
        result = self.run_w1(LINE_STYLE)
        self.assertNotIn("REGISTRY_ENTRY_INVALID", codes(result["issues"]))
        self.assertTrue(any("解析 1 条，W2 可用 1 条" in ln for ln in result["info"]), result["info"])

    def test_flow_style_block_fails_with_hint(self):
        result = self.run_w1(FLOW_STYLE)
        msgs = [m for c, m in result["issues"] if c == "REGISTRY_ENTRY_INVALID"]
        self.assertEqual(1, len(msgs), result["issues"])
        self.assertIn("flow 风格", msgs[0])

    def test_registry_check_only_at_w1(self):
        with tempfile.TemporaryDirectory() as wd:
            write(os.path.join(wd, "brief.json"), json.dumps({"mode": "full"}))
            write(os.path.join(wd, "collection", "02-market.md"), REGISTRY_HEAD + FLOW_STYLE + REGISTRY_TAIL)
            self.assertNotIn("REGISTRY_ENTRY_INVALID", codes(LINT.lint(wd, "final")["issues"]))


if __name__ == "__main__":
    unittest.main()
