import copy
import importlib.util
import json
import os
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
SCRIPT = os.path.join(ROOT, "scripts", "check_research_output.py")
SPEC = importlib.util.spec_from_file_location("check_research_output", SCRIPT)
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class IndustryRulesTests(unittest.TestCase):
    def test_registry_has_valid_appendices_and_kpi_groups(self):
        rules = CHECKER.load_industry_rules()
        self.assertEqual(20, len(rules))
        for slug, rule in rules.items():
            self.assertTrue(os.path.isfile(os.path.join(ROOT, rule["appendix"])), slug)
            self.assertGreaterEqual(len(rule["required_groups"]), 2, slug)
            for group in rule["required_groups"]:
                self.assertTrue(group["terms"], f"{slug}: {group['label']}")

    def test_auto_detects_primary_and_secondary_appendices(self):
        rules = CHECKER.load_industry_rules()
        text = "Industry appendix: Internet/platforms (primary) + SaaS (secondary)"
        self.assertEqual(["saas", "internet-platform"], CHECKER.detect_declared_industries(text, rules))

    def test_platform_equivalent_kpis_pass(self):
        issues = []
        text = "行业附录: internet-platform\n| 广告变现 | 分部经营利润率 |\n|---:|---:|\n| +10% | 20% |"
        CHECKER.check_industry_requirements(text, ["auto"], "report.md", issues)
        self.assertEqual([], issues)

    def test_missing_industry_kpi_is_p1(self):
        issues = []
        CHECKER.check_industry_requirements("行业附录: banks\n| NIM |\n|---:|\n| 3% |", ["auto"], "report.md", issues)
        self.assertTrue(any(issue.code == "REPORT_INDUSTRY_KPI_MISSING" and issue.severity == "P1" for issue in issues))


class LanguageTests(unittest.TestCase):
    def test_english_report_rejects_chinese_template_marker(self):
        issues = []
        CHECKER.check_language_consistency("# Acme (ACME) Equity Research Report\n本章要点：增长。", "auto", "report.md", issues)
        self.assertEqual("REPORT_LANGUAGE_MIXED", issues[0].code)

    def test_chinese_report_accepts_chinese_template_markers(self):
        issues = []
        CHECKER.check_language_consistency("# 示例（DEMO）个股投资研究报告\n本章要点：增长。", "auto", "report.md", issues)
        self.assertEqual([], issues)


class IntegratedCheckerTests(unittest.TestCase):
    def test_demo_report_passes_report_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, _, _ = CHECKER.write_demo_files(tmp)
            issues = []
            CHECKER.check_report(report, None, issues, ["saas"], "zh")
            self.assertEqual([], issues)


def load_dcf():
    spec = importlib.util.spec_from_file_location("dcf", os.path.join(ROOT, "scripts", "dcf.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Schema3CheckerTests(unittest.TestCase):
    """schema 3：checker 读同目录 inputs.json、import dcf 重算标签；规则违规分级。"""

    def setUp(self):
        self.dcf = load_dcf()
        self.tmp = tempfile.TemporaryDirectory()
        self.vdir = os.path.join(self.tmp.name, "valuation")
        os.makedirs(self.vdir)
        self.write("inputs.json", self.dcf.DEMO3_INPUTS)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, obj):
        path = os.path.join(self.vdir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        return path

    def report(self, text):
        path = os.path.join(self.tmp.name, "r.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def run_checks(self, cfg, report_text):
        issues = []
        a = CHECKER.check_assumptions(self.write("assumptions.json", cfg), issues)
        CHECKER.check_report(self.report(report_text), a, issues, ["saas"], "zh")
        return {i.code: i.severity for i in issues}

    def test_recomputed_label_matches(self):
        codes = self.run_checks(copy.deepcopy(self.dcf.DEMO3), "结论：合理")
        self.assertNotIn("REPORT_VALUATION_LABEL_MISMATCH", codes)
        self.assertNotIn("SCHEMA3_EVALUATION_FAILED", codes)

    def test_tampered_label_detected(self):
        codes = self.run_checks(copy.deepcopy(self.dcf.DEMO3), "结论：低估")
        self.assertEqual(codes.get("REPORT_VALUATION_LABEL_MISMATCH"), "P1")

    def test_unreliable_line_required(self):
        cfg = copy.deepcopy(self.dcf.DEMO3)
        for s in cfg["scenarios"]:
            s["margin_target"] = -0.05
        cfg["drivers"]["m1"] = -0.05
        cfg["methods"] = {"epv": False}
        self.assertEqual(self.run_checks(cfg, "结论：合理").get("REPORT_VALUATION_LABEL_MISMATCH"), "P1")
        self.assertNotIn("REPORT_VALUATION_LABEL_MISMATCH", self.run_checks(cfg, "结论：无法给出可靠估值区间"))

    def test_rule_violations_graded(self):
        cfg = copy.deepcopy(self.dcf.DEMO3)
        cfg["weights"] = {"adjust": {"epv": 0.2}, "reasons": {"epv": "x"}}
        cfg["terminal"]["g"] = 0.05
        cfg["scenarios"][0]["prob"] = 0.10
        cfg["scenarios"][1]["prob"] = 0.65
        cfg["scenarios"][1]["revenue"] = [1, 2]
        with open(os.path.join(self.vdir, "verify_calc.py"), "w") as f:
            f.write("print(1)\n")
        codes = self.run_checks(cfg, "结论：合理")
        self.assertEqual(codes.get("WEIGHT_ADJUST_OVER_LIMIT"), "P0")
        self.assertEqual(codes.get("TERMINAL_G_ABOVE_RF"), "P0")
        self.assertEqual(codes.get("DCF_PROB_BELOW_FLOOR"), "P1")
        self.assertEqual(codes.get("DCF_LEGACY_HANDFILLED_PATH"), "P2")
        self.assertEqual(codes.get("CALC_OUTSIDE_CALC_DIR"), "P2")
        self.assertEqual(codes.get("SCHEMA3_EVALUATION_FAILED"), "P0")

    def test_basis_flag_unhandled(self):
        cfg = copy.deepcopy(self.dcf.DEMO3)
        del cfg["basis_confirmed"]
        self.assertEqual(self.run_checks(cfg, "结论：合理").get("BASIS_FLAG_UNHANDLED"), "P1")

    def test_financials_hygiene(self):
        path = os.path.join(self.tmp.name, "f.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("period,revenue,total_assets,total_liabilities,cash\nFY2024,10,100,50,20,99\nFY2025,10,100,50,200\n")
        issues = []
        CHECKER.check_financials(path, issues)
        codes = {i.code for i in issues}
        self.assertIn("CSV_ROW_LENGTH", codes)
        self.assertIn("CSV_CASH_GT_ASSETS", codes)


if __name__ == "__main__":
    unittest.main()
