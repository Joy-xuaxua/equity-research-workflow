import contextlib
import csv
import importlib.util
import io
import json
import os
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
SCRIPT = os.path.join(ROOT, "scripts", "derive_metrics.py")
CATALOG = os.path.join(ROOT, "references", "derived-metrics.json")
SPEC = importlib.util.spec_from_file_location("derive_metrics", SCRIPT)
DM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DM)

# 夹具=归档 run（Zhipu 02513.HK）的 financials.csv 数值与 ledger 锚原文（回归断言与外层 T6 同源）。
CSV_TEXT = (
    "period,revenue,gross_profit,operating_income,net_income,cfo,capex,fcf,shares,eps,total_assets,"
    "receivables,ppe,current_assets,depreciation,sga,total_liabilities,deferred_revenue\n"
    "FY2022,57409,31360,,-143650,,,,,,361976,,,,,,542164,\n"
    "FY2023,124538,80482,,-787957,,,,,,2860153,,,,,,3842746,\n"
    "FY2024,312414,175889,,-2958007,-2244919,132760,-2377679,,,4375769,91135,,,,,8330914,75059\n"
    "FY2025,724334,296656,-3786750,-4718167,-2246123,23088,-2269211,159522220,-12.03,4853861,303208,,,,896226,12964843,148644\n"
)

LEDGER_TEXT = (
    "# W2 对账台账（测试夹具）\n\n"
    "## §1 行情与股本基准\n"
    "- 现价（收盘）1,007.00 港元\n"
    "- 币种与汇率：港元；HKD/CNY＝0.8585\n"
    "- 总股本 465,623,090 股\n\n"
    "## §2 关键数字台账\n"
    "- 经调整净亏损附注：股份支付 558,265、上市开支 40,568\n"
    "- FY2025 损益表结构：毛利 296,656−研发 3,180,443−销售及营销 390,869\n"
    "- FY2025 期末正式雇员 1,094 人\n"
    "- ARR 里程碑：2026-01 约 0.4 亿美元 → 2026-07 破 10 亿美元\n"
)

INPUTS_DOC = {
    "industry": "saas",
    "inputs": [
        {"key": "sbc", "value": 558265, "unit": "千元", "period": "FY2025",
         "anchor": "股份支付 558,265", "ts": "2026-04-19"},
        {"key": "rd_expense", "value": 3180443, "unit": "千元", "period": "FY2025",
         "anchor": "研发 3,180,443", "ts": "2026-04-19"},
        {"key": "employees", "value": 1094, "unit": "人", "period": "FY2025",
         "anchor": "FY2025 期末正式雇员 1,094 人", "ts": "2026-04-19"},
        {"key": "price_close", "value": 1007.00, "unit": "港元", "period": "最新",
         "anchor": "1,007.00 港元", "ts": "2026-08-24"},
        {"key": "fx_hkd_cny", "value": 0.8585, "unit": "CNY/HKD", "period": "最新",
         "anchor": "HKD/CNY＝0.8585", "ts": "2026-08-23"},
        {"key": "shares_outstanding", "value": 465623090, "unit": "股", "period": "最新",
         "anchor": "465,623,090 股", "ts": "2026-08-24"},
    ],
}


def make_workdir(csv_text=CSV_TEXT, ledger_text=LEDGER_TEXT, inputs_doc=INPUTS_DOC):
    tmp = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmp, "forensic"))
    with open(os.path.join(tmp, "forensic", "financials.csv"), "w", encoding="utf-8", newline="") as f:
        f.write(csv_text)
    if ledger_text is not None:
        with open(os.path.join(tmp, "forensic", "ledger.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(ledger_text)
    if inputs_doc is not None:
        with open(os.path.join(tmp, "forensic", "derived-inputs.json"), "w", encoding="utf-8") as f:
            json.dump(inputs_doc, f, ensure_ascii=False, indent=2)
    return tmp


def read_derived(workdir):
    with open(os.path.join(workdir, "forensic", "derived.csv"), "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows, {(r["metric"], r["period"]): r["value"] for r in rows}


class CatalogTests(unittest.TestCase):
    def test_catalog_loads_and_consistent(self):
        metrics = DM.load_catalog(CATALOG)
        keys = [m["key"] for m in metrics]
        self.assertEqual(len(keys), len(set(keys)))
        for m in metrics:
            self.assertIn(m["periodicity"], ("per_fy", "point", "window"), m["key"])
            self.assertTrue(m.get("label") and m.get("unit"), m["key"])
            if m.get("type") == "external":
                self.assertIsNone(m["_formula_ast"], m["key"])
            else:
                self.assertIsNotNone(m["_formula_ast"], m["key"])
        # 顺序敏感依赖：rule_of_40 必须定义在 yoy_revenue / fcf_margin 之后
        self.assertLess(keys.index("yoy_revenue"), keys.index("rule_of_40"))
        self.assertLess(keys.index("fcf_margin"), keys.index("rule_of_40"))

    def test_version_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "bad.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"version": 2, "metrics": []}, f)
            with self.assertRaises(ValueError):
                DM.load_catalog(p)

    def test_point_formula_referencing_shares_rejected(self):
        bad = {"version": 1, "metrics": [
            {"key": "yoy_revenue", "label": "营收同比", "unit": "%", "periodicity": "per_fy",
             "industry": "any", "formula": "yoy(revenue)", "inputs": ["revenue"], "note": ""},
            {"key": "ps_bad", "label": "坏P/S", "unit": "倍", "periodicity": "point",
             "industry": "any", "formula": "price_close*shares/last(revenue)", "inputs": [], "note": ""},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "bad.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(bad, f, ensure_ascii=False)
            with self.assertRaises(ValueError) as cm:
                DM.load_catalog(p)
            self.assertIn("shares_outstanding", str(cm.exception))

    def test_forward_reference_rejected(self):
        bad = {"version": 1, "metrics": [
            {"key": "rule_of_40", "label": "Rule of 40", "unit": "%", "periodicity": "per_fy",
             "industry": "any", "formula": "yoy_revenue+fcf_margin", "inputs": [], "note": ""},
            {"key": "yoy_revenue", "label": "营收同比", "unit": "%", "periodicity": "per_fy",
             "industry": "any", "formula": "yoy(revenue)", "inputs": ["revenue"], "note": ""},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "bad.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(bad, f, ensure_ascii=False)
            with self.assertRaises(ValueError):
                DM.load_catalog(p)


class KnownValueTests(unittest.TestCase):
    """归档 run 数值的已知值断言（含 T6 十一项：营收同比/毛利率/FCF 率/SBC 率/研发率/Rule of 40/
    DSO/应收-收入增速差/收入全周期 CAGR/人均创收/SGA 率）。"""

    @classmethod
    def setUpClass(cls):
        cls.workdir = make_workdir()
        with contextlib.redirect_stderr(io.StringIO()):  # 吞「未获取」提示噪音
            cls.rc = DM.run(cls.workdir)
        cls.rows, cls.values = read_derived(cls.workdir)

    def test_exit_zero_and_contract(self):
        self.assertEqual(0, self.rc)
        header = list(self.rows[0].keys())
        self.assertEqual(["metric", "label", "period", "value", "unit", "formula", "inputs", "anchor"], header)
        for r in self.rows:  # 每行都有公式/锚可溯源
            self.assertTrue(r["metric"] and r["period"] and r["unit"])

    def test_t6_eleven_metrics(self):
        v = self.values
        self.assertEqual("131.9", v[("yoy_revenue", "FY2025")])
        self.assertEqual("150.9", v[("yoy_revenue", "FY2024")])
        self.assertEqual("116.9", v[("yoy_revenue", "FY2023")])
        self.assertEqual("41.0", v[("gm_pct", "FY2025")])
        self.assertEqual("56.3", v[("gm_pct", "FY2024")])
        self.assertEqual("-313.3", v[("fcf_margin", "FY2025")])
        self.assertEqual("-761.1", v[("fcf_margin", "FY2024")])
        self.assertEqual("77.1", v[("sbc_revenue", "FY2025")])
        self.assertEqual("439.1", v[("rd_revenue", "FY2025")])
        self.assertEqual("-181.4", v[("rule_of_40", "FY2025")])
        self.assertEqual("152.8", v[("dso_net", "FY2025")])
        self.assertEqual("106.5", v[("dso_net", "FY2024")])
        self.assertEqual("100.9", v[("recv_growth_gap_pp", "FY2025")])
        self.assertEqual("98.0", v[("yoy_deferred", "FY2025")])
        self.assertEqual("132.8", v[("cagr_revenue_full", "FY2022→FY2025")])
        self.assertEqual("66.2", v[("rev_per_capita", "FY2025")])
        self.assertEqual("123.7", v[("sga_revenue", "FY2025")])

    def test_incident_metric_row_shape(self):
        # 事故指标：period 列显式写窗口、公式与输入可机读回放
        row = next(r for r in self.rows if r["metric"] == "cagr_revenue_full")
        self.assertEqual("FY2022→FY2025", row["period"])
        self.assertEqual("cagr(revenue)", row["formula"])
        self.assertIn("revenue[FY2022]=57409", row["inputs"])
        self.assertIn("revenue[FY2025]=724334", row["inputs"])

    def test_more_known_values(self):
        v = self.values
        self.assertEqual("54.6", v[("gm_pct", "FY2022")])
        self.assertEqual("64.6", v[("gm_pct", "FY2023")])
        self.assertEqual("-651.4", v[("net_margin", "FY2025")])
        self.assertEqual("-522.8", v[("om_pct", "FY2025")])
        self.assertEqual("-53.6", v[("accruals_ratio", "FY2025")])
        self.assertEqual("-19.7", v[("accruals_ratio", "FY2024")])
        self.assertEqual("555.7", v[("ps_fy", "最新")])  # 1007×465,623,090×0.8585/1000/724,334
        # 输入缺失的年份不输出（首财年无基期 / 现金流缺失）
        self.assertNotIn(("yoy_revenue", "FY2022"), v)
        self.assertNotIn(("fcf_margin", "FY2022"), v)
        self.assertNotIn(("om_pct", "FY2024"), v)

    def test_external_kpi_missing_visible(self):
        # saas external KPI 未转录 → 保留「未获取」行（缺口可见，不静默消失）
        self.assertEqual(DM.NOT_OBTAINED, self.values[("arr", "最新")])

    def test_deterministic_and_source_untouched(self):
        path = os.path.join(self.workdir, "forensic", "derived.csv")
        with open(path, "rb") as f:
            first = f.read()
        with contextlib.redirect_stderr(io.StringIO()):
            DM.run(self.workdir)
        with open(path, "rb") as f:
            second = f.read()
        self.assertEqual(first, second)  # 重跑产物逐字节一致（无时间戳/随机性）
        with open(os.path.join(self.workdir, "forensic", "financials.csv"), "r", encoding="utf-8", newline="") as f:
            self.assertEqual(CSV_TEXT, f.read())  # 原文未被改写

    def test_summary_written(self):
        with open(os.path.join(self.workdir, "forensic", "derived-summary.md"), "r", encoding="utf-8") as f:
            text = f.read()
        self.assertIn("派生指标摘要", text)
        self.assertIn("cagr(revenue)", text)
        self.assertIn("132.8", text)


class RobustnessTests(unittest.TestCase):
    def test_anchor_failure_fails_loud_no_output(self):
        doc = json.loads(json.dumps(INPUTS_DOC))
        doc["inputs"][0]["anchor"] = "股份支付 999,999"  # ledger 中不存在的锚
        workdir = make_workdir(inputs_doc=doc)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                DM.run(workdir)
        self.assertEqual(1, cm.exception.code)
        self.assertIn("股份支付 999,999", err.getvalue())
        self.assertIn("anchor", err.getvalue())
        self.assertFalse(os.path.exists(os.path.join(workdir, "forensic", "derived.csv")))
        self.assertFalse(os.path.exists(os.path.join(workdir, "forensic", "derived-summary.md")))

    def test_empty_anchor_rejected(self):
        doc = json.loads(json.dumps(INPUTS_DOC))
        doc["inputs"][1]["anchor"] = ""
        workdir = make_workdir(inputs_doc=doc)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                DM.run(workdir)
        self.assertEqual(1, cm.exception.code)

    def test_missing_column_degrades_to_not_obtained(self):
        lines = CSV_TEXT.splitlines()
        keep = [i for i, c in enumerate(lines[0].split(",")) if c != "sga"]
        csv_no_sga = "\n".join(",".join(line.split(",")[i] for i in keep) for line in lines) + "\n"
        workdir = make_workdir(csv_text=csv_no_sga)
        with contextlib.redirect_stderr(io.StringIO()):
            rc = DM.run(workdir)
        self.assertEqual(0, rc)
        _, values = read_derived(workdir)
        self.assertEqual(DM.NOT_OBTAINED, values[("sga_revenue", "FY2025")])  # 防呆：缺列不崩溃
        self.assertEqual("131.9", values[("yoy_revenue", "FY2025")])          # 其余指标不受影响

    def test_no_inputs_file_runs_csv_only(self):
        workdir = make_workdir(inputs_doc=None, ledger_text=None)
        with contextlib.redirect_stderr(io.StringIO()):
            rc = DM.run(workdir)
        self.assertEqual(0, rc)
        _, values = read_derived(workdir)
        self.assertEqual("132.8", values[("cagr_revenue_full", "FY2022→FY2025")])
        self.assertEqual(DM.NOT_OBTAINED, values[("sbc_revenue", "FY2025")])  # 外部输入未转录
        self.assertEqual(DM.NOT_OBTAINED, values[("ps_fy", "最新")])
        self.assertNotIn(("rule_of_40", "FY2025"), values)  # industry 回退 any：saas 项不跑
        self.assertNotIn(("arr", "最新"), values)

    def test_external_passthrough_with_anchor(self):
        doc = json.loads(json.dumps(INPUTS_DOC))
        doc["inputs"].append({"key": "arr", "value": "2026-07 破 10 亿美元", "unit": "亿美元",
                              "period": "最新", "anchor": "ARR 里程碑：2026-01 约 0.4 亿美元 → 2026-07 破 10 亿美元",
                              "ts": "2026-08-25"})
        workdir = make_workdir(inputs_doc=doc)
        with contextlib.redirect_stderr(io.StringIO()):
            rc = DM.run(workdir)
        self.assertEqual(0, rc)
        rows, _ = read_derived(workdir)
        row = next(r for r in rows if r["metric"] == "arr")
        self.assertEqual("2026-07 破 10 亿美元", row["value"])
        self.assertEqual("亿美元", row["unit"])
        self.assertIn("arr@ARR 里程碑", row["anchor"])

    def test_formula_referenced_input_must_be_numeric(self):
        doc = json.loads(json.dumps(INPUTS_DOC))
        doc["inputs"][0]["value"] = "558,265千元"  # sbc 被公式引用但非数字
        workdir = make_workdir(inputs_doc=doc)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                DM.run(workdir)
        self.assertEqual(1, cm.exception.code)


if __name__ == "__main__":
    unittest.main()
