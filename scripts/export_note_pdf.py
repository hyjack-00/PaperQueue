from __future__ import annotations

import sys
import re
from pathlib import Path

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer


def _register_cjk_font() -> str:
    try:
        font_name = "STSong-Light"
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))
        return font_name
    except Exception:
        pass
    candidates = [
        Path("/home/agent-user/.fonts/NotoSansCJKsc-Regular.otf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            font_name = "PaperQueueCJK"
            try:
                pdfmetrics.registerFont(TTFont(font_name, str(candidate)))
                return font_name
            except Exception:
                continue
    return "Helvetica"


def build_pdf(markdown_path: Path, output_path: Path) -> None:
    styles = getSampleStyleSheet()
    font_name = _register_cjk_font()
    title_style = ParagraphStyle('Title', parent=styles['Title'], alignment=TA_LEFT, fontName=font_name, wordWrap='CJK')
    h1 = ParagraphStyle('H1', parent=styles['Heading1'], spaceAfter=12, fontName=font_name, wordWrap='CJK')
    h2 = ParagraphStyle('H2', parent=styles['Heading2'], spaceAfter=10, fontName=font_name, wordWrap='CJK')
    body = ParagraphStyle('Body', parent=styles['BodyText'], leading=16, spaceAfter=6, fontName=font_name, wordWrap='CJK')
    bullet = ParagraphStyle('Bullet', parent=styles['BodyText'], leftIndent=12, bulletIndent=0, leading=16, spaceAfter=4, fontName=font_name, wordWrap='CJK')

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
        figure_img = re.match(r'<img src="([^"]+)">', line)
        if figure_img:
            img_path = (markdown_path.parent / figure_img.group(1)).resolve()
            if img_path.exists():
                img = Image(str(img_path))
                max_width = 16 * cm
                max_height = 20 * cm
                img._restrictSize(max_width, max_height)
                story.append(img)
                story.append(Spacer(1, 0.15 * cm))
            continue
        figure_caption = re.match(r"<figcaption>(.*?)</figcaption>", line)
        if figure_caption:
            story.append(Paragraph(figure_caption.group(1), body))
            continue
        if line in {"<figure class=\"paper-figure\">", "</figure>"}:
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
