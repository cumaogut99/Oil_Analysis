"""Veritabanını Excel'e dışa aktarma (mevcut Excel düzenine benzer geniş format + uzun format)."""
from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .db import Sample
from .evaluation import STATUS_TEXT, Evaluator
from .parameters import ParamDef
from .textnorm import format_date

FILLS = {1: PatternFill("solid", fgColor="FFF3A6"), 2: PatternFill("solid", fgColor="F5A3A3")}
HEAD_FILL = PatternFill("solid", fgColor="C6E0B4")


def export_workbook(path: str, samples: list[Sample], params: list[ParamDef], ev: Evaluator,
                    platforms: dict[str, str]):
    wb = Workbook()
    ws = wb.active
    ws.title = "Analizler"
    samples = sorted(samples, key=lambda s: (s.motor_no or "~", s.sort_key()))
    used = [p for p in params if any(p.key in s.values for s in samples)]
    head = [("Motor Numarası", lambda s: s.motor_no or ""),
            ("Platform", lambda s: s.platform_code or ""),
            ("Platform Grubu", lambda s: platforms.get(s.platform_code or "", "") if s.platform_code else ""),
            ("Analiz No", lambda s: s.sample_no),
            ("Numune Tipi", lambda s: s.sample_type),
            ("Tarih", lambda s: format_date(s.date_taken)),
            ("Yağ Tipi", lambda s: s.oil_type or ""),
            ("Motor Çalışma Süresi (sa)", lambda s: s.motor_hours),
            ("Yağ Çalışma Süresi (sa)", lambda s: s.oil_hours),
            ("SGS Teşhisi", lambda s: s.lab_diagnosis or s.lab_diag_letter or ""),
            ("Genel Durum", lambda s: "Sıfır Yağ" if s.is_fresh else STATUS_TEXT[ev.overall(s)[0]])]
    ws.cell(1, 1, "Parametre").font = Font(bold=True)
    for r, (label, _fn) in enumerate(head, start=1):
        c = ws.cell(r, 1, label)
        c.font = Font(bold=True)
        c.fill = HEAD_FILL
    for r, p in enumerate(used, start=len(head) + 2):
        ws.cell(r, 1, f"{p.name} [{p.unit}]" if p.unit else p.name).font = Font(bold=True)
    for c, s in enumerate(samples, start=2):
        evs = ev.evaluate(s)
        for r, (_label, fn) in enumerate(head, start=1):
            cell = ws.cell(r, c, fn(s))
            cell.fill = HEAD_FILL
            cell.alignment = Alignment(horizontal="center")
        for r, p in enumerate(used, start=len(head) + 2):
            v = s.values.get(p.key)
            raw = s.raws.get(p.key)
            if v is None and not raw:
                continue
            cell = ws.cell(r, c, v if v is not None else raw)
            cell.alignment = Alignment(horizontal="center")
            e = evs.get(p.key)
            if e is not None and e.status in FILLS:
                cell.fill = FILLS[e.status]
    ws.column_dimensions["A"].width = 30
    for c in range(2, len(samples) + 2):
        ws.column_dimensions[get_column_letter(c)].width = 12
    ws.freeze_panes = "B2"

    # Yorumlar
    wc = wb.create_sheet("Yorumlar")
    wc.append(["Analiz No", "Motor", "Tarih", "Genel Durum", "Dikkat Gerektirenler",
               "SGS Teşhisi", "SGS Yorumu", "Değerlendirme Yorumu"])
    for s in samples:
        st, flagged = ev.overall(s)
        wc.append([s.sample_no, s.motor_no, format_date(s.date_taken),
                   "Sıfır Yağ" if s.is_fresh else STATUS_TEXT[st], ", ".join(flagged),
                   s.lab_diagnosis, s.lab_comment, s.user_comment])

    # Uzun format (pivot / Power BI için)
    wl = wb.create_sheet("Uzun Format")
    wl.append(["Analiz No", "Motor", "Platform", "Platform Grubu", "Numune Tipi", "Yağ Tipi", "Tarih",
               "Motor sa", "Yağ sa", "Parametre", "Birim", "Değer", "Ham", "Durum",
               "Artış hızı (/100 sa)"])
    pmap = {p.key: p for p in params}
    for s in samples:
        evs = ev.evaluate(s)
        for key, v in s.values.items():
            p = pmap.get(key)
            e = evs.get(key)
            wl.append([s.sample_no, s.motor_no, s.platform_code,
                       platforms.get(s.platform_code or "", "") if s.platform_code else "",
                       s.sample_type, s.oil_type, s.date_taken, s.motor_hours, s.oil_hours,
                       p.name if p else key, p.unit if p else "", v, s.raws.get(key),
                       STATUS_TEXT.get(e.status) if e else "", e.rate if e else None])
    wb.save(path)
