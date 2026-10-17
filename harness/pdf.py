"""md → HTML → PDF via headless Edge/Chrome (the deliverer body's fallback ④, the one verified on this
machine), then verification with pypdf: non-zero pages and the CJK title extractable as text.
Falls back to pandoc / wkhtmltopdf when present; returns None when no toolchain exists (→ .md only).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

import markdown

from .util import read, write

CSS = """
@page { size: A4; margin: 16mm 12mm 14mm 12mm; }
* { box-sizing: border-box; }
body { font-family: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', sans-serif;
       font-size: 10pt; line-height: 1.65; color: #111; margin: 0; }
h1 { font-size: 17pt; line-height: 1.4; margin: 0 0 6pt 0; }
h2 { font-size: 13.5pt; margin: 14pt 0 6pt 0; border-bottom: 1.2pt solid #333; padding-bottom: 3pt; break-before: page; }
h2:first-of-type { break-before: auto; }
h3 { font-size: 11.5pt; margin: 10pt 0 4pt 0; }
h4 { font-size: 10.5pt; margin: 8pt 0 3pt 0; }
p { margin: 4pt 0; text-align: justify; }
blockquote { margin: 6pt 0; padding: 6pt 10pt; border-left: 3pt solid #888; background: #f5f5f5; }
blockquote p { margin: 3pt 0; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; font-size: 7.6pt; line-height: 1.45; }
th, td { border: 0.6pt solid #888; padding: 2.5pt 4pt; vertical-align: top; word-wrap: break-word; overflow-wrap: anywhere; }
th { background: #ececec; font-weight: bold; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
pre { font-family: Consolas, 'Cascadia Mono', 'Microsoft YaHei', monospace; font-size: 7.2pt; line-height: 1.35;
      background: #f7f7f7; border: 0.6pt solid #ccc; padding: 5pt; white-space: pre-wrap; break-inside: avoid; }
code { font-family: Consolas, 'Microsoft YaHei', monospace; font-size: 8.6pt; background: #f0f0f0; padding: 0 2pt; }
pre code { font-size: 7.2pt; background: none; padding: 0; }
hr { border: none; border-top: 0.8pt solid #999; margin: 8pt 0; }
ol, ul { margin: 4pt 0; padding-left: 18pt; }
li { margin: 2pt 0; }
"""


def _browser() -> Optional[str]:
    cands = [
        os.environ.get("HARNESS_BROWSER", ""),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        shutil.which("msedge") or "", shutil.which("google-chrome") or "", shutil.which("chromium") or "",
    ]
    return next((c for c in cands if c and Path(c).exists()), None)


def to_html(md_path: Path, html_path: Path, title: str, lang: str) -> None:
    body = markdown.markdown(read(md_path), extensions=["tables", "fenced_code", "sane_lists"])
    write(html_path, f'<!DOCTYPE html><html lang="{"zh-CN" if lang == "zh" else "en"}"><head><meta charset="utf-8">'
                     f"<title>{title}</title><style>{CSS}</style></head><body>{body}</body></html>")


def verify(pdf_path: Path, probe: str) -> Tuple[bool, str]:
    from pypdf import PdfReader
    try:
        reader = PdfReader(str(pdf_path))
        pages = len(reader.pages)
        first = reader.pages[0].extract_text() if pages else ""
    except Exception as exc:  # noqa: BLE001 — any parse failure means the PDF is not deliverable
        return False, f"PDF 解析失败：{exc}"
    compact = "".join(first.split())
    ok = pages > 0 and probe[:4] in compact
    return ok, f"{pages} 页；首页文本抽取{'含' if ok else '不含'}标题「{probe[:4]}」"


def convert(md_path: Path, pdf_path: Path, html_path: Path, title: str, lang: str = "zh") -> Tuple[Optional[str], str]:
    """Returns (toolchain used or None, verification note)."""
    to_html(md_path, html_path, title, lang)
    browser = _browser()
    if browser:
        subprocess.run([browser, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri()],
                       capture_output=True, timeout=300)
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            ok, note = verify(pdf_path, title)
            if ok:
                return f"headless {Path(browser).stem}", note
    if shutil.which("pandoc"):
        subprocess.run(["pandoc", str(md_path), "-o", str(pdf_path), "--pdf-engine=xelatex",
                        "-V", "CJKmainfont=Microsoft YaHei"], capture_output=True, timeout=600)
        if pdf_path.exists():
            ok, note = verify(pdf_path, title)
            if ok:
                return "pandoc", note
    if shutil.which("wkhtmltopdf"):
        subprocess.run(["wkhtmltopdf", str(html_path), str(pdf_path)], capture_output=True, timeout=600)
        if pdf_path.exists():
            ok, note = verify(pdf_path, title)
            if ok:
                return "wkhtmltopdf", note
    return None, "无可用 PDF 工具链（或转换后校验失败），降级交付 .md"
