"""Geçmiş analizlerin tutulduğu Excel dosyasını içe aktarır.

Beklenen düzen (YAG_ANALIZI_FULL.xlsx): her sütun bir analiz, her satır bir
parametre; etiketler bir sütunda (genelde B). Satır sırası sabit kabul edilmez,
etiketler PDF ile aynı eşleştirici ile tanınır. Birleştirilmiş hücreler
(ör. Motor Numarası birden çok sütunu kapsar) açılarak her sütuna dağıtılır.
"SIFIR YAĞ" başlıklı sütunlar taze yağ referansı olarak alınır. MAX/MIN/AVR
gibi hesap sütunları, geçerli bir analiz numarası olmadığından atlanır.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .db import FRESH_OIL, SAMPLE_TYPES, UNSPECIFIED
from .parameters import LabelMatcher
from .pdf_parser import ParsedSample, UnmatchedRow
from .textnorm import fold, normalize_label

ANALYSIS_ID_RE = re.compile(r"^[A-Za-z]{1,6}[-_ ]?\d{3,}$")


@dataclass
class SheetResult:
    name: str
    samples: list = field(default_factory=list)     # ParsedSample (meta: motor_no, platform ...)
    unmatched: list = field(default_factory=list)   # UnmatchedRow
    label_col: int | None = None
    warnings: list = field(default_factory=list)


def _cell_text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v).strip()


def guess_sample_type(text: str) -> str | None:
    f = fold(text or "")
    if "sifir" in f or "fresh" in f or "taze" in f:
        return FRESH_OIL
    if "rodaj" in f:
        return "Rodaj"
    if "green" in f:
        return "Green"
    if "saha" in f or "field" in f:
        return "Saha"
    for t in SAMPLE_TYPES:
        if fold(t) == f:
            return t
    return None


def read_workbook(path: str, matcher: LabelMatcher | None = None) -> list[SheetResult]:
    import openpyxl

    matcher = matcher or LabelMatcher()
    wb = openpyxl.load_workbook(path, data_only=True)
    results = []
    for ws in wb.worksheets:
        results.append(_read_sheet(ws, matcher))
    return results


def _read_sheet(ws, matcher: LabelMatcher) -> SheetResult:
    res = SheetResult(ws.title)
    max_row, max_col = ws.max_row, ws.max_column
    if max_row < 3 or max_col < 2:
        return res
    grid: dict[tuple[int, int], object] = {}
    for row in ws.iter_rows(min_row=1, max_row=max_row, max_col=max_col):
        for c in row:
            if c.value is not None:
                grid[(c.row, c.column)] = c.value
    for rng in ws.merged_cells.ranges:
        v = grid.get((rng.min_row, rng.min_col))
        if v is None:
            continue
        for r in range(rng.min_row, rng.max_row + 1):
            for cc in range(rng.min_col, rng.max_col + 1):
                grid[(r, cc)] = v

    # Etiket sütununu bul: en çok tanınan etiketi içeren sütun (ilk 15 sütun)
    best_col, best_cnt, best_matches = None, 0, {}
    for col in range(1, min(15, max_col) + 1):
        matches = {}
        for r in range(1, max_row + 1):
            t = _cell_text(grid.get((r, col)))
            if not t or re.fullmatch(r"[\d.,\s]+", t):
                continue
            m = matcher.match(t)
            if m and m.kind != "ignore":
                matches[r] = (t, m)
        if len(matches) > best_cnt:
            best_col, best_cnt, best_matches = col, len(matches), matches
    if best_col is None or best_cnt < 5:
        res.warnings.append("Etiket sütunu bulunamadı; sayfa atlandı.")
        return res
    res.label_col = best_col

    id_row = next((r for r, (_, m) in best_matches.items()
                   if m.kind == "meta" and m.key == "sample_no"), None)
    if id_row is None:
        res.warnings.append("'Analiz No' satırı bulunamadı; sayfa atlandı.")
        return res
    header_rows = [r for r, (_, m) in best_matches.items() if m.kind == "meta"]
    top_rows = range(1, max(header_rows) + 1)

    # Etiket sütunu dışındaki, tanınmayan ama değer içeren satırlar
    unknown_rows = {}
    lo_r, hi_r = min(best_matches), max(best_matches)
    for r in range(lo_r, min(max_row, hi_r + 3) + 1):  # tablo sonuna eklenmiş yeni satırlar
        if r in best_matches:
            continue
        t = _cell_text(grid.get((r, best_col)))
        if t and normalize_label(t):
            unknown_rows[r] = t

    unmatched_vals: dict[int, dict] = {}
    for col in range(best_col + 1, max_col + 1):
        sid = _cell_text(grid.get((id_row, col)))
        if not ANALYSIS_ID_RE.match(sid):
            continue
        s = ParsedSample(sid.replace(" ", "").upper())
        header_text = " ".join(_cell_text(grid.get((r, col))) for r in top_rows)
        stype = guess_sample_type(header_text) if "sifir" in fold(header_text) else None
        for r, (_label, m) in best_matches.items():
            v = grid.get((r, col))
            if v is None or _cell_text(v) == "":
                continue
            if m.kind == "meta":
                if m.key == "sample_no":
                    continue
                s.meta.setdefault(m.key, v)
            else:
                s.values.setdefault(m.key, v)
        for r, label in unknown_rows.items():
            v = grid.get((r, col))
            if v is not None and _cell_text(v) != "":
                unmatched_vals.setdefault(r, {})[s.sample_no] = _cell_text(v)
        if stype == FRESH_OIL:
            s.meta["sample_type"] = FRESH_OIL
            s.meta.pop("motor_no", None)
            s.meta.pop("platform", None)
        else:
            st = guess_sample_type(_cell_text(s.meta.get("sample_type")))
            s.meta["sample_type"] = st or s.meta.get("sample_type") or None
            mn = _cell_text(s.meta.get("motor_no"))
            if mn and guess_sample_type(mn) == FRESH_OIL:
                s.meta["sample_type"] = FRESH_OIL
                s.meta.pop("motor_no", None)
            plat = _cell_text(s.meta.get("platform"))
            if plat in ("-", "--"):
                s.meta.pop("platform", None)
        res.samples.append(s)

    for r, vals in unmatched_vals.items():
        if len(vals) >= 1:
            label = unknown_rows[r]
            res.unmatched.append(UnmatchedRow(label, normalize_label(label), vals))
    if not res.samples:
        res.warnings.append("Geçerli analiz sütunu bulunamadı.")
    return res


def default_type_for_sheet(name: str) -> str:
    f = fold(name or "")
    hits = [t for t, kw in (("Rodaj", "rodaj"), ("Green", "green"), ("Saha", "saha"),
                            (FRESH_OIL, "sifir")) if kw in f]
    return hits[0] if len(hits) == 1 else UNSPECIFIED
