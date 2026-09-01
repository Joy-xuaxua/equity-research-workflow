# -*- coding: utf-8 -*-
"""W8 内部转换脚本：final/*.md -> HTML（YaHei 字体、表格防溢出）-> Edge 无头 PDF。"""
import subprocess
import sys
from pathlib import Path

import markdown

WORKDIR = Path(r"C:/Users/zliu71/Documents/equity-research-workflow/research/Zhipu_02513HK_20260901")
MD = WORKDIR / "final" / "智谱_02513HK_2026财年中期_财报深度分析_20260901.md"
HTML = WORKDIR / "checker" / "report-final.html"
PDF = WORKDIR / "final" / "智谱_02513HK_2026财年中期_财报深度分析_20260901.pdf"
EDGE = r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"

CSS = """
@page { size: A4; margin: 14mm 11mm 16mm 11mm; }
* { box-sizing: border-box; }
body {
  font-family: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', sans-serif;
  font-size: 9.5pt; line-height: 1.55; color: #1a1a1a; margin: 0;
  overflow-wrap: anywhere;
}
h1 { font-size: 17pt; margin: 0 0 10pt; line-height: 1.35; }
h2 { font-size: 13pt; margin: 16pt 0 6pt; border-bottom: 1.5pt solid #333; padding-bottom: 3pt; page-break-after: avoid; }
h3 { font-size: 11pt; margin: 12pt 0 4pt; page-break-after: avoid; }
h4 { font-size: 10pt; margin: 10pt 0 3pt; page-break-after: avoid; }
p { margin: 4pt 0; }
ul, ol { margin: 4pt 0 4pt 0; padding-left: 16pt; }
li { margin: 2pt 0; }
table {
  border-collapse: collapse; width: 100%; margin: 6pt 0;
  font-size: 8pt; table-layout: auto; page-break-inside: auto;
}
th, td {
  border: 0.5pt solid #999; padding: 2.5pt 4pt; vertical-align: top;
  text-align: left; overflow-wrap: anywhere; word-break: break-word;
}
th { background: #efefef; font-weight: bold; }
tr { page-break-inside: avoid; }
blockquote {
  margin: 6pt 0; padding: 5pt 9pt; border-left: 3pt solid #888;
  background: #f6f6f6; font-size: 9pt;
}
blockquote p { margin: 3pt 0; }
code, pre {
  font-family: Consolas, 'Microsoft YaHei', monospace;
}
code { font-size: 8.5pt; background: #f0f0f0; padding: 0 2pt; }
pre {
  font-size: 8pt; background: #f4f4f4; border: 0.5pt solid #ccc;
  padding: 5pt; overflow: visible; white-space: pre; line-height: 1.35;
  page-break-inside: avoid;
}
pre code { background: none; padding: 0; font-size: 8pt; }
hr { border: none; border-top: 0.75pt solid #bbb; margin: 12pt 0; }
strong { font-weight: bold; }
a { color: inherit; text-decoration: none; }
"""

def main():
    text = MD.read_text(encoding="utf-8")
    body = markdown.markdown(
        text, extensions=["tables", "fenced_code", "sane_lists"]
    )
    html = (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<title>智谱 02513.HK FY2026 H1 财报深度分析</title>"
        f"<style>{CSS}</style></head><body>{body}</body></html>"
    )
    HTML.write_text(html, encoding="utf-8")

    cmd = [
        EDGE, "--headless", "--disable-gpu", "--no-pdf-header-footer",
        f"--print-to-pdf={PDF}",
        HTML.as_uri(),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    print("edge rc:", r.returncode)
    if r.stderr:
        print("edge stderr tail:", r.stderr.strip()[-400:])
    print("pdf exists:", PDF.exists(), "size:", PDF.stat().st_size if PDF.exists() else 0)

    # 验证：页数非零 + CJK 文本抽查
    from pypdf import PdfReader
    reader = PdfReader(str(PDF))
    n = len(reader.pages)
    print("pages:", n)
    sample = ""
    for i in (0, n // 2, n - 1):
        sample += reader.pages[i].extract_text() or ""
    for probe in ["智谱", "财报可信度", "显著高估", "附录", "免责声明"]:
        print(f"contains {probe!r}:", probe in sample or probe in (reader.pages[0].extract_text() or ""))
    if n == 0:
        sys.exit(2)

if __name__ == "__main__":
    main()
