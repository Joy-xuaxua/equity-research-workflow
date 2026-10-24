import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
SCRIPT = os.path.join(ROOT, "scripts", "valuation_inputs.py")
SPEC = importlib.util.spec_from_file_location("valuation_inputs", SCRIPT)
VI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VI)

HEADER = ("period,revenue,gross_profit,operating_income,net_income,cfo,capex,fcf,shares,eps,total_assets,"
          "receivables,ppe,current_assets,depreciation,sga,total_liabilities,cash,interest_bearing_debt,"
          "pre_tax_income,deferred_revenue,minority_equity,goodwill\n")

# 夹具＝归档 run（Zhipu 02513.HK 0901）financials.csv 原文：FY2022/23 行比表头多 1 个字段，
# 总负债错位进了 cash 列（cash 542,164 > 总资产 361,976）。
ZHIPU_CSV = HEADER + (
    "FY2022,57409,31360,,-143650,,,,,,361976,,,,,,,542164,,,,,,\n"
    "FY2023,124538,80482,,-787957,,,,,,2860153,,,,,,,3842746,,,,,,\n"
    "FY2024,312414,175889,,-2958007,-2244919,132760,-2377679,,,4375769,91135,,,,,8330914,,,,,,75059\n"
    "FY2025,724334,296656,-3786750,-4718167,-2246123,23088,-2269211,159522220,-12.03,4853861,303208,655825,"
    "3571411,,896226,12964843,2259147,1234595,,148644,-18480,39379\n"
    "2025H1,190877,95424,-1899225,-2357852,,,,159522000,-6.23,,,,,,393735,,,,,,,\n"
    "2026H1,953892,251611,-2146552,-2071992,,,,432359000,-4.67,9644830,782944,855060,6993696,,281012,"
    "5215274,3993722,2604199,-2070030,302325,12508,283815\n"
)

CLEAN_CSV = HEADER + (
    "FY2022,1000,500,100,80,,,,,,2000,,,,50,,800,300,200,100,,,\n"
    "FY2023,1100,550,120,90,,,,,,2100,,,,55,,820,320,200,115,,,\n"
    "FY2024,1200,600,130,100,,,,,,2200,,,,60,,850,330,210,125,,,\n"
    "FY2025,1300,650,150,110,,,,,,2300,,,,65,,860,350,220,140,,,\n"
)

LOSS_CSV = HEADER + (
    "FY2023,1000,500,-100,-120,,,,,,2000,,,,,,900,300,200,-110,,,\n"
    "FY2024,900,450,-150,-160,,,,,,1900,,,,,,950,250,250,-160,,,\n"
    "FY2025,800,400,-200,-210,,,,,,1800,,,,,,1000,200,300,-205,,,\n"
)

LEDGER = "收盘价 30.00 元（2026-03-31 收盘）\n总股本 100,000,000 股（2026-02-28）\nHKD/CNY＝0.857\n"


def inputs_doc(fx=None):
    rows = [
        {"key": "price_close", "value": 30.0, "unit": "元/股", "period": "最新",
         "anchor": "收盘价 30.00 元（2026-03-31 收盘）", "ts": "2026-04-01"},
        {"key": "shares_outstanding", "value": 100000000, "unit": "股", "period": "最新",
         "anchor": "总股本 100,000,000 股（2026-02-28）", "ts": "2026-04-01"},
    ]
    if fx:
        rows.append({"key": fx[0], "value": fx[1], "unit": "", "period": "最新", "anchor": "HKD/CNY＝0.857"})
    return {"industry": "consumer", "inputs": rows}


class Workdir:
    def __init__(self, csv_text, fx=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name
        os.makedirs(os.path.join(self.path, "forensic"))
        with io.open(os.path.join(self.path, "forensic", "financials.csv"), "w", encoding="utf-8") as f:
            f.write(csv_text)
        with io.open(os.path.join(self.path, "forensic", "derived-inputs.json"), "w", encoding="utf-8") as f:
            json.dump(inputs_doc(fx), f, ensure_ascii=False)
        with io.open(os.path.join(self.path, "forensic", "ledger.md"), "w", encoding="utf-8") as f:
            f.write(LEDGER)

    def __enter__(self):
        return self.path

    def __exit__(self, *a):
        self.tmp.cleanup()


class HygieneTest(unittest.TestCase):
    def test_zhipu_row_shift_fails_loud(self):
        with Workdir(ZHIPU_CSV) as wd:
            codes = [c for c, _ in VI.csv_hygiene(os.path.join(wd, "forensic", "financials.csv"))]
            self.assertEqual(codes.count("CSV_ROW_LENGTH"), 2)
            with self.assertRaises(VI.InputsError):
                VI.build(wd)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(VI.main([wd]), 1)
            self.assertFalse(os.path.exists(os.path.join(wd, "valuation", "inputs.json")))

    def test_cash_above_assets(self):
        bad = CLEAN_CSV.replace("FY2025,1300,650,150,110,,,,,,2300,,,,65,,860,350",
                                "FY2025,1300,650,150,110,,,,,,2300,,,,65,,860,3500")
        with Workdir(bad) as wd:
            codes = [c for c, _ in VI.csv_hygiene(os.path.join(wd, "forensic", "financials.csv"))]
            self.assertIn("CSV_CASH_GT_ASSETS", codes)


class BuildTest(unittest.TestCase):
    def test_half_year_ttm_and_net_debt(self):
        fixed = "\n".join(l for l in ZHIPU_CSV.splitlines() if not l.startswith(("FY2022", "FY2023"))) + "\n"
        with Workdir(fixed, fx=("fx_hkd_cny", 0.857)) as wd:
            doc = VI.build(wd)
            f = doc["facts"]
            self.assertEqual(f["base_revenue"]["value"], 724334 + 953892 - 190877)
            self.assertEqual(f["base_revenue"]["basis"], "TTM 2026H1")
            self.assertAlmostEqual(f["op_margin_reported"]["value"],
                                   (-3786750 - 2146552 + 1899225) / (724334 + 953892 - 190877))
            self.assertEqual(f["net_debt"]["period"], "2026H1")
            self.assertEqual(f["net_debt"]["value"], 2604199 - 3993722 + 12508)
            self.assertEqual(f["invested_capital"]["value"], (9644830 - 5215274) + 2604199 - 3993722)
            self.assertFalse(f["sales_to_capital_hist"]["clean"])     # FY2025 IC<0
            self.assertIsNone(f["tax_effective"]["value"])            # 无盈利年份

    def test_fx_direction(self):
        with Workdir(CLEAN_CSV, fx=("fx_hkd_cny", 0.857)) as wd:
            fx = VI.build(wd)["facts"]["fx"]
            self.assertEqual((fx["price_ccy"], fx["report_ccy"], fx["value"]), ("hkd", "cny", 0.857))
            self.assertIn("1 HKD = 0.857 CNY", fx["formula"])
        with Workdir(CLEAN_CSV) as wd:
            fx = VI.build(wd)["facts"]["fx"]
            self.assertEqual(fx["value"], 1.0)
            self.assertTrue(fx["flags"])

    def test_basis_flag(self):
        with Workdir(CLEAN_CSV) as wd:
            b = VI.build(wd)["basis"]
            self.assertTrue(b["basis_flag"])
            self.assertEqual(b["balance_sheet_date"], "2025-12-31")
            self.assertEqual(b["shares_date"], "2026-02-28")
            self.assertEqual(b["price_date"], "2026-03-31")

    def test_clean_history_and_tax(self):
        with Workdir(CLEAN_CSV) as wd:
            f = VI.build(wd)["facts"]
            self.assertTrue(f["sales_to_capital_hist"]["clean"])
            self.assertEqual(f["base_revenue"]["basis"], "FY2025")
            rates = sorted(1 - ni / pti for ni, pti in ((80, 100), (90, 115), (100, 125), (110, 140)))
            self.assertAlmostEqual(f["tax_effective"]["value"], (rates[1] + rates[2]) / 2)
            self.assertEqual(len(f["history"]), 4)

    def test_negative_ic_and_no_tax(self):
        with Workdir(LOSS_CSV) as wd:
            f = VI.build(wd)["facts"]
            self.assertIsNone(f["tax_effective"]["value"])
            self.assertGreater(f["invested_capital"]["value"], 0)
            self.assertAlmostEqual(f["op_margin_median_5y"]["value"], -150 / 900)

    def test_main_writes_inputs(self):
        with Workdir(CLEAN_CSV) as wd:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(VI.main([wd]), 0)
            with io.open(os.path.join(wd, "valuation", "inputs.json"), encoding="utf-8") as fh:
                doc = json.load(fh)
            self.assertEqual(doc["generated_by"], "scripts/valuation_inputs.py")


if __name__ == "__main__":
    unittest.main()
