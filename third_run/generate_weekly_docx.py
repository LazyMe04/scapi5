#!/usr/bin/env python3
"""Convert a Markdown report into a formatted Word document.

Usage:  python generate_weekly_docx.py <input.md> <output.docx>
"""
import re
import sys

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor, Inches

MONO = "Consolas"
CODE_BG = RGBColor(0xF2, 0xF2, 0xF2)


def add_inline(paragraph, text, base_bold=False):
    """Render inline **bold** and `code` markers as separate runs."""
    # Split on bold spans and code spans while keeping delimiters.
    pattern = re.compile(r"(\*\*.+?\*\*|`[^`]+?`)")
    for chunk in pattern.split(text):
        if not chunk:
            continue
        if chunk.startswith("**") and chunk.endswith("**") and len(chunk) > 4:
            run = paragraph.add_run(chunk[2:-2])
            run.bold = True
        elif chunk.startswith("`") and chunk.endswith("`") and len(chunk) > 2:
            run = paragraph.add_run(chunk[1:-1])
            run.font.name = MONO
            run.font.size = Pt(9.5)
            run.font.color.rgb = RGBColor(0x8B, 0x1A, 0x1A)
        else:
            run = paragraph.add_run(chunk)
            run.bold = base_bold
    return paragraph


def style_document(doc):
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(8)
    normal.paragraph_format.line_spacing = 1.15
    for name, size, r, g, b in (
        ("Title", 22, 0x1A, 0x1A, 0x1A),
        ("Heading 1", 15, 0x1F, 0x3B, 0x63),
        ("Heading 2", 12.5, 0x1F, 0x3B, 0x63),
        ("Heading 3", 11.5, 0x33, 0x44, 0x55),
    ):
        try:
            st = doc.styles[name]
        except KeyError:
            continue
        st.font.name = "Calibri"
        st.font.size = Pt(size)
        st.font.color.rgb = RGBColor(r, g, b)


def split_row(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_divider(line):
    cells = split_row(line)
    return all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c)


def add_table(doc, rows):
    header, body = rows[0], rows[1:]
    table = doc.add_table(rows=1, cols=len(header))
    table.style = "Light Grid Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for cell, text in zip(table.rows[0].cells, header):
        cell.text = ""
        add_inline(cell.paragraphs[0], text, base_bold=True)
    for row in body:
        cells = table.add_row().cells
        for cell, text in zip(cells, row):
            cell.text = ""
            add_inline(cell.paragraphs[0], text)
    doc.add_paragraph()


def convert(md_path, out_path):
    with open(md_path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    doc = Document()
    style_document(doc)
    for section in doc.sections:
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

    i = 0
    in_code = False
    code_buf = []
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Fenced code block
        if stripped.startswith("```"):
            if in_code:
                p = doc.add_paragraph()
                run = p.add_run("\n".join(code_buf))
                run.font.name = MONO
                run.font.size = Pt(9)
                run.font.color.rgb = RGBColor(0x22, 0x44, 0x22)
                p.paragraph_format.left_indent = Inches(0.3)
                code_buf = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # Horizontal rule
        if stripped in ("---", "***", "___"):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(10)
            run = p.add_run("_" * 78)
            run.font.color.rgb = RGBColor(0xBB, 0xBB, 0xBB)
            i += 1
            continue

        # Table
        if stripped.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not is_divider(lines[i]):
                    rows.append(split_row(lines[i]))
                i += 1
            if rows:
                add_table(doc, rows)
            continue

        # Headings
        m = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if m:
            level, text = len(m.group(1)), m.group(2)
            if level == 1:
                p = doc.add_paragraph()
                add_inline(p, text)
                for run in p.runs:
                    run.bold = True
                    run.font.size = Pt(19)
                    run.font.color.rgb = RGBColor(0x14, 0x14, 0x14)
            else:
                style = "Heading %d" % min(level - 1, 3)
                p = doc.add_heading(level=min(level - 1, 3))
                add_inline(p, text)
                p.style = doc.styles[style]
            i += 1
            continue

        # Bullets
        m = re.match(r"^[-*]\s+(.*)", stripped)
        if m:
            p = doc.add_paragraph(style="List Bullet")
            add_inline(p, m.group(1))
            p.paragraph_format.space_after = Pt(3)
            i += 1
            continue

        # Numbered list
        m = re.match(r"^\d+\.\s+(.*)", stripped)
        if m:
            p = doc.add_paragraph(style="List Number")
            add_inline(p, m.group(1))
            p.paragraph_format.space_after = Pt(3)
            i += 1
            continue

        if not stripped:
            i += 1
            continue

        p = doc.add_paragraph()
        add_inline(p, stripped)
        i += 1

    doc.save(out_path)
    print("Wrote", out_path)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
