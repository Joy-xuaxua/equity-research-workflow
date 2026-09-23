# -*- coding: utf-8 -*-
"""md -> HTML -> PDF (headless Edge). Internal build script for W8 delivery."""
import markdown, os, sys

WORKDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD = os.path.join(WORKDIR, 'final', '安莉芳控股_1388.HK_个股投资研究报告_20260923.md')
HTML = os.path.join(WORKDIR, 'checker', 'report_final.html')

src = open(MD, encoding='utf-8').read()
body = markdown.markdown(src, extensions=['tables', 'fenced_code', 'sane_lists'])

css = """
@page { size: A4; margin: 16mm 12mm 14mm 12mm; }
* { box-sizing: border-box; }
body { font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
       font-size: 10pt; line-height: 1.65; color: #111; margin: 0; }
h1 { font-size: 17pt; line-height: 1.4; margin: 0 0 6pt 0; }
h2 { font-size: 13.5pt; margin: 14pt 0 6pt 0; border-bottom: 1.2pt solid #333;
     padding-bottom: 3pt; break-before: page; }
h2:first-of-type { break-before: auto; }
h3 { font-size: 11.5pt; margin: 10pt 0 4pt 0; }
h4 { font-size: 10.5pt; margin: 8pt 0 3pt 0; }
p { margin: 4pt 0; text-align: justify; }
blockquote { margin: 6pt 0; padding: 6pt 10pt; border-left: 3pt solid #888;
             background: #f5f5f5; }
blockquote p { margin: 3pt 0; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; font-size: 7.6pt;
        line-height: 1.45; }
th, td { border: 0.6pt solid #888; padding: 2.5pt 4pt; vertical-align: top;
         word-wrap: break-word; overflow-wrap: anywhere; }
th { background: #ececec; font-weight: bold; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
pre { font-family: Consolas, 'Cascadia Mono', 'Microsoft YaHei', monospace;
      font-size: 7.2pt; line-height: 1.35; background: #f7f7f7; border: 0.6pt solid #ccc;
      padding: 5pt; white-space: pre; overflow: visible; break-inside: avoid; }
code { font-family: Consolas, 'Microsoft YaHei', monospace; font-size: 8.6pt;
       background: #f0f0f0; padding: 0 2pt; }
pre code { font-size: 7.2pt; background: none; padding: 0; }
hr { border: none; border-top: 0.8pt solid #999; margin: 8pt 0; }
ol, ul { margin: 4pt 0; padding-left: 18pt; }
li { margin: 2pt 0; }
strong { font-weight: bold; }
"""

html = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<title>安莉芳控股（1388.HK）个股投资研究报告</title>'
        f'<style>{css}</style></head><body>{body}</body></html>')
open(HTML, 'w', encoding='utf-8').write(html)
print('HTML WROTE', HTML, len(html), 'chars')
