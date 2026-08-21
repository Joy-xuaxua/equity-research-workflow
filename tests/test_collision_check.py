import importlib.util
import json
import os
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
SCRIPT = os.path.join(ROOT, "scripts", "collision_check.py")
SPEC = importlib.util.spec_from_file_location("collision_check", SCRIPT)
CC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CC)


def entry(key, value, unit, period, anchor, scope=None, source="测试源", tier="3", ts="2026-08-18"):
    e = {"key": key, "value": value, "unit": unit, "period": period, "anchor": anchor,
         "source": source, "tier": tier, "ts": ts}
    if scope:
        e["scope"] = scope
    return e


def build_file(entries, conflict_rows=None, duplicate_anchor=None):
    lines = ["# 采集文件：测试", "", "## 发现", ""]
    for e in entries:
        lines.append(f"- {e['anchor']}")
    if duplicate_anchor:
        lines.append(f"- {duplicate_anchor}")
    lines += ["", "## 指标登记", "```yaml"]
    for e in entries:
        lines.append(f"- key: {e['key']}")
        for f in ("value", "unit", "period", "scope", "source", "tier", "ts", "anchor"):
            if e.get(f):
                lines.append(f"  {f}: {e[f]}")
    lines += ["```", "", "## 冲突"]
    if conflict_rows:
        lines.append("| 指标 | 值 A | 来源 A | 值 B | 来源 B | 口径差异初判 |")
        lines.append("|---|---|---|---|---|---|")
        for r in conflict_rows:
            lines.append("| " + " | ".join(str(c) for c in r) + " |")
    lines += ["", "## 未获取到", "", "| 条目 | 已尝试 | 原因 |", "|---|---|---|", "", "## 原文附录", ""]
    return "\n".join(lines) + "\n"


def make_workdir(files):
    tmp = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmp, "collection"))
    for fname, content in files.items():
        with open(os.path.join(tmp, "collection", fname), "w", encoding="utf-8") as f:
            f.write(content)
    return tmp


def run_on(files, **kw):
    workdir = make_workdir(files)
    return CC.run(workdir, out=os.path.join(workdir, "collision-report.txt"), **kw)


class RegistryTests(unittest.TestCase):
    def test_registry_loads_and_consistent(self):
        reg = CC.load_registry()
        self.assertEqual(1, reg["version"])
        cc = {c["id"]: c for c in reg["crosschecks"]}
        self.assertEqual(6, len(cc))
        for key, meta in reg["metrics"].items():
            self.assertIn(meta["unit"], reg["units"], key)
            for cid in meta.get("crosschecks", []):
                self.assertIn(cid, cc, (key, cid))
        refd = {cid for m in reg["metrics"].values() for cid in m.get("crosschecks", [])}
        self.assertEqual(set(cc), refd)

    def test_registry_version_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "bad.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"version": 2}, f)
            with self.assertRaises(ValueError):
                CC.load_registry(p)


class ParserTests(unittest.TestCase):
    def test_canonical_period_variants(self):
        cases = {
            "FY2025": "FY2025", "财年2025": "FY2025", "2025": "FY2025", "2025财年": "FY2025",
            "2025H1": "2025H1", "1H2025": "2025H1", "2025上半年": "2025H1", "2025H2": "2025H2",
            "FY2026Q1": "FY2026Q1", "2026Q1": "FY2026Q1", "2026财年Q3": "FY2026Q3",
            "最新": "最新", "当前": "最新", "TTM": "TTM", "滚动十二个月": "TTM",
            "2025-03-31": "2025-03-31",
        }
        for raw, want in cases.items():
            self.assertEqual(want, CC.canonical_period(raw), raw)
        self.assertIsNone(CC.canonical_period("FY25 春"))

    def test_parse_number_loose(self):
        self.assertEqual((4856.0, 4856.0), CC.parse_number_loose("4,856"))
        self.assertEqual((120000.0, 150000.0), CC.parse_number_loose("120,000–150,000"))
        self.assertEqual((1.2, 1.5), CC.parse_number_loose("约 1.2~1.5"))
        self.assertEqual((-3.5, -3.5), CC.parse_number_loose("-3.5"))
        self.assertEqual((None, None), CC.parse_number_loose("未获取到"))

    def test_parse_unit_exact_and_compound(self):
        units = CC.load_registry()["units"]
        self.assertEqual(("currency", 1e8, "HKD"), CC.parse_unit("亿港元", units))
        self.assertEqual(("currency", 1e4, "CNY"), CC.parse_unit("万人民币", units))
        self.assertEqual(("currency", 1e8, "CNY"), CC.parse_unit("亿元人民币", units))
        self.assertEqual(("currency", 1e6, "USD"), CC.parse_unit("百万美元", units))
        self.assertEqual(("shares", 1e8, None), CC.parse_unit("亿股", units))
        self.assertIsNone(CC.parse_unit("光年", units))


class CollisionTests(unittest.TestCase):
    def test_cross_file_value_mismatch_is_p1(self):
        e1 = entry("shares_outstanding", "46,562", "万股", "最新", "月报表总股本46,562万股口径核对")
        e2 = entry("shares_outstanding", "2.41", "亿股", "最新", "富途口径H股总数2.41亿股快照")
        code, issues = run_on({"01-disclosure.md": build_file([e1]), "02-market.md": build_file([e2])})
        self.assertEqual(1, code)
        self.assertTrue(any(i.code == "COLLISION_VALUE_MISMATCH" and i.severity == "P1" for i in issues))

    def test_equal_value_across_unit_scales_no_collision(self):
        e1 = entry("shares_outstanding", "46,562", "万股", "最新", "月报表总股本46,562万股口径核对")
        e2 = entry("shares_outstanding", "4.6562", "亿股", "最新", "招股书披露总股本约4.6562亿股")
        code, issues = run_on({"01-disclosure.md": build_file([e1]), "02-market.md": build_file([e2])})
        self.assertEqual(0, code)
        self.assertFalse([i for i in issues if i.code == "COLLISION_VALUE_MISMATCH"])

    def test_currency_mismatch_is_p2_not_p1(self):
        e1 = entry("market_cap", "4,856", "亿港元", "最新", "港股市值4,856亿港元快照")
        e2 = entry("market_cap", "4,428", "亿人民币", "最新", "按人民币计市值约4,428亿元")
        code, issues = run_on({"01-disclosure.md": build_file([e1]), "02-market.md": build_file([e2])})
        self.assertEqual(0, code)
        self.assertTrue(any(i.code == "CURRENCY_MISMATCH" and i.severity == "P2" for i in issues))
        self.assertFalse([i for i in issues if i.code == "COLLISION_VALUE_MISMATCH"])

    def test_range_overlap_no_collision(self):
        e1 = entry("consensus_revenue_fwd", "300,000–340,000", "万元", "FY2026", "一致预期FY2026收入300,000–340,000万元")
        e2 = entry("consensus_revenue_fwd", "310,000–330,000", "万元", "FY2026", "另一家口径FY2026收入预期310,000–330,000万元")
        code, issues = run_on({"01-disclosure.md": build_file([e1]), "02-market.md": build_file([e2])})
        self.assertEqual(0, code)
        self.assertFalse([i for i in issues if i.code == "COLLISION_VALUE_MISMATCH"])

    def test_self_contradiction_same_file(self):
        e1 = entry("market_cap", "100", "亿港元", "最新", "市值口径甲约100亿港元")
        e2 = entry("market_cap", "200", "亿港元", "最新", "市值口径乙约200亿港元")
        code, issues = run_on({"01-disclosure.md": build_file([e1, e2])})
        self.assertEqual(1, code)
        self.assertTrue(any(i.code == "SELF_CONTRADICTION" for i in issues))

    def test_unknown_key_and_missing_scope(self):
        bad = entry("nonexistent_metric", "1", "元", "FY2025", "某个不存在的指标原文片段占位")
        seg = entry("revenue_segment", "60", "万元", "FY2025", "分部收入60万元之原文片段占位")
        code, issues = run_on({"01-disclosure.md": build_file([bad, seg])})
        self.assertTrue(any(i.code == "REGISTRY_KEY_UNKNOWN" and i.severity == "P1" for i in issues))
        self.assertTrue(any(i.code == "SCOPE_MISSING" and i.severity == "P2" for i in issues))

    def test_anchor_not_unique(self):
        e = entry("revenue", "100", "万元", "FY2025", "营业收入100万元整句原文")
        code, issues = run_on({"01-disclosure.md": build_file([e], duplicate_anchor="重复出现：营业收入100万元整句原文")})
        self.assertTrue(any(i.code == "ANCHOR_NOT_UNIQUE" and i.severity == "P2" for i in issues))

    def test_table_unregistered(self):
        e = entry("revenue", "100", "万元", "FY2025", "营业收入100万元整句原文")
        rows = [("总市值", "4,146", "富途", "4,856", "彭博", "口径差")]
        code, issues = run_on({"01-disclosure.md": build_file([e], conflict_rows=rows)})
        self.assertTrue(any(i.code == "TABLE_UNREGISTERED" and i.severity == "P2" for i in issues))


class CrosscheckTests(unittest.TestCase):
    def test_market_cap_identity_passes(self):
        price = entry("price_close", "1,043", "港元/股", "最新", "收盘价1,043港元每股价快照")
        shares = entry("shares_outstanding", "4.66", "亿股", "最新", "总股本约4.66亿股口径")
        cap = entry("market_cap", "4,856", "亿港元", "最新", "总市值4,856亿港元快照")
        code, issues = run_on({
            "01-disclosure.md": build_file([shares]),
            "02-market.md": build_file([price, cap]),
        })
        self.assertFalse([i for i in issues if i.code == "CROSSCHECK_FAIL"], [i.line() for i in issues])
        self.assertEqual(0, code)

    def test_balance_sheet_identity_fails_p1(self):
        a = entry("total_assets", "35.7", "亿元", "FY2025", "总资产35.7亿元报表行原文")
        l = entry("total_liabilities", "10.0", "亿元", "FY2025", "总负债10.0亿元报表行原文")
        q = entry("total_equity", "31.2", "亿元", "FY2025", "所有者权益31.2亿元行原文")
        code, issues = run_on({"01-disclosure.md": build_file([a, l, q])})
        hits = [i for i in issues if i.code == "CROSSCHECK_FAIL"]
        self.assertEqual(1, len(hits))
        self.assertEqual("P1", hits[0].severity)
        self.assertIn("balance_sheet_identity", hits[0].message)

    def test_segments_sum_fails_p1(self):
        rev = entry("revenue", "100", "万元", "FY2025", "全年营业收入100万元整句")
        s1 = entry("revenue_segment", "60", "万元", "FY2025", "开放平台分部收入60万元", scope="开放平台")
        s2 = entry("revenue_segment", "35", "万元", "FY2025", "技术服务分部收入35万元", scope="技术服务")
        code, issues = run_on({"01-disclosure.md": build_file([rev, s1, s2])})
        hits = [i for i in issues if i.code == "CROSSCHECK_FAIL" and "revenue_segments_sum" in i.message]
        self.assertEqual(1, len(hits))
        self.assertEqual("P1", hits[0].severity)

    def test_pe_identity_falls_back_to_latest_fy(self):
        pe = entry("pe_ttm", "150", "倍", "最新", "市盈率TTM约150倍快照")
        cap = entry("market_cap", "4,500", "亿港元", "最新", "总市值4,500亿港元快照")
        ni = entry("net_income", "20", "亿元", "FY2025", "FY2025净利润20亿元整句")
        code, issues = run_on({
            "02-market.md": build_file([pe, cap]),
            "01-disclosure.md": build_file([ni]),
        })
        hits = [i for i in issues if i.code == "CROSSCHECK_FAIL" and "pe_identity" in i.message]
        self.assertEqual(1, len(hits))
        self.assertEqual("P2", hits[0].severity)


class LegacyDowngradeTests(unittest.TestCase):
    def test_no_registry_block_degrades_to_p2_exit_zero(self):
        legacy = "# 采集文件：旧版\n\n## 发现\n\n- 总股本4.66亿股\n\n## 冲突\n\n（无）\n"
        code, issues = run_on({"01-disclosure.md": legacy})
        self.assertEqual(0, code)
        self.assertTrue(any(i.code == "REGISTRY_BLOCK_MISSING" and i.severity == "P2" for i in issues))
        self.assertTrue(any("降级" in i.message for i in issues))

    def test_lines_without_expected_metrics_are_exempt(self):
        """full 模式 04-industry 不在预期登记线内：无登记块不报 P2；earnings 模式 04-market 在预期内：报 P2。"""
        legacy = "# 采集文件：旧版\n\n## 发现\n\n- 行业规模数据占位\n"
        code, issues = run_on({
            "01-disclosure.md": build_file([entry("revenue", "100", "万元", "FY2025", "营业收入100万元整句原文")]),
            "04-industry.md": legacy})
        self.assertFalse([i for i in issues if i.code == "REGISTRY_BLOCK_MISSING" and i.file == "04-industry.md"])
        workdir = make_workdir({"04-market.md": legacy})
        with open(os.path.join(workdir, "brief.json"), "w", encoding="utf-8") as f:
            f.write('{"mode": "earnings"}')
        code, issues = CC.run(workdir, out=os.path.join(workdir, "collision-report.txt"))
        self.assertTrue(any(i.code == "REGISTRY_BLOCK_MISSING" and i.file == "04-market.md" for i in issues))

    def test_no_registry_block_strict_exits_one(self):
        legacy = "# 采集文件：旧版\n\n## 发现\n\n- 总股本4.66亿股\n"
        code, issues = run_on({"01-disclosure.md": legacy}, strict=True)
        self.assertEqual(1, code)

    def test_report_written_and_sectioned(self):
        e1 = entry("market_cap", "100", "亿港元", "最新", "市值口径甲约100亿港元")
        e2 = entry("market_cap", "200", "亿港元", "最新", "市值口径乙约200亿港元")
        # 同文件补一个 anchor 重复条目，凑出 P2 使体检节出现
        e3 = entry("revenue", "88", "万元", "FY2025", "营业收入88万元体检节占位原文")
        workdir = make_workdir({
            "01-disclosure.md": build_file([e1, e3], duplicate_anchor="再提一次营业收入88万元体检节占位原文"),
            "02-market.md": build_file([e2]),
        })
        code, _ = CC.run(workdir)
        self.assertEqual(1, code)
        with open(os.path.join(workdir, "forensic", "collision-report.txt"), encoding="utf-8") as f:
            report = f.read()
        self.assertIn("== 对撞冲突（P1，需裁决）==", report)
        self.assertIn("== 登记块体检（P2/P3）==", report)
        self.assertIn("汇总：P1 × 1", report)


if __name__ == "__main__":
    unittest.main()
