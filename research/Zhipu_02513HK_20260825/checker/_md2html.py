# -*- coding: utf-8 -*-
"""W8 delivery: convert final report md to print-ready HTML (CJK-safe)."""
import sys
import markdown

SRC = r"C:/Users/zliu71/Documents/equity-research-workflow/research/Zhipu_02513HK_20260825/final/智谱_02513HK_个股投资研究报告_20260825.md"
DST = r"C:/Users/zliu71/Documents/equity-research-workflow/research/Zhipu_02513HK_20260825/checker/_report.html"

with open(SRC, encoding="utf-8") as f:
    text = f.read()

body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])

html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>智谱（02513.HK）个股投资研究报告</title>
<style>
@page { size: A4; margin: 17mm 13mm 18mm 13mm; }
* { box-sizing: border-box; }
body {
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
  font-size: 10pt; line-height: 1.55; color: #1b1b1b; margin: 0;
  widows: 2; orphans: 2;
}
h1 { font-size: 17pt; text-align: center; margin: 0 0 10pt 0; line-height: 1.35; }
h2 { font-size: 13.5pt; margin: 16pt 0 6pt 0; padding-bottom: 3pt;
     border-bottom: 1.2pt solid #33507a; color: #1f3a5f; page-break-after: avoid; }
h3 { font-size: 11.5pt; margin: 12pt 0 4pt 0; color: #1f3a5f; page-break-after: avoid; }
h4 { font-size: 10.5pt; margin: 9pt 0 3pt 0; page-break-after: avoid; }
p { margin: 4pt 0; text-align: justify; }
ul, ol { margin: 4pt 0 4pt 0; padding-left: 18pt; }
li { margin: 2pt 0; }
hr { border: none; border-top: 0.7pt solid #bbbbbb; margin: 10pt 0; }
blockquote {
  border-left: 3pt solid #33507a; background: #f2f5fa; color: #222;
  margin: 6pt 0; padding: 5pt 9pt; page-break-inside: avoid;
}
blockquote p { margin: 3pt 0; }
table {
  width: 100%; border-collapse: collapse; margin: 7pt 0;
  font-size: 8.4pt; line-height: 1.4;
}
th, td {
  border: 0.5pt solid #9aa4b0; padding: 2.5pt 4pt;
  vertical-align: top; word-break: break-word; overflow-wrap: anywhere;
}
th { background: #e6ebf2; font-weight: bold; }
tr { page-break-inside: avoid; }
pre {
  background: #f5f6f7; border: 0.5pt solid #cccccc; border-radius: 2pt;
  padding: 5pt 7pt; margin: 7pt 0;
  font-family: Consolas, "Courier New", monospace;
  font-size: 8.6pt; white-space: pre-wrap; word-break: break-all;
  page-break-inside: avoid;
}
code {
  font-family: Consolas, "Courier New", monospace; font-size: 88%;
  background: #f0f1f3; padding: 0 2pt; border-radius: 2pt;
}
pre code { background: none; padding: 0; font-size: 100%; }
strong { color: #000; }
</style>
</head>
<body>
__BODY__
</body>
</html>
""".replace("__BODY__", body)

with open(DST, "w", encoding="utf-8") as f:
    f.write(html)
print("HTML written:", DST, len(html), "chars")
