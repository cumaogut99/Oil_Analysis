"""Rapor modelini Word (DOCX) dosyasına yazar (python-docx).

İçindekiler gerçek bir Word TOC alanıdır; dosya açılırken Word alanları
güncellemeyi önerir (sayfa numaraları dolar). Güncellenmeden önce de başlık
listesi görünür.
"""
from __future__ import annotations

import os
import sys

from .model import Heading, Image, KeyValues, PageBreak, Para, Report, Table

if getattr(sys, "frozen", False):
    # python-docx üst/alt bilgi şablonunu "docx/parts/../templates" yoluyla açar; exe'de
    # modüller arşivde olduğundan "docx/parts" klasörü yoktur ve yol çözülemez.
    os.makedirs(os.path.join(getattr(sys, "_MEIPASS", ""), "docx", "parts"), exist_ok=True)

PRIMARY = "1D4ED8"
DARK = "0F172A"
MUTED = "64748B"
HEAD_BG = "E2E8F0"
ALT_BG = "F8FAFC"
STATUS_BG = {0: "DCFCE7", 1: "FEF3C7", 2: "FEE2E2"}
STATUS_FG = {0: "166534", 1: "92400E", 2: "991B1B"}


def _shade(cell, hex_color):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def _repeat_header(row):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trPr.append(el)


def _field(paragraph, instr, placeholder=""):
    """Paragrafa bir Word alanı ekler (PAGE, TOC ...)."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    def fld(t):
        r = OxmlElement("w:r")
        f = OxmlElement("w:fldChar")
        f.set(qn("w:fldCharType"), t)
        if t == "begin":
            f.set(qn("w:dirty"), "true")
        r.append(f)
        return r

    p = paragraph._p
    p.append(fld("begin"))
    r = OxmlElement("w:r")
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = instr
    r.append(it)
    p.append(r)
    p.append(fld("separate"))
    if placeholder:
        r = OxmlElement("w:r")
        for i, line in enumerate(placeholder.split("\n")):
            if i:
                r.append(OxmlElement("w:br"))
            t = OxmlElement("w:t")
            t.set(qn("xml:space"), "preserve")
            t.text = line
            r.append(t)
        p.append(r)
    p.append(fld("end"))


def _set_cell_text(cell, text, size, bold=False, color=None):
    from docx.shared import Pt, RGBColor
    cell.text = ""
    par = cell.paragraphs[0]
    par.paragraph_format.space_after = Pt(0)
    run = par.add_run(str(text))
    run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def write_docx(rep: Report, path: str):
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    doc = Document()
    # yazı tipi ve başlık stilleri
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    for lvl, size, color in ((1, 16, PRIMARY), (2, 12.5, DARK), (3, 10.5, DARK)):
        hs = doc.styles[f"Heading {lvl}"]
        hs.font.name = "Calibri"
        hs.font.size = Pt(size)
        hs.font.bold = True
        hs.font.color.rgb = RGBColor.from_string(color)
    # alanları açılışta güncelle
    settings = doc.settings.element
    upd = OxmlElement("w:updateFields")
    upd.set(qn("w:val"), "true")
    settings.append(upd)

    sec = doc.sections[0]
    sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
    for side in ("left_margin", "right_margin"):
        setattr(sec, side, Cm(2.0))
    sec.top_margin = Cm(2.0)
    sec.bottom_margin = Cm(1.8)
    sec.different_first_page_header_footer = True
    # kapak sayfası: boş üst/alt bilgi (bazı programlar tanımsızsa varsayılanı gösterir)
    sec.first_page_header.is_linked_to_previous = False
    sec.first_page_footer.is_linked_to_previous = False
    sec.first_page_footer.paragraphs[0].text = ""
    # alt bilgi: sayfa numarası (kapak hariç)
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = fp.add_run("Sayfa ")
    r.font.size = Pt(8)
    _field(fp, "PAGE", "1")
    hp = sec.header.paragraphs[0]
    hr = hp.add_run(rep.title)
    hr.font.size = Pt(8)
    hr.font.color.rgb = RGBColor.from_string(MUTED)
    usable = 17.0

    # ---------------- kapak
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(90)
    r = p.add_run("MOTOR YAĞI ANALİZ")
    r.font.size = Pt(11)
    r.bold = True
    r.font.color.rgb = RGBColor.from_string(PRIMARY)
    p = doc.add_paragraph()
    r = p.add_run(rep.title)
    r.font.size = Pt(28)
    r.bold = True
    r.font.color.rgb = RGBColor.from_string(DARK)
    if rep.subtitle:
        p = doc.add_paragraph()
        r = p.add_run(rep.subtitle)
        r.font.size = Pt(14)
        r.font.color.rgb = RGBColor.from_string(MUTED)
    doc.add_paragraph().paragraph_format.space_after = Pt(30)
    t = doc.add_table(rows=0, cols=2)
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    for k, v in rep.cover_pairs:
        row = t.add_row()
        _set_cell_text(row.cells[0], k, 10, bold=True, color=DARK)
        _set_cell_text(row.cells[1], v, 10)
        row.cells[0].width = Cm(5)
        row.cells[1].width = Cm(usable - 5)
    if rep.description:
        doc.add_paragraph()
        doc.add_paragraph(rep.description)
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # ---------------- içindekiler
    p = doc.add_paragraph()
    r = p.add_run("İçindekiler")
    r.font.size = Pt(18)
    r.bold = True
    r.font.color.rgb = RGBColor.from_string(DARK)
    heads = rep.headings(2)
    placeholder = "\n".join(("    " if h.level == 2 else "") + h.text for h in heads)
    toc_p = doc.add_paragraph()
    _field(toc_p, 'TOC \\o "1-2" \\h \\z \\u', placeholder or " ")
    note = doc.add_paragraph()
    nr = note.add_run("Sayfa numaraları Word açılırken alanlar güncellendiğinde dolar "
                      "(gerekirse: sağ tık > Alanı Güncelleştir).")
    nr.font.size = Pt(7.5)
    nr.italic = True
    nr.font.color.rgb = RGBColor.from_string(MUTED)

    # ---------------- içerik
    for b in rep.blocks:
        if isinstance(b, PageBreak):
            continue  # her 1. seviye başlık zaten yeni sayfada başlar
        if isinstance(b, Heading):
            if b.level == 1:
                doc.add_page_break()
            doc.add_heading(b.text, level=min(b.level, 3))
        elif isinstance(b, Para):
            p = doc.add_paragraph()
            r = p.add_run(b.text)
            if b.style in ("muted", "small"):
                r.font.size = Pt(8.5)
                r.font.color.rgb = RGBColor.from_string(MUTED if b.style == "muted" else "334155")
        elif isinstance(b, KeyValues):
            t = doc.add_table(rows=0, cols=2)
            for k, v in b.pairs:
                row = t.add_row()
                _set_cell_text(row.cells[0], k, 9, bold=True)
                _set_cell_text(row.cells[1], v, 9)
                row.cells[0].width = Cm(4.5)
                row.cells[1].width = Cm(usable - 4.5)
            doc.add_paragraph()
        elif isinstance(b, Table):
            _table(doc, b, usable)
            doc.add_paragraph().paragraph_format.space_after = Pt(2)
        elif isinstance(b, Image):
            doc.add_picture(b.path, width=Cm(min(b.width_cm, usable)))
            if b.caption:
                cp = doc.add_paragraph(b.caption)
                cp.runs[0].font.size = Pt(8)
    doc.save(path)
    return path


def _table(doc, b: Table, usable):
    from docx.shared import Cm
    n = len(b.headers)
    t = doc.add_table(rows=1, cols=n)
    t.style = "Table Grid"
    rel = b.widths or [1] * n
    tot = float(sum(rel))
    widths = [Cm(usable * r / tot) for r in rel]
    size = 7.5 if b.small else 9
    hdr = t.rows[0]
    _repeat_header(hdr)
    for j, h in enumerate(b.headers):
        _set_cell_text(hdr.cells[j], h, size, bold=True, color=DARK)
        _shade(hdr.cells[j], HEAD_BG)
        hdr.cells[j].width = widths[j]
    rows = b.rows or [["—"] + [""] * (n - 1)]
    for i, row in enumerate(rows):
        cells = t.add_row().cells
        srow = (b.statuses[i] if b.statuses and i < len(b.statuses) else None) or [None] * n
        for j, val in enumerate(row):
            s = srow[j] if j < len(srow) else None
            _set_cell_text(cells[j], val, size, color=STATUS_FG.get(s))
            if s in STATUS_BG:
                _shade(cells[j], STATUS_BG[s])
            elif i % 2 == 1:
                _shade(cells[j], ALT_BG)
            cells[j].width = widths[j]
