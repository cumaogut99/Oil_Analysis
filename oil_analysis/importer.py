"""Ayrıştırılmış rapor/Excel verisini veritabanına yazan servis katmanı."""
from __future__ import annotations

from pathlib import Path

from .db import FRESH_OIL, UNSPECIFIED, Database
from .excel_importer import SheetResult
from .pdf_parser import ParsedReport, ParsedSample, lab_info_json
from .textnorm import fold

_LETTER_TEXT = {"y": "Yeşil", "k": "Kırmızı", "s": "Sarı"}


def _txt(v):
    if v is None:
        return None
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v).strip() or None


def apply_mappings(samples: list[ParsedSample], unmatched, mapping: dict[str, str]):
    """Kullanıcının eşleştirdiği satırları numunelere işler.

    mapping: norm etiket -> 'param:key' | 'meta:key' | 'ignore'
    """
    by_no = {s.sample_no: s for s in samples}
    for u in unmatched:
        tgt = mapping.get(u.norm)
        if not tgt or tgt == "ignore":
            continue
        kind, _, key = tgt.partition(":")
        for sno, raw in u.values.items():
            s = by_no.get(sno)
            if s is None:
                continue
            (s.meta if kind == "meta" else s.values).setdefault(key, raw)


def save_report(db: Database, report: ParsedReport, *, motor_no: str, platform_code: str | None,
                sample_type: str, oil_type: str | None, include_history: bool = True,
                overwrite_main: bool = False, user_comment: str | None = None) -> dict:
    counts = {"inserted": 0, "updated": 0, "skipped": 0}
    main = report.main_sample_no
    h = report.header
    for sno, ps in report.samples.items():
        is_main = sno == main
        if not is_main and not include_history:
            continue
        m = ps.meta
        meta = {
            "platform_code": platform_code,
            "sample_type": sample_type if is_main else UNSPECIFIED,
            "oil_type": oil_type,
            "lubricant": h.get("lubricant"),
            "source": "SGS",
            "date_taken": m.get("date_taken"),
            "date_received": m.get("date_received"),
            "date_analysis": m.get("date_analysis"),
            "date_diagnosis": m.get("date_diagnosis"),
            "motor_hours": m.get("motor_hours"),
            "oil_hours": m.get("oil_hours"),
            "topup": m.get("topup"),
            "lab_diag_letter": m.get("lab_diag_letter"),
            "lab_diagnosis": _LETTER_TEXT.get(fold(m.get("lab_diag_letter") or "")),
            "origin": "pdf" if is_main else "pdf-geçmiş",
            "source_file": Path(report.file).name,
        }
        if is_main:
            meta["lab_diagnosis"] = h.get("lab_diagnosis") or meta["lab_diagnosis"]
            meta["date_diagnosis"] = meta["date_diagnosis"] or h.get("lab_diagnosis_date")
            meta["lab_comment"] = h.get("lab_comment")
            meta["lab_info"] = lab_info_json(report)
            meta["user_comment"] = user_comment
        status = db.save_sample(sno, motor_no, meta, ps.values,
                                overwrite=overwrite_main and is_main, commit=False)
        counts[status] += 1
    db.commit()
    return counts


def save_excel(db: Database, sheets: list[SheetResult], sheet_types: dict[str, str],
               overwrite: bool = False, source_file: str = "") -> dict:
    counts = {"inserted": 0, "updated": 0, "skipped": 0}
    for sh in sheets:
        default_type = sheet_types.get(sh.name, UNSPECIFIED)
        for ps in sh.samples:
            m = ps.meta
            stype = m.get("sample_type") or default_type
            meta = {
                "platform_code": _txt(m.get("platform")),
                "sample_type": stype,
                "oil_type": _txt(m.get("oil_type")),
                "source": _txt(m.get("source")),
                "date_taken": m.get("date_taken"),
                "date_analysis": m.get("date_analysis"),
                "motor_hours": m.get("motor_hours"),
                "oil_hours": m.get("oil_hours"),
                "topup": m.get("topup"),
                "lab_diag_letter": _txt(m.get("lab_diag_letter")),
                "origin": f"excel:{sh.name}",
                "source_file": source_file,
            }
            motor = None if stype == FRESH_OIL else _txt(m.get("motor_no"))
            status = db.save_sample(ps.sample_no, motor, meta, ps.values,
                                    overwrite=overwrite, commit=False)
            counts[status] += 1
    db.commit()
    return counts
