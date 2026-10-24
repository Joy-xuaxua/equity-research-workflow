import contextlib
import copy
import importlib.util
import io
import os
import random
import subprocess
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
SCRIPT = os.path.join(ROOT, "scripts", "dcf.py")
SPEC = importlib.util.spec_from_file_location("dcf", SCRIPT)
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)


def inputs():
    return copy.deepcopy(D.DEMO3_INPUTS)


def cfg():
    return copy.deepcopy(D.DEMO3)


def evaluate(i=None, c=None, **kw):
    return D.evaluate(i or inputs(), c or cfg(), **kw)


def method(ev, mid):
    return next(m for m in ev["methods"] if m["id"] == mid)


class WeightedQuantileTest(unittest.TestCase):
    def test_single_value(self):
        self.assertEqual(D.wquantile([5.0], [1.0], 0.5), 5.0)

    def test_two_methods_interpolates(self):
        # 位置 0.25 / 0.75 → q=0.5 在两者正中
        self.assertAlmostEqual(D.wquantile([10.0, 20.0], [1.0, 1.0], 0.5), 15.0)

    def test_primary_half_weight_not_stuck_on_boundary(self):
        # 主方法 0.5：位置 0.25（主）与 0.75 → 中位数为两者中点，而非恰好卡在边界
        self.assertAlmostEqual(D.wquantile([10.0, 30.0], [0.5, 0.5], 0.5), 20.0)

    def test_clamps_out_of_range(self):
        self.assertEqual(D.wquantile([1.0, 2.0, 3.0], [1, 1, 1], 0.0), 1.0)
        self.assertEqual(D.wquantile([1.0, 2.0, 3.0], [1, 1, 1], 1.0), 3.0)

    def test_zero_weight_and_empty(self):
        self.assertIsNone(D.wquantile([1.0], [0.0], 0.5))
        self.assertEqual(D.wquantile([1.0, 9.0], [1.0, 0.0], 0.5), 1.0)

    def test_continuous_in_weights(self):
        vals = [10.0, 14.0, 30.0]
        a = D.wquantile(vals, [0.5, 0.25, 0.25], 0.5)
        b = D.wquantile(vals, [0.5001, 0.2499, 0.25], 0.5)
        self.assertLess(abs(a - b), 0.01)

    def test_composite_low_never_above_high(self):
        rng = random.Random(7)
        fallbacks = 0
        for _ in range(5000):
            n = rng.randint(1, 5)
            lo = [rng.uniform(0, 100) for _ in range(n)]
            hi = [x + rng.uniform(0, 50) for x in lo]
            mid = [(a + b) / 2 for a, b in zip(lo, hi)]
            w = [rng.uniform(0.05, 1) for _ in range(n)]
            L, H, fb = D.composite_range(lo, hi, mid, w)
            fallbacks += fb
            self.assertLessEqual(L, H + 1e-9)
            if not fb:
                self.assertEqual((L, H), (D.wquantile(lo, w, 0.5), D.wquantile(hi, w, 0.5)))
        self.assertGreater(fallbacks, 0)  # 回退分支确实被覆盖

    def test_midpoint_cdf_bear_heavy(self):
        # 熊概率 >0.5：P25 落在熊值上（夹端）
        self.assertEqual(D.wquantile([1.0, 5.0, 9.0], [0.6, 0.25, 0.15], 0.25), 1.0)


class GrowthPathTest(unittest.TestCase):
    def test_terminal_year_equals_g_inf(self):
        for hl in (0.5, 1, 3, 5):
            p = D.growth_path(0.4, 0.3, hl, 0.025, 10)
            self.assertEqual(len(p), 10)
            self.assertAlmostEqual(p[0], 0.4)
            self.assertAlmostEqual(p[1], 0.3)
            self.assertAlmostEqual(p[-1], 0.025)

    def test_monotone_decay(self):
        p = D.growth_path(0.2, 0.2, 3, 0.02, 10)
        self.assertTrue(all(a >= b - 1e-12 for a, b in zip(p[1:], p[2:])))


class ProjectionIdentityTest(unittest.TestCase):
    def setUp(self):
        self.F, _ = D.resolve_facts(inputs(), cfg())
        self.term = {"g": 0.02, "roiic": None, "roiic_reason": None}
        self.d = D.scenario_drivers(cfg(), cfg()["scenarios"][1], self.F)

    def test_tv_equals_nopat_over_wacc_when_roiic_is_wacc(self):
        r = D.project(self.d, self.F, 0.09, self.term)
        self.assertAlmostEqual(r["tv"], r["nopat_n1"] * (1 - 0.02 / 0.09) / (0.09 - 0.02))
        self.assertAlmostEqual(r["tv"], r["nopat_n1"] / 0.09)

    def test_eva_identity(self):
        for roiic in (None, 0.12):
            r = D.project(self.d, self.F, 0.09, self.term, roiic=roiic)
            self.assertAlmostEqual(r["eva"]["ev"], r["ev"], delta=1e-6 * abs(r["ev"]))

    def test_nol_shields_tax_after_losses(self):
        d = dict(self.d, m1=-0.10, margin_target=0.10, margin_years=2, nol_open=0.0)
        r = D.project(d, self.F, 0.09, self.term)
        rows = r["rows"]
        self.assertEqual(rows[0]["nopat"], rows[0]["ebit"])  # 亏损年不交税
        first_profit = next(x for x in rows if x["ebit"] > 0)
        self.assertGreater(first_profit["nopat"], first_profit["ebit"] * (1 - d["tax"]))  # NOL 抵扣

    def test_capital_release_floor(self):
        d = dict(self.d, g1=-0.5, g2=-0.5, half_life=5, allow_capital_release=True, sales_to_capital=0.2)
        r = D.project(d, self.F, 0.09, self.term)
        self.assertGreaterEqual(sum(x["reinv"] for x in r["rows"]), -self.F["invested_capital"] - 1e-6)
        d2 = dict(d, allow_capital_release=False)
        self.assertTrue(all(x["reinv"] >= 0 for x in D.project(d2, self.F, 0.09, self.term)["rows"]))

    def test_terminal_loss_drops_reinvestment_term(self):
        d = dict(self.d, m1=-0.2, margin_target=-0.05)
        r = D.project(d, self.F, 0.09, self.term, roiic=0.05)
        self.assertTrue(r["terminal_loss"])
        self.assertAlmostEqual(r["tv"], r["nopat_n1"] / (0.09 - 0.02))


class GateTest(unittest.TestCase):
    def test_demo_reliable(self):
        ev = evaluate()
        self.assertEqual(ev["syn"]["label"], "合理")
        self.assertAlmostEqual(sum(m["weight"] for m in ev["methods"] if m["gate"] is None), 1.0)
        self.assertAlmostEqual(method(ev, "dcf")["weight"], 0.5)

    def test_negative_base_gates_dcf(self):
        c = cfg()
        for s in c["scenarios"]:
            s["margin_target"] = -0.05
        c["drivers"]["m1"] = -0.05
        ev = evaluate(c=c)
        self.assertIn("经营价值为负", method(ev, "dcf")["gate"])
        self.assertIn("经营价值为负", ev["syn"]["flags"])

    def test_fcff_not_applicable_gates_dcf_and_epv(self):
        i = inputs()
        i["industry"] = "banks"
        c = cfg()
        c["methods"]["multiples"]["items"][1]["peers"] = [{"name": n, "value": v, "source": "t"} for n, v in
                                                          (("a", 10), ("b", 12), ("c", 14))]
        del c["methods"]["multiples"]["items"][1]["history"]
        ev = evaluate(i, c)
        self.assertIsNotNone(method(ev, "dcf")["gate"])
        self.assertIsNotNone(method(ev, "epv")["gate"])
        self.assertIsNotNone(ev["syn"]["label"])
        self.assertIn("单一方法", ev["syn"]["flags"])

    def test_epv_gate_on_negative_normalized_nopat(self):
        i = inputs()
        i["facts"]["op_margin_median_5y"]["value"] = -0.02
        self.assertEqual(method(evaluate(i), "epv")["gate"], "常态化 NOPAT ≤0")

    def test_multiple_needs_three_obs_and_positive_metric(self):
        c = cfg()
        c["methods"]["multiples"]["items"][0]["peers"] = c["methods"]["multiples"]["items"][0]["peers"][:2]
        i = inputs()
        i["facts"]["net_income_ttm"]["value"] = -1.0
        ev = evaluate(i, c)
        items = method(ev, "multiples")["items"]
        self.assertIn("<3", items[0]["gate"])
        self.assertIn("≤0", items[1]["gate"])
        self.assertIsNotNone(method(ev, "multiples")["gate"])

    def test_band_rejected(self):
        c = cfg()
        c["methods"]["multiples"]["items"][0]["band"] = [10, 20]
        with self.assertRaises(ValueError):
            evaluate(c=c)

    def test_asset_ladder_without_realization_path_is_signal_only(self):
        c = cfg()
        c["methods"]["sum_of_parts"] = {"kind": "asset_ladder", "parts": [
            {"name": "net", "type": "value", "lo": 1_000_000, "hi": 3_000_000, "source": "t"}]}
        ev = evaluate(c=c)
        self.assertTrue(method(ev, "sum_of_parts").get("signal_only"))
        self.assertNotIn("weight", method(ev, "sum_of_parts"))
        c["methods"]["sum_of_parts"]["realization_path"] = {"evidence": "处置公告", "source": "HKEX 2026-01-01"}
        self.assertIsNone(method(evaluate(c=c), "sum_of_parts")["gate"])

    def test_all_gated_is_unreliable(self):
        c = cfg()
        for s in c["scenarios"]:
            s["margin_target"] = -0.05
        c["drivers"]["m1"] = -0.05
        c["methods"] = {"epv": False}
        ev = evaluate(c=c)
        self.assertIsNone(ev["syn"]["label"])
        self.assertEqual(ev["syn"]["reason"], "全部方法被闸门剔除")

    def test_clip_before_interpolate(self):
        c = cfg()
        c["scenarios"][0]["margin_target"] = -0.30  # 熊情景为负 → 截 0 后再插值
        dcf = method(evaluate(c=c), "dcf")
        self.assertGreaterEqual(dcf["lo"], 0.0)


class RuleTest(unittest.TestCase):
    def test_g_above_rf_is_hard_error(self):
        c = cfg()
        c["terminal"]["g"] = 0.05
        with self.assertRaises(ValueError):
            evaluate(c=c)

    def test_default_g_is_min_rf_2_5(self):
        c = cfg()
        del c["terminal"]["g"]
        self.assertAlmostEqual(evaluate(c=c)["term"]["g"], 0.025)

    def test_weight_adjust_limit(self):
        c = cfg()
        c["weights"] = {"adjust": {"epv": 0.15}, "reasons": {"epv": "x"}}
        with self.assertRaises(ValueError):
            evaluate(c=c)
        c["weights"] = {"adjust": {"epv": 0.1}, "reasons": {"epv": "x"}}
        self.assertAlmostEqual(method(evaluate(c=c), "epv")["weight"], 0.35 / 1.1)  # 调整后归一
        c["weights"] = {"adjust": {"epv": 0.1}}
        with self.assertRaises(ValueError):
            evaluate(c=c)

    def test_basis_flag_requires_handling(self):
        c = cfg()
        del c["basis_confirmed"]
        with self.assertRaises(ValueError):
            evaluate(c=c)
        c["pro_forma"] = {"cash_delta": 50_000, "shares_basis": "不变", "source": "ledger"}
        ev = evaluate(c=c)
        self.assertEqual(ev["F"]["_pf_cash"], 50_000)

    def test_legacy_paths_rejected(self):
        c = cfg()
        c["scenarios"][1]["revenue"] = [1, 2, 3]
        with self.assertRaises(ValueError):
            evaluate(c=c)

    def test_probability_floor_and_evidence_warnings(self):
        c = cfg()
        c["scenarios"][0].update(prob=0.10, evidence="中强")
        c["scenarios"][1].update(prob=0.65, evidence="弱")
        w = " ".join(evaluate(c=c)["warnings"])
        self.assertIn("PROB_FLOOR", w)
        self.assertIn("证据中强", w)
        self.assertIn("基准情景证据弱", w)

    def test_extreme_growth_requires_reason(self):
        c = cfg()
        c["scenarios"][2].update(g1=0.9, half_life=5)
        with self.assertRaises(ValueError):
            evaluate(c=c)
        c["scenarios"][2]["extreme_growth_reason"] = "x"
        evaluate(c=c)

    def test_unclean_s2c_requires_explicit_value(self):
        i = inputs()
        i["facts"]["sales_to_capital_hist"]["clean"] = False
        c = cfg()
        del c["drivers"]["sales_to_capital"]
        with self.assertRaises(ValueError):
            evaluate(i, c)
        evaluate(inputs(), copy.deepcopy(c))  # 干净 → 默认取历史

    def test_override_logged(self):
        c = cfg()
        c["overrides"] = [{"field": "base_revenue", "value": 1_100_000, "reason": "TTM", "source": "ledger"}]
        ev = evaluate(c=c)
        self.assertEqual(ev["F"]["base_revenue"], 1_100_000)
        self.assertEqual(ev["overrides"][0][0], "base_revenue")

    def test_custom_must_live_in_calc(self):
        c = cfg()
        c["methods"]["custom"] = [{"name": "nav", "script": "valuation/nav.py", "lo": 1, "mid": 2, "hi": 3}]
        with self.assertRaises(ValueError):
            evaluate(c=c)
        c["methods"]["custom"][0]["script"] = "valuation/calc/nav.py"
        c["methods"]["custom"][0].update(lo=100, mid=200, hi=300)
        ev = evaluate(c=c)
        self.assertLessEqual(method(ev, "custom:nav")["weight"], D.CUSTOM_CAP + 1e-9)


class PerturbationTest(unittest.TestCase):
    def test_robustness_set(self):
        ev = evaluate()
        rows = D.robustness(inputs(), cfg(), ev, None)
        names = [r[0] for r in rows]
        self.assertEqual(len(rows), 10)
        self.assertIn("WACC +1pp", names)
        self.assertTrue(all(r[4] in ("翻转", "不变", "不适用") for r in rows))

    def test_prob_shift_respected(self):
        a = evaluate()["syn"]
        b = evaluate(pert={"prob_shift": ("base", "bear", 0.15)})["syn"]
        self.assertLess(b["L"], a["L"])

    def test_tornado_sorted(self):
        ev = evaluate()
        base = next(s for s in ev["scen"] if s["name"] == "base")
        _, tor = D.tornado(base, ev["F"], ev["wacc"], ev["term"])
        spans = [t[3] for t in tor]
        self.assertEqual(spans, sorted(spans, reverse=True))

    def test_mc_deterministic(self):
        ev = evaluate()
        a = D.montecarlo3(ev["scen"], ev["F"], ev["wacc"], ev["term"], {"n": 300, "seed": 1})
        b = D.montecarlo3(ev["scen"], ev["F"], ev["wacc"], ev["term"], {"n": 300, "seed": 1})
        self.assertEqual(a, b)


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        env = dict(os.environ, PYTHONUTF8="1")
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, encoding="utf-8", env=env)

    def test_legacy_demo_output_unchanged(self):
        with io.open(os.path.join(ROOT, "tests", "golden", "dcf_demo_legacy.txt"), encoding="utf-8") as f:
            golden = f.read()
        out = self.run_cli("--demo")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.replace("\r\n", "\n"), golden.replace("\r\n", "\n"))

    def test_demo3_calibration_line(self):
        out = self.run_cli("--demo3")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("=== 标定 === 综合区间 [", out.stdout)
        self.assertIn("**合理**", out.stdout)

    def test_unreliable_line_printed(self):
        c = cfg()
        for s in c["scenarios"]:
            s["margin_target"] = -0.05
        c["drivers"]["m1"] = -0.05
        c["methods"] = {"epv": False}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            D.run3(inputs(), c)
        self.assertIn(f"=== 标定 === {D.UNRELIABLE}（", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
