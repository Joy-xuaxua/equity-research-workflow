import hashlib
import importlib.util
import json
import os
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
SCRIPT = os.path.join(ROOT, "scripts", "reconcile_merge.py")
SPEC = importlib.util.spec_from_file_location("reconcile_merge", SCRIPT)
RM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RM)

F01 = "01-disclosure.md"
F02 = "02-market.md"
BODY_01 = [
    "# 采集文件：01",
    "",
    "## 发现",
    "",
    "- 月报表总股本46,562万股，与IPO基数勾稽一致",
    "- FY2025 营业收入 7.24 亿元",
    "",
    "## 指标登记",
    "```yaml",
    "- key: shares_outstanding",
    "  value: 46,562",
    "  unit: 万股",
    "  period: 最新",
    "  source: 月报表",
    "  tier: 1",
    "  ts: 2026-08-18",
    "  anchor: 月报表总股本46,562万股，与IPO基数勾稽一致",
    "```",
    "",
    "## 冲突",
    "",
    "（无）",
    "",
    "## 原文附录",
    "",
    "> 公告原文逐字引用占位。",
]
BODY_02 = [
    "# 采集文件：02",
    "",
    "## 发现",
    "",
    "- 富途口径H股总数2.41亿股快照",
    "- 收盘价1,043港元每股价快照",
    "",
    "## 冲突",
    "",
    "（无）",
]


def make_workdir(files=None):
    tmp = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmp, "collection"))
    os.makedirs(os.path.join(tmp, "forensic"))
    for fname, body in (files or {}).items():
        with open(os.path.join(tmp, "collection", fname), "w", encoding="utf-8") as f:
            f.write("\n".join(body) + "\n")
    return tmp


def write_adj(workdir, records, generated="2026-08-19 11:40"):
    adj = {"version": 1, "generated": generated, "adjudications": records}
    path = os.path.join(workdir, "forensic", "adjudications.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(adj, f, ensure_ascii=False, indent=2)
    return path


def rec(rid, status, metric, files, value=None, note=None):
    r = {"id": rid, "status": status, "metric": metric, "files": files}
    if value is not None:
        r["value"] = value
    if note is not None:
        r["note"] = note
    return r


def fread(workdir, fname):
    with open(os.path.join(workdir, "reconciled", fname), encoding="utf-8") as f:
        return f.read()


def dirhash(workdir, sub):
    h = hashlib.sha256()
    for fname in sorted(os.listdir(os.path.join(workdir, sub))):
        with open(os.path.join(workdir, sub, fname), "rb") as f:
            h.update(fname.encode())
            h.update(f.read())
    return h.hexdigest()


class AnchorTests(unittest.TestCase):
    def test_stamps_inserted_after_anchor_lines(self):
        wd = make_workdir({F01: BODY_01, F02: BODY_02})
        write_adj(wd, [
            rec("C01", "resolved", "shares_outstanding",
                [{"file": F01, "anchor": "月报表总股本46,562万股，与IPO基数勾稽一致", "side": "A"},
                 {"file": F02, "anchor": "富途口径H股总数2.41亿股快照", "side": "B"}],
                value="465,623,090", note="Tier 1 基数＋配售，富途勾稽一致"),
            rec("C09", "dual", "employees",
                [{"file": F01, "anchor": "FY2025 营业收入 7.24 亿元", "side": "neutral"}],
                value="1,094（正式雇员）‖937（员工总数）", note="口径差未核，双值保留"),
            rec("C13", "pending", "cfo",
                [{"file": F02, "anchor": "收盘价1,043港元每股价快照", "side": "neutral"}],
                note="研报原文不可得，待回源核验"),
        ])
        code, issues = RM.run(wd)
        self.assertEqual(0, code, [i.line() for i in issues])
        c01 = fread(wd, F01)
        self.assertIn("- 月报表总股本46,562万股，与IPO基数勾稽一致\n▶ 裁决@ledger C01｜采信：465,623,090｜Tier 1 基数＋配售，富途勾稽一致", c01)
        self.assertIn("- FY2025 营业收入 7.24 亿元\n▶ 双值@ledger C09｜1,094（正式雇员）‖937（员工总数）｜口径差未核，双值保留", c01)
        c02 = fread(wd, F02)
        self.assertIn("- 富途口径H股总数2.41亿股快照\n▶ 裁决@ledger C01｜采信：465,623,090｜Tier 1 基数＋配售，富途勾稽一致", c02)
        self.assertIn("▶ 悬置@ledger C13｜研报原文不可得，待回源核验", c02)
        # 登记块内的 anchor 引用行不被打戳
        self.assertNotIn("  anchor: 月报表总股本46,562万股，与IPO基数勾稽一致\n▶", c01)

    def test_registry_block_anchor_excluded_from_matching(self):
        """锚点同时出现在登记块与正文：戳只打在正文行后（登记块行不算命中）。"""
        wd = make_workdir({F01: BODY_01})
        write_adj(wd, [rec("C02", "resolved", "revenue",
                           [{"file": F01, "anchor": "FY2025 营业收入 7.24 亿元", "side": "neutral"}],
                           value="7.24 亿元", note="审计后口径")])
        code, issues = RM.run(wd)
        self.assertEqual(0, code, [i.line() for i in issues])
        lines = fread(wd, F01).splitlines()
        stamped = [i for i, l in enumerate(lines) if l.startswith("▶ ")]
        self.assertEqual(1, len(stamped))
        self.assertIn("FY2025 营业收入", lines[stamped[0] - 1])

    def test_anchor_not_found_is_p1_partial_write(self):
        wd = make_workdir({F01: BODY_01, F02: BODY_02})
        write_adj(wd, [
            rec("C01", "resolved", "shares_outstanding",
                [{"file": F01, "anchor": "月报表总股本46,562万股，与IPO基数勾稽一致", "side": "A"}],
                value="465,623,090", note="Tier 1"),
            rec("C99", "pending", "cfo",
                [{"file": F02, "anchor": "不存在的锚点文本占位符xyz", "side": "neutral"}]),
        ])
        code, issues = RM.run(wd)
        self.assertEqual(1, code)
        self.assertTrue(any(i.code == "ANCHOR_NOT_FOUND" and i.severity == "P1" for i in issues))
        # 部分成功仍落盘
        self.assertIn("▶ 裁决@ledger C01", fread(wd, F01))
        self.assertTrue(os.path.isfile(os.path.join(wd, "reconciled", F02)))

    def test_anchor_ambiguous_is_p1(self):
        body = ["# 采集文件：02", "", "## 发现", "", "- 总市值约100亿港元口径甲", "- 重复一次总市值约100亿港元口径甲的表述"]
        wd = make_workdir({F02: body})
        write_adj(wd, [rec("C05", "resolved", "market_cap",
                           [{"file": F02, "anchor": "总市值约100亿港元口径甲", "side": "A"}], value="100 亿港元")])
        code, issues = RM.run(wd)
        self.assertEqual(1, code)
        self.assertTrue(any(i.code == "ANCHOR_AMBIGUOUS" for i in issues))

    def test_target_file_missing_is_p1(self):
        wd = make_workdir({F01: BODY_01})
        write_adj(wd, [rec("C07", "dual", "market_cap",
                           [{"file": "04-industry.md", "anchor": "某锚点文本至少八字以上", "side": "neutral"}])])
        code, issues = RM.run(wd)
        self.assertEqual(1, code)
        self.assertTrue(any(i.code == "TARGET_FILE_MISSING" for i in issues))


class SchemaTests(unittest.TestCase):
    def test_bad_version_no_rebuild(self):
        wd = make_workdir({F01: BODY_01})
        path = os.path.join(wd, "forensic", "adjudications.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": 2, "generated": "2026-08-19 11:40", "adjudications": []}, f)
        code, issues = RM.run(wd)
        self.assertEqual(1, code)
        self.assertTrue(any(i.code == "ADJUDICATIONS_SCHEMA" for i in issues))
        self.assertFalse(os.path.isdir(os.path.join(wd, "reconciled")))

    def test_bad_status_and_short_anchor(self):
        wd = make_workdir({F01: BODY_01})
        write_adj(wd, [rec("C01", "wrong", "x", [{"file": F01, "anchor": "短", "side": "A"}])])
        code, issues = RM.run(wd)
        self.assertEqual(1, code)
        self.assertTrue(any("status" in i.message for i in issues))

    def test_empty_adjudications_rebuild_only(self):
        wd = make_workdir({F01: BODY_01, F02: BODY_02})
        write_adj(wd, [])
        code, issues = RM.run(wd)
        self.assertEqual(0, code)
        for fname in (F01, F02):
            text = fread(wd, fname)
            self.assertIn("【对账后副本】", text)
            self.assertEqual([], [l for l in text.splitlines() if l.startswith("▶ ")])


class IdempotencyTests(unittest.TestCase):
    def test_rerun_byte_identical(self):
        wd = make_workdir({F01: BODY_01, F02: BODY_02})
        write_adj(wd, [
            rec("C01", "resolved", "shares_outstanding",
                [{"file": F01, "anchor": "月报表总股本46,562万股，与IPO基数勾稽一致", "side": "A"}],
                value="465,623,090", note="Tier 1 基数＋配售"),
        ])
        code1, _ = RM.run(wd)
        self.assertEqual(0, code1)
        first = dirhash(wd, "reconciled")
        code2, _ = RM.run(wd)
        self.assertEqual(0, code2)
        self.assertEqual(first, dirhash(wd, "reconciled"))
        # 戳只出现一次（重跑不叠加）
        self.assertEqual(1, fread(wd, F01).count("▶ 裁决@ledger C01"))

    def test_strip_appendix(self):
        wd = make_workdir({F01: BODY_01})
        write_adj(wd, [])
        code, _ = RM.run(wd, strip=True)
        self.assertEqual(0, code)
        self.assertNotIn("原文附录", fread(wd, F01))
        self.assertNotIn("公告原文逐字引用占位", fread(wd, F01))
        # 不 strip 时保留
        code, _ = RM.run(wd, strip=False)
        self.assertEqual(0, code)
        self.assertIn("公告原文逐字引用占位", fread(wd, F01))


class ReadOnlyTests(unittest.TestCase):
    def test_collection_untouched(self):
        wd = make_workdir({F01: BODY_01, F02: BODY_02})
        write_adj(wd, [
            rec("C01", "resolved", "shares_outstanding",
                [{"file": F01, "anchor": "月报表总股本46,562万股，与IPO基数勾稽一致", "side": "A"}],
                value="465,623,090", note="Tier 1"),
        ])
        before = dirhash(wd, "collection")
        RM.run(wd)
        self.assertEqual(before, dirhash(wd, "collection"))

    def test_header_contains_fingerprint(self):
        wd = make_workdir({F01: BODY_01})
        adj_path = write_adj(wd, [
            rec("C01", "pending", "cfo", [{"file": F01, "anchor": "月报表总股本46,562万股，与IPO基数勾稽一致", "side": "neutral"}]),
        ])
        with open(adj_path, encoding="utf-8") as f:
            adj = json.load(f)
        RM.run(wd)
        text = fread(wd, F01)
        self.assertIn(f"sha256:{RM.canonical_sha8(adj)}", text)
        self.assertIn("生成于 2026-08-19 11:40", text)


if __name__ == "__main__":
    unittest.main()
