"""Rapor modelini PDF'e yazar (reportlab): kapak, içindekiler (sayfa numaralı), yer imleri."""
from __future__ import annotations

import os
from xml.sax.saxutils import escape

from .model import Heading, Image, KeyValues, PageBreak, Para, Report, Table

PRIMARY = "#1d4ed8"
DARK = "#0f172a"
MUTED = "#64748b"
BORDER = "#cbd5e1"
HEAD_BG = "#e2e8f0"
STATUS_BG = {0: "#dcfce7", 1: "#fef3c7", 2: "#fee2e2"}
STATUS_FG = {0: "#166534", 1: "#92400e", 2: "#991b1b"}


def _register_fonts():
    """Türkçe karakterler için DejaVu (matplotlib ile birlikte gelir)."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if "DejaVu" in pdfmetrics.getRegisteredFontNames():
        return "DejaVu", "DejaVu-Bold"
    import matplotlib
    base = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
    pdfmetrics.registerFont(TTFont("DejaVu", os.path.join(base, "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", os.path.join(base, "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold",
                                  italic="DejaVu", boldItalic="DejaVu-Bold")
    return "DejaVu", "DejaVu-Bold"


def write_pdf(rep: Report, path: str):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (BaseDocTemplate, Frame, NextPageTemplate, PageTemplate, Paragraph,
                                    Spacer)
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import PageBreak as RLPageBreak
    from reportlab.platypus import Table as RLTable
    from reportlab.platypus import TableStyle
    from reportlab.platypus.tableofcontents import TableOfContents

    font, bold = _register_fonts()
    W, H = A4
    margin = 1.8 * cm
    avail = W - 2 * margin

    st = {
        "title": ParagraphStyle("t", fontName=bold, fontSize=26, leading=32, textColor=colors.HexColor(DARK)),
        "subtitle": ParagraphStyle("st", fontName=font, fontSize=13, leading=18,
                                   textColor=colors.HexColor(MUTED)),
        "h1": ParagraphStyle("h1", fontName=bold, fontSize=16, leading=21, spaceAfter=8,
                             textColor=colors.HexColor(PRIMARY)),
        "h2": ParagraphStyle("h2", fontName=bold, fontSize=12, leading=16, spaceBefore=10, spaceAfter=5,
                             textColor=colors.HexColor(DARK)),
        "h3": ParagraphStyle("h3", fontName=bold, fontSize=9.5, leading=13, spaceBefore=9, spaceAfter=3,
                             textColor=colors.HexColor(DARK)),
        "normal": ParagraphStyle("n", fontName=font, fontSize=9, leading=12.5, spaceAfter=5, alignment=TA_LEFT),
        "muted": ParagraphStyle("m", fontName=font, fontSize=8.5, leading=12, spaceAfter=5,
                                textColor=colors.HexColor(MUTED)),
        "small": ParagraphStyle("s", fontName=font, fontSize=8, leading=11, spaceAfter=5,
                                textColor=colors.HexColor("#334155")),
        "cell": ParagraphStyle("c", fontName=font, fontSize=7.5, leading=9.5),
        "cellh": ParagraphStyle("ch", fontName=bold, fontSize=7.5, leading=9.5, textColor=colors.HexColor(DARK)),
        "toc_title": ParagraphStyle("tt", fontName=bold, fontSize=18, leading=24, spaceAfter=14,
                                    textColor=colors.HexColor(DARK)),
    }

    class Doc(BaseDocTemplate):
        def afterFlowable(self, f):
            if isinstance(f, Paragraph) and getattr(f, "_toc_level", None) is not None:
                lvl = f._toc_level
                key = f"h{id(f)}"
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(f.getPlainText(), key, level=lvl, closed=lvl > 0)
                self.notify("TOCEntry", (lvl, f.getPlainText(), self.page, key))

    def cover_page(canv, _doc):
        canv.saveState()
        canv.setFillColor(colors.HexColor(DARK))
        canv.rect(0, H - 7.5 * cm, W, 7.5 * cm, stroke=0, fill=1)
        canv.setFillColor(colors.HexColor("#38bdf8"))
        canv.rect(0, H - 7.5 * cm, W, 0.25 * cm, stroke=0, fill=1)
        canv.setFillColor(colors.white)
        canv.setFont(bold, 11)
        canv.drawString(margin, H - 2.2 * cm, "MOTOR YAĞI ANALİZ")
        canv.setFont(font, 8)
        canv.setFillColor(colors.HexColor(MUTED))
        canv.drawString(margin, 1.2 * cm, f"Oluşturma tarihi: {rep.date}")
        canv.restoreState()

    def normal_page(canv, doc):
        canv.saveState()
        canv.setStrokeColor(colors.HexColor(BORDER))
        canv.setLineWidth(0.5)
        canv.line(margin, H - 1.25 * cm, W - margin, H - 1.25 * cm)
        canv.line(margin, 1.3 * cm, W - margin, 1.3 * cm)
        canv.setFont(font, 7.5)
        canv.setFillColor(colors.HexColor(MUTED))
        canv.drawString(margin, H - 1.05 * cm, rep.title[:110])
        canv.drawRightString(W - margin, H - 1.05 * cm, rep.date)
        canv.drawString(margin, 0.85 * cm, "Motor Yağı Analiz")
        canv.drawRightString(W - margin, 0.85 * cm, f"Sayfa {doc.page}")
        canv.restoreState()

    doc = Doc(path, pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=1.8 * cm,
              bottomMargin=1.8 * cm, title=rep.title, author=rep.author or "", subject=rep.subtitle or "")
    frame_cover = Frame(margin, 2 * cm, avail, H - 10 * cm, id="cover")
    frame = Frame(margin, 1.6 * cm, avail, H - 3.2 * cm, id="normal")
    doc.addPageTemplates([PageTemplate("cover", [frame_cover], onPage=cover_page),
                          PageTemplate("normal", [frame], onPage=normal_page)])

    def P(text, style):
        return Paragraph(escape(str(text)).replace("\n", "<br/>"), st[style])

    story = []
    # ---- kapak
    story.append(Spacer(1, 0.6 * cm))
    story.append(P(rep.title, "title"))
    if rep.subtitle:
        story.append(Spacer(1, 0.2 * cm))
        story.append(P(rep.subtitle, "subtitle"))
    story.append(Spacer(1, 1.2 * cm))
    kv = [[P(k, "cellh"), P(v, "cell")] for k, v in rep.cover_pairs]
    t = RLTable(kv, colWidths=[5 * cm, avail - 5 * cm])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor(BORDER)),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(t)
    if rep.description:
        story.append(Spacer(1, 0.8 * cm))
        story.append(P(rep.description, "normal"))
    story.append(NextPageTemplate("normal"))
    story.append(RLPageBreak())

    # ---- içindekiler
    story.append(Paragraph("İçindekiler", st["toc_title"]))
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle("toc1", fontName=bold, fontSize=10.5, leading=16, leftIndent=0, firstLineIndent=0),
        ParagraphStyle("toc2", fontName=font, fontSize=9, leading=13, leftIndent=14, firstLineIndent=0,
                       textColor=colors.HexColor("#334155")),
    ]
    toc.dotsMinLevel = 0
    story.append(toc)
    story.append(RLPageBreak())

    # ---- içerik
    first = True
    for b in rep.blocks:
        if isinstance(b, PageBreak):
            if not first:
                story.append(RLPageBreak())
            continue
        first = False
        if isinstance(b, Heading):
            p = P(b.text, {1: "h1", 2: "h2"}.get(b.level, "h3"))
            if b.level <= 2:
                p._toc_level = b.level - 1
            story.append(p)
        elif isinstance(b, Para):
            story.append(P(b.text, b.style if b.style in st else "normal"))
        elif isinstance(b, KeyValues):
            kv = [[P(k, "cellh"), P(v, "cell")] for k, v in b.pairs]
            t = RLTable(kv, colWidths=[4.5 * cm, avail - 4.5 * cm])
            t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor(BORDER)),
                                   ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            story.append(t)
            story.append(Spacer(1, 0.3 * cm))
        elif isinstance(b, Table):
            story.append(_table(b, st, avail, colors, RLTable, TableStyle, P))
            story.append(Spacer(1, 0.3 * cm))
        elif isinstance(b, Image):
            from reportlab.lib.utils import ImageReader
            iw, ih = ImageReader(b.path).getSize()
            w = min(b.width_cm * cm, avail)
            story.append(RLImage(b.path, width=w, height=w * ih / iw))
            if b.caption:
                story.append(P(b.caption, "muted"))
            story.append(Spacer(1, 0.25 * cm))
    doc.multiBuild(story)
    return path


def _table(b: Table, st, avail, colors, RLTable, TableStyle, P):
    n = len(b.headers)
    rel = b.widths or [1] * n
    tot = float(sum(rel))
    widths = [avail * r / tot for r in rel]
    for k, col in STATUS_FG.items():
        st.setdefault(f"cell{k}", st["cell"].clone(f"cell{k}", textColor=colors.HexColor(col)))
    data = [[P(h, "cellh") for h in b.headers]]
    for i, row in enumerate(b.rows):
        srow = (b.statuses[i] if b.statuses and i < len(b.statuses) else None) or [None] * n
        data.append([P(c, f"cell{srow[j]}" if j < len(srow) and srow[j] in STATUS_FG else "cell")
                     for j, c in enumerate(row)])
    if len(data) == 1:
        data.append([P("—", "cell")] + [P("", "cell") for _ in range(n - 1)])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(HEAD_BG)),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#94a3b8")),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor(BORDER)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f8fafc")))
    if b.statuses:
        for i, srow in enumerate(b.statuses, start=1):
            for j, s in enumerate(srow or []):
                if s in STATUS_BG:
                    style.append(("BACKGROUND", (j, i), (j, i), colors.HexColor(STATUS_BG[s])))
    t = RLTable(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle(style))
    return t
