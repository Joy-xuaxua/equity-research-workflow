# -*- coding: utf-8 -*-
"""md -> HTML (CJK 字体/表格防溢出 CSS) -> headless Edge 打印 PDF。内部留档脚本。"""
import io
import subprocess
import sys
import os

import markdown

SRC = sys.argv[1]
HTML_OUT = sys.argv[2]
PDF_OUT = sys.argv[3]
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

CSS = """
@page { size: A4; margin: 16mm 12mm 16mm 12mm; }
html { -webkit-print-color-adjust: exact; }
body {
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
  font-size: 9.5pt; line-height: 1.55; color: #1a1a1a; margin: 0;
}
h1 { font-size: 17pt; text-align: center; margin: 0 0 10pt; }
h2 { font-size: 13pt; margin: 16pt 0 6pt; border-bottom: 1.5pt solid #333; padding-bottom: 2pt; }
h3 { font-size: 11pt; margin: 12pt 0 4pt; }
h4 { font-size: 10pt; margin: 10pt 0 3pt; }
p { margin: 4pt 0; text-align: justify; }
table {
  border-collapse: collapse; width: 100%; margin: 6pt 0;
  font-size: 8pt; table-layout: auto;
}
th, td {
  border: 0.5pt solid #999; padding: 2.5pt 4pt; vertical-align: top;
  word-break: break-word; overflow-wrap: anywhere; max-width: 260pt;
}
th { background: #eef1f4; font-weight: bold; }
tr { page-break-inside: avoid; }
blockquote {
  margin: 8pt 0; padding: 6pt 10pt; border-left: 3pt solid #2b5b84;
  background: #f2f6fa; page-break-inside: avoid;
}
blockquote p { margin: 3pt 0; }
code, pre {
  font-family: Consolas, "Microsoft YaHei", monospace;
}
code { font-size: 8.5pt; background: #f4f4f4; padding: 0 2pt; }
pre {
  font-size: 8pt; background: #f7f7f7; border: 0.5pt solid #ccc;
  padding: 6pt; overflow: visible; white-space: pre-wrap;
  page-break-inside: avoid; line-height: 1.35;
}
hr { border: none; border-top: 0.75pt solid #bbb; margin: 12pt 0; }
ul, ol { margin: 4pt 0 4pt 18pt; padding: 0; }
li { margin: 2pt 0; }
strong { color: #000; }
"""

def main():
    with io.open(SRC, encoding="utf-8") as f:
        text = f.read()
    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
        output_format="html5",
    )
    html = ("<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<title>智谱（02513.HK）个股投资研究报告</title>"
            f"<style>{CSS}</style></head><body>{body}</body></html>")
    with io.open(HTML_OUT, "w", encoding="utf-8") as f:
        f.write(html)
    url = "file:///" + os.path.abspath(HTML_OUT).replace("\\", "/")
    cmd = [EDGE, "--headless", "--disable-gpu", "--no-pdf-header-footer",
           f"--print-to-pdf={os.path.abspath(PDF_OUT)}", url]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    ok = os.path.isfile(os.path.abspath(PDF_OUT)) and os.path.getsize(os.path.abspath(PDF_OUT)) > 10000
    print("edge rc=", r.returncode, "| pdf exists:", ok,
          "| size:", os.path.getsize(os.path.abspath(PDF_OUT)) if ok else 0)
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
