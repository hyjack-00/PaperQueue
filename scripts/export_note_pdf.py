from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer


def build_pdf(markdown_path: Path, output_path: Path) -> None:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Title'], alignment=TA_LEFT)
    h1 = ParagraphStyle('H1', parent=styles['Heading1'], spaceAfter=12)
    h2 = ParagraphStyle('H2', parent=styles['Heading2'], spaceAfter=10)
    body = ParagraphStyle('Body', parent=styles['BodyText'], leading=16, spaceAfter=6)
    bullet = ParagraphStyle('Bullet', parent=styles['BodyText'], leftIndent=12, bulletIndent=0, leading=16, spaceAfter=4)

    lines = markdown_path.read_text(encoding='utf-8').splitlines()
    story = []
    in_frontmatter = False
    frontmatter_seen = 0

    for raw in lines:
        line = raw.strip()
        if line == '---':
            frontmatter_seen += 1
            in_frontmatter = frontmatter_seen == 1 or (in_frontmatter and frontmatter_seen == 2)
            if frontmatter_seen >= 2:
                in_frontmatter = False
            continue
        if frontmatter_seen == 1 and in_frontmatter:
            continue
        if not line:
            story.append(Spacer(1, 0.18 * cm))
            continue
        if line.startswith('# '):
            story.append(Paragraph(line[2:], title_style))
            continue
        if line.startswith('## '):
            story.append(Paragraph(line[3:], h1))
            continue
        if line.startswith('### '):
            story.append(Paragraph(line[4:], h2))
            continue
        if line.startswith('![](') and line.endswith(')'):
            rel = line[4:-1]
            img_path = (markdown_path.parent / rel).resolve()
            if img_path.exists():
                img = Image(str(img_path))
                max_width = 16 * cm
                max_height = 20 * cm
                img._restrictSize(max_width, max_height)
                story.append(img)
                story.append(Spacer(1, 0.2 * cm))
            continue
        if line.startswith('* '):
            story.append(Paragraph(line[2:], bullet, bulletText='•'))
            continue
        if line.startswith('- '):
            story.append(Paragraph(line[2:], bullet, bulletText='•'))
            continue
        story.append(Paragraph(line, body))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output_path), pagesize=A4, leftMargin=1.5*cm, rightMargin=1.5*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)
    doc.build(story)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('usage: export_note_pdf.py <input.md> <output.pdf>')
    build_pdf(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
