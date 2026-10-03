# -*- coding: utf-8 -*-
"""
Markdown → HTML → PDF
首选：Word（中文排版/文本层最完美，支持页码页脚）
兜底：Edge/Chrome 无头打印（若 Word 不可用）
用法：
    py make_pdf.py                                  # 默认渲染《人声合成与播放全流程.md》
    py make_pdf.py 文件.md [输出.pdf] [封面标题] [封面副标题]
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
import markdown

BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

EMOJI = {
    "🔬": "[实验] ", "🎧": "[听] ", "💡": "[提示] ", "📌": "[要点] ",
    "⚠️": "[注意] ", "🎯": "[目标] ", "🧠": "[思考] ", "⭐": "★",
    "🔑": "[核心] ", "📝": "[例题] ", "📖": "[书] ",
    "✅": "√", "❌": "×",
}

CSS = """\
body {
  font-family: "Microsoft YaHei", "SimSun", sans-serif;
  font-size: 10.5pt; line-height: 1.6; color: #1a1a1a;
}
h1 {
  font-size: 16.5pt; color: #0e3a5d; background-color: #eef4f9;
  border-bottom: 2pt solid #0e3a5d; padding: 6pt 10pt;
  margin-top: 18pt; page-break-before: always;
}
h2 {
  font-size: 13.5pt; color: #145a86;
  border-left: 4pt solid #145a86; padding-left: 8pt;
}
h3 { font-size: 11.5pt; color: #2c3e50; }
p { margin: 5pt 0; }
pre {
  background-color: #f6f8fa; border: 0.75pt solid #d0d7de;
  padding: 8pt; font-size: 8.5pt; line-height: 1.4;
  font-family: Consolas, "Microsoft YaHei", monospace; margin: 7pt 0;
}
code {
  font-family: Consolas, "Microsoft YaHei", monospace;
  background-color: #eef1f4; font-size: 9pt;
}
pre code { background-color: transparent; }
table { width: 100%; border-collapse: collapse; font-size: 9pt; margin: 8pt 0; }
th, td { border: 0.75pt solid #8a97a5; padding: 3.5pt 6pt; }
th { background-color: #e8f0f7; }
blockquote {
  border-left: 4pt solid #5b9bd5; background-color: #f2f7fb;
  margin: 8pt 0; padding: 5pt 12pt; color: #2c3e50;
}
hr { border: none; border-top: 1pt solid #b0b8c0; }
.cover { text-align: center; margin-top: 90pt; page-break-after: always; }
.cover p { margin: 0; }
"""

DEFAULT_TITLE = "人声合成与播放全流程详解"
DEFAULT_SUB = "Source–Filter 模型深度讲义<br/>声源 × 声道 → 波形 → 文件 → 扬声器"


def cover_html(title: str, subtitle: str) -> str:
    lines = subtitle.split("<br/>")
    sub_p = "".join(
        f'<p style="font-size:13pt; color:#555; margin-top:18pt;">{ln}</p>'
        for ln in lines
    )
    return f"""
<div class="cover">
  <p style="font-size:24pt; font-weight:bold; color:#0e3a5d;">{title}</p>
  {sub_p}
  <p style="font-size:10pt; color:#999; margin-top:60pt;">配套教程 · 2026-10-03</p>
  <p style="font-size:10pt; color:#999;">Python / numpy / scipy / ffmpeg</p>
</div>"""


def _free_target(p: Path) -> Path:
    """确保目标可写：能删就删；被占用则换备用名（v2 → 时间戳）"""
    import time
    try:
        if p.exists():
            os.remove(p)
        return p
    except OSError:
        for name in (p.stem + "_v2", p.stem + "_" + time.strftime("%H%M%S")):
            alt = p.with_name(name + p.suffix)
            try:
                if alt.exists():
                    os.remove(alt)
                return alt
            except OSError:
                continue
        return p


def _exported_changed(p: Path, before: tuple) -> bool:
    """导出后文件是否真的变了（防止旧文件假阳性）"""
    if not p.exists():
        return False
    return (p.stat().st_size, p.stat().st_mtime_ns) != before


def md_to_html(text: str, title: str, subtitle: str) -> str:
    text = re.sub(r"[^\u0000-\uFFFF]", "", text)
    for k, v in EMOJI.items():
        text = text.replace(k, v)
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    # 图片统一限宽：Word 按 width 等比缩放，防止 150dpi 原始尺寸溢出页面
    body = re.sub(
        r'<img\b([^>]*?)(/?)>',
        lambda m: '<img width="550" %s%s>' % (m.group(1), m.group(2)),
        body,
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{CSS}</style></head>
<body>{cover_html(title, subtitle)}{body}</body></html>"""


def pdf_via_word(html_path: Path, pdf_path: Path) -> bool:
    """Word 打开 HTML 并另存为 PDF（中文文本层完美、可加页码）"""
    try:
        import win32com.client as win32
        import pythoncom
    except ImportError:
        return False
    word = None
    doc = None
    before = (pdf_path.stat().st_size, pdf_path.stat().st_mtime_ns) if pdf_path.exists() else None
    try:
        word = win32.DispatchEx('Word.Application')
        word.Visible = False
        doc = word.Documents.Open(str(html_path), ReadOnly=False, AddToRecentFiles=False)
        ps = doc.PageSetup
        ps.PaperSize = 7                      # wdPaperA4
        ps.TopMargin = 45.4                   # 1.6cm（CentimetersToPoints 在本机 E_FAIL，直接用 points）
        ps.BottomMargin = 51.0                # 1.8cm
        ps.LeftMargin = 42.5                  # 1.5cm
        ps.RightMargin = 42.5                 # 1.5cm
        for sec in doc.Sections:
            sec.Footers(1).PageNumbers.Add(PageNumberAlignment=2)  # 右下角页码
        doc.ExportAsFixedFormat(OutputFileName=str(Path(pdf_path).resolve()),
                                ExportFormat=17)          # wdExportFormatPDF（SaveAs2 在本机类型不匹配，换用导出接口）
        doc.Close(0)
        doc = None
        word.Quit()
        word = None
        return _exported_changed(pdf_path, before)
    except Exception as e:
        print(f"[Word 方案失败] {e}")
        return False
    finally:
        try:
            if doc is not None:
                doc.Close(0)
        except Exception:
            pass
        try:
            if word is not None:
                word.Quit()
        except Exception:
            pass


def pdf_via_browser(html_path: Path, pdf_path: Path) -> bool:
    browser = next((p for p in BROWSER_CANDIDATES if Path(p).exists()), None)
    if browser is None:
        print("错误：未找到 Edge/Chrome")
        return False
    before = (pdf_path.stat().st_size, pdf_path.stat().st_mtime_ns) if pdf_path.exists() else None
    profile = Path(tempfile.gettempdir()) / "edge_pdf_profile"
    cmd = [browser, "--headless=new", "--disable-gpu",
           f"--user-data-dir={profile}", "--no-pdf-header-footer",
           f"--print-to-pdf={pdf_path}", html_path.as_uri()]
    try:
        subprocess.run(cmd, check=True, timeout=120,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.SubprocessError:
        return False
    return _exported_changed(pdf_path, before)


def main() -> int:
    args = sys.argv[1:]
    src = Path(args[0]) if args else Path("人声合成与播放全流程.md")
    out = Path(args[1]) if len(args) > 1 else src.with_suffix(".pdf")
    pick = _free_target(out)
    if pick != out:
        print(f"[提示] {out.name} 正被其他程序占用（PDF 阅读器开着？），输出到：{pick.name}")
    out = pick
    title = args[2] if len(args) > 2 else DEFAULT_TITLE
    subtitle = args[3] if len(args) > 3 else DEFAULT_SUB

    html = md_to_html(src.read_text(encoding="utf-8"), title, subtitle)
    tmp = Path.cwd() / f"voice_tmp_{os.getpid()}.html"   # 与 figs/ 同目录，相对路径图片才能被 Word 解析
    tmp.write_text(html, encoding="utf-8")

    ok = False
    try:
        ok = pdf_via_word(tmp, out)
        engine = "Word"
        if not ok:
            ok = pdf_via_browser(tmp, out)
            engine = "Edge/Chrome（兜底）"
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass

    if not ok:
        print("PDF 生成失败")
        return 1
    print(f"PDF 已生成（{engine}）：{out}  （{out.stat().st_size // 1024} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())