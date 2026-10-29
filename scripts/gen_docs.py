#!/usr/bin/env python3
"""把 docs/ 里的 Markdown 转成带排版的 .docx（行业分析 / 报价单）。

为什么要生成一个脚本而不是手工排一遍 Word：
- 报价单改一次就要重排一次，脚本能保证格式始终一致；
- README / 方案里的数字和这里同源，避免"两份文件两个数字"。

用法：
    pip install python-docx
    python3 scripts/gen_docs.py

表格支持：Markdown 的表格会转成 Word 表格，单元格内的 **粗体** 会生效。
代码块保持等宽字体原样段落。
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")

FONT_BODY = "微软雅黑"
FONT_MONO = "Consolas"
BLUE = "1F4E79"


def add_cell_bold(par, text: str):
    """解析 **粗体** 片段，其余作为普通文本。"""
    for kind, chunk in _split_bold(text):
        run = par.add_run(chunk)
        run.bold = (kind == "b")


def _split_bold(text: str):
    out = []
    pos = 0
    for m in re.finditer(r"\*\*(.+?)\*\*", text):
        if m.start() > pos:
            out.append(("n", text[pos:m.start()]))
        out.append(("b", m.group(1)))
        pos = m.end()
    if pos < len(text):
        out.append(("n", text[pos:]))
    return out


def convert(md_path: str, docx_path: str, title: str) -> int:
    try:
        from docx import Document
        from docx.enum.table import WD_TABLE_ALIGNMENT
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
        from docx.shared import Pt, RGBColor
    except ImportError:
        print("需要 python-docx：pip install python-docx", file=sys.stderr)
        return 1

    lines = open(md_path, encoding="utf-8").read().splitlines()
    doc = Document()

    # 页面默认字体
    style = doc.styles["Normal"]
    style.font.name = FONT_BODY
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_BODY)

    # 封面标题
    h = doc.add_heading(title, level=0)
    for r in h.runs:
        r.font.color.rgb = RGBColor.from_string(BLUE)
        r.font.name = FONT_BODY
        r._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_BODY)

    i = 0
    while i < len(lines):
        raw = lines[i]
        s = raw.rstrip()

        if not s:
            i += 1
            continue

        # Markdown 一级标题用作封面标题，其余降级
        if s.startswith("# "):
            i += 1
            continue

        # 代码块
        if s.startswith("```"):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            code = "\n".join(buf)
            if code.strip():
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Pt(12)
                p.paragraph_format.space_after = Pt(6)
                run = p.add_run(code)
                run.font.name = FONT_MONO
                run.font.size = Pt(9)
                run._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_MONO)
            continue

        # 标题
        m = re.match(r"^(#{2,6})\s+(.*)$", s)
        if m:
            level = min(len(m.group(1)) - 1, 4)
            head = doc.add_heading(m.group(2).replace("**", ""), level=level)
            for r in head.runs:
                r.font.name = FONT_BODY
                r._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_BODY)
                r.font.color.rgb = RGBColor.from_string(BLUE)
            i += 1
            continue

        # 表格
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            header = [c.strip() for c in s.strip("|").split("|")]
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if len(cells) < len(header):
                    cells += [""] * (len(header) - len(cells))
                rows.append(cells[:len(header)])
                i += 1
            table = doc.add_table(rows=1, cols=len(header))
            table.style = "Light Grid Accent 1"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            hdr = table.rows[0].cells
            for j, name in enumerate(header):
                hdr[j].text = ""
                add_cell_bold(hdr[j].paragraphs[0], name)
                for r in hdr[j].paragraphs[0].runs:
                    r.bold = True
                    r.font.size = Pt(9)
            for cells in rows:
                row = table.add_row().cells
                for j, val in enumerate(cells):
                    row[j].text = ""
                    par = row[j].paragraphs[0]
                    add_cell_bold(par, val)
                    for r in par.runs:
                        r.font.size = Pt(9)
            doc.add_paragraph()
            continue

        # 分隔线
        if s.startswith("---"):
            i += 1
            continue

        # 引用块
        if s.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                buf.append(lines[i].lstrip()[1:].strip())
                i += 1
            text = " ".join(x for x in buf if x)
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Pt(18)
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(8)
            for kind, chunk in _split_bold(text):
                run = p.add_run(chunk)
                run.italic = True
                run.bold = (kind == "b")
                run.font.size = Pt(10)
                run.font.color.rgb = RGBColor.from_string("44546A")
            continue

        # 列表
        if re.match(r"^[-*]\s+", s) or re.match(r"^\d+\.\s+", s):
            ordered = bool(re.match(r"^\d+\.\s+", s))
            text = re.sub(r"^([-*]|\d+\.)\s+", "", s)
            p = doc.add_paragraph(style="List Number" if ordered else "List Bullet")
            add_cell_bold(p, text)
            i += 1
            continue

        # 普通段落
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        add_cell_bold(p, s)
        i += 1

    doc.add_paragraph()
    foot = doc.add_paragraph()
    foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = foot.add_run("本文件由 scripts/gen_docs.py 从 Markdown 自动生成，勿手工编辑。")
    run.font.size = Pt(8.5)
    run.font.color.rgb = RGBColor.from_string("808080")

    os.makedirs(os.path.dirname(docx_path), exist_ok=True)
    doc.save(docx_path)
    print(f"{os.path.relpath(md_path, ROOT)} -> {os.path.relpath(docx_path, ROOT)}")
    return 0


def main() -> int:
    jobs = [
        ("行业分析.md", "行业分析.docx", "门诊预约与分诊赛道 · 行业分析"),
        ("报价单.md", "报价单.docx", "门诊预约与分诊协作助手 · 报价单"),
    ]
    rc = 0
    for md, docx, title in jobs:
        src = os.path.join(DOCS, md)
        if not os.path.exists(src):
            print(f"跳过（不存在）：{src}", file=sys.stderr)
            continue
        rc |= convert(src, os.path.join(DOCS, docx), title)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
