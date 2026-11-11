"""SGS yağ analizi PDF raporlarını okuyan ayrıştırıcı.

Tasarım ilkeleri (rapor formatı kişiden kişiye değişebildiği için):

* Sabit satır sırası veya sabit koordinat varsayılmaz. Her sayfadaki kelimeler
  konumlarıyla birlikte okunur.
* Numune sütunları "Sample Number" satırındaki numune numaralarının (ELD00135
  gibi) yatay konumundan bulunur. Kaç sütun dolu olursa olsun çalışır.
* Etiket sütunu ile değer sütunları ayrı ayrı satırlara gruplanır ve sıra
  korumalı dinamik programlama (DP) ile hizalanır. Böylece değerler etiketten
  biraz kaymış olsa bile (çok sayfalı/ölçekli PDF'ler) doğru satıra düşer.
* Etiketler `LabelMatcher` ile normalize edilip eşleştirilir (Ca = Kalsiyum,
  "Su içeriği %" ≠ "Su içeriği mg/kg" vb.). Eşleşmeyenler kullanıcıya sorulur.
* PDF'te metin katmanı yoksa (taranmış), Tesseract kuruluysa OCR ile aynı
  kelime-konum verisi üretilip aynı algoritma çalıştırılır.
"""
from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from .parameters import HEADER_RE, LabelMatcher
from .textnorm import fold, normalize_label, parse_date, parse_number

ID_RE = re.compile(r"^[A-Z]{2,6}\d{4,}$")
_DIAG_BANNER_RE = re.compile(
    r"diagnosis\s*:?\s*(yesil|sari|kirmizi|turuncu|green|yellow|red|orange)\b"
    r"(?:\s+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}))?")
_STOP_RE = re.compile(r"^(end of analytical|analysed by|analyzed by|diagnosed by)")
_COLOR_NAMES = {"yesil": "Yeşil", "green": "Yeşil", "sari": "Sarı", "yellow": "Sarı",
                "kirmizi": "Kırmızı", "red": "Kırmızı", "turuncu": "Turuncu",
                "orange": "Turuncu"}


class ParseError(Exception):
    pass


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def xc(self):
        return (self.x0 + self.x1) / 2

    @property
    def yc(self):
        return (self.top + self.bottom) / 2


@dataclass
class ParsedSample:
    sample_no: str
    meta: dict = field(default_factory=dict)      # meta anahtarı -> ham metin
    values: dict = field(default_factory=dict)    # param anahtarı -> ham metin

    def number(self, key):
        return parse_number(self.values.get(key))


@dataclass
class UnmatchedRow:
    label: str
    norm: str
    values: dict  # sample_no -> ham metin


@dataclass
class ParsedReport:
    file: str
    report_no: str | None = None
    header: dict = field(default_factory=dict)
    samples: dict = field(default_factory=dict)   # sample_no -> ParsedSample
    unmatched: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    used_ocr: bool = False

    @property
    def main_sample_no(self) -> str | None:
        for cand in (self.report_no, self.header.get("sample_nr")):
            if cand and cand in self.samples:
                return cand
        if self.samples:
            # en son tarihli / en sağdaki sütun
            return list(self.samples)[-1]
        return self.report_no


# ------------------------------------------------------------ kelime okuma
def _words_from_pdf(path: str):
    import pdfplumber
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            ws = page.extract_words(x_tolerance=1.5, y_tolerance=2.5,
                                    keep_blank_chars=False, use_text_flow=False)
            words = [Word(w["text"], w["x0"], w["x1"], w["top"], w["bottom"]) for w in ws]
            w = float(page.width)
            try:
                left = page.crop((0, 0, w / 2, page.height)).extract_text() or ""
                right = page.crop((w / 2, 0, w, page.height)).extract_text() or ""
            except Exception:  # noqa: BLE001
                left = right = ""
            full = page.extract_text() or ""
            pages.append({"words": words, "texts": [left, right, full], "width": w})
    return pages


def _words_from_ocr(path: str):
    try:
        import pytesseract
        import pdfplumber
    except ImportError as exc:
        raise ParseError(
            "PDF metin katmanı içermiyor (taranmış belge). OCR için 'pytesseract' "
            "paketi ve Tesseract programı (tur+eng dil paketleriyle) kurulmalıdır.") from exc
    pages = []
    dpi = 300
    scale = 72.0 / dpi
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            img = page.to_image(resolution=dpi).original
            try:
                data = pytesseract.image_to_data(img, lang="tur+eng",
                                                 output_type=pytesseract.Output.DICT)
                text = pytesseract.image_to_string(img, lang="tur+eng")
            except Exception as exc:  # noqa: BLE001
                raise ParseError(f"OCR başarısız: {exc}") from exc
            words = []
            for i, t in enumerate(data["text"]):
                t = (t or "").strip()
                if not t or float(data["conf"][i]) < 0:
                    continue
                x, y, w, h = (data[k][i] * scale for k in ("left", "top", "width", "height"))
                words.append(Word(t, x, x + w, y, y + h))
            pages.append({"words": words, "texts": [text, "", text], "width": float(page.width)})
    return pages


# ---------------------------------------------------------- yardımcılar
def _group_lines(words: list[Word]) -> list[list[Word]]:
    if not words:
        return []
    hs = sorted(w.bottom - w.top for w in words)
    tol = max(2.0, 0.45 * hs[len(hs) // 2])
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.yc, w.x0)):
        if lines and abs(w.yc - statistics.fmean(x.yc for x in lines[-1])) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w.x0) for line in lines]


def _line_text(line: list[Word]) -> str:
    return " ".join(w.text for w in line)


def _align(labels, values, row_h, skip_label=0.45, skip_value=1.5):
    """Sıra korumalı hizalama. labels/values: y koordinat listeleri.

    Dönen: {value_index: label_index}
    """
    n, m = len(labels), len(values)
    INF = float("inf")
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    bt = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            cur = dp[i][j]
            if cur == INF:
                continue
            if i < n and cur + skip_label < dp[i + 1][j]:
                dp[i + 1][j] = cur + skip_label
                bt[i + 1][j] = (i, j, None)
            if j < m and cur + skip_value < dp[i][j + 1]:
                dp[i][j + 1] = cur + skip_value
                bt[i][j + 1] = (i, j, None)
            if i < n and j < m:
                d = abs(labels[i] - values[j]) / row_h
                c = cur + (d if d <= 1.6 else 50.0)
                if c < dp[i + 1][j + 1]:
                    dp[i + 1][j + 1] = c
                    bt[i + 1][j + 1] = (i, j, "m")
    out = {}
    i, j = n, m
    while (i, j) != (0, 0):
        pi, pj, kind = bt[i][j]
        if kind == "m":
            out[pj] = pi
        i, j = pi, pj
    return out


# --------------------------------------------------------- tablo ayrıştırma
def _parse_table(words: list[Word], matcher: LabelMatcher, report: ParsedReport):
    """Bir sayfadaki sonuç/geçmiş tablosunu ayrıştırır."""
    lines = _group_lines(words)
    start_idx = None
    for i, line in enumerate(lines):
        lead = normalize_label(" ".join(w.text for w in line[:3]))
        if not re.match(r"^sample (number|nr|no)\b", lead):
            continue
        id_pos = [k for k, w in enumerate(line) if ID_RE.match(w.text)]
        if not id_pos:
            continue
        # "Sample Nr : ELD00135" gibi bilgi kutusu satırlarını ele (iki nokta içerir)
        if any(":" in w.text for w in line[:id_pos[0]]):
            continue
        start_idx = i
        break
    if start_idx is None:
        return
    id_line = lines[start_idx]
    ids = [w for w in id_line if ID_RE.match(w.text)]
    # Aynı satıra düşmemiş ama çok yakın ID'ler
    y0 = statistics.fmean(w.yc for w in id_line)
    for line in lines[max(0, start_idx - 1): start_idx + 2]:
        for w in line:
            if ID_RE.match(w.text) and w not in ids and abs(w.yc - y0) < 6:
                ids.append(w)
    ids.sort(key=lambda w: w.xc)
    centers = [w.xc for w in ids]
    sample_nos = [w.text for w in ids]
    if len(centers) >= 2:
        hw = min(b - a for a, b in zip(centers, centers[1:])) / 2
    else:
        hw = 45.0
    hw = max(hw, 20.0)
    label_right = centers[0] - hw

    # bölge: "Sequential number" (varsa) satırından durma satırına kadar
    first = start_idx
    for k in range(max(0, start_idx - 3), start_idx):
        if normalize_label(_line_text(lines[k])).startswith("sequential"):
            first = k
    last = len(lines)
    for k in range(start_idx + 1, len(lines)):
        full = fold(_line_text(lines[k]))
        lead = normalize_label(" ".join(w.text for w in lines[k] if w.x1 <= label_right))
        if _DIAG_BANNER_RE.search(full) or _STOP_RE.match(lead):
            last = k
            break
    region = [w for line in lines[first:last] for w in line]

    label_words, col_words = [], [[] for _ in centers]
    for w in region:
        if w.x1 <= label_right + 2:
            label_words.append(w)
            continue
        if "+" in w.text:  # Test suite kodları (V40+V100+VI+...) sütunlara taşar
            continue
        best = min(range(len(centers)), key=lambda c: abs(w.xc - centers[c]))
        if abs(w.xc - centers[best]) <= hw * 1.05:
            col_words[best].append(w)

    label_rows = []
    for line in _group_lines(label_words):
        text = _line_text(line)
        norm = normalize_label(text)
        if not norm or HEADER_RE.search(norm):
            continue
        label_rows.append((statistics.fmean(w.yc for w in line), text, norm))
    if not label_rows:
        return
    ys = [r[0] for r in label_rows]
    diffs = [b - a for a, b in zip(ys, ys[1:]) if b - a > 2]
    row_h = statistics.median(diffs) if diffs else 12.0

    # Etiket satırlarını eşleştir
    matches = [matcher.match(r[1]) for r in label_rows]

    # Her sütun için değerleri hizala. Sayfa genelinde sistematik bir kayma
    # (ölçek/ofset) varsa doğrusal model ile tahmin edilip düzeltilir.
    cols = []
    for cw in col_words:
        vlines = _group_lines(cw)
        cols.append(([statistics.fmean(w.yc for w in vl) for vl in vlines],
                     [_line_text(vl) for vl in vlines]))
    a, b = 0.0, 1.0
    mappings = []
    for _it in range(3):
        mappings = [_align(ys, [(v - a) / b for v in vys], row_h) for vys, _ in cols]
        # yalnızca güvenilir (artığı küçük) eşleşmelerle model kur
        pairs = [(ys[li], cols[c][0][vi]) for c, mp in enumerate(mappings)
                 for vi, li in mp.items()
                 if abs((cols[c][0][vi] - a) / b - ys[li]) < 0.35 * row_h]
        if len(pairs) < 4:
            break
        lx = [p[0] for p in pairs]
        vy = [p[1] for p in pairs]
        mx, my = statistics.fmean(lx), statistics.fmean(vy)
        sxx = sum((x - mx) ** 2 for x in lx)
        if sxx <= 0:
            break
        nb = sum((x - mx) * (y - my) for x, y in pairs) / sxx
        if not 0.8 < nb < 1.25:
            break
        na = my - nb * mx
        if abs(na - a) < 0.05 and abs(nb - b) < 1e-4:
            break
        a, b = na, nb
    row_values: list[dict] = [{} for _ in label_rows]
    for c, mapping in enumerate(mappings):
        vtexts = cols[c][1]
        for vi, li in mapping.items():
            prev = row_values[li].get(sample_nos[c])
            row_values[li][sample_nos[c]] = (prev + " " + vtexts[vi]) if prev else vtexts[vi]

    for (y, text, norm), match, vals in zip(label_rows, matches, row_values):
        if not vals:
            continue
        if match is None:
            report.unmatched.append(UnmatchedRow(text, norm, vals))
            continue
        if match.kind == "ignore":
            continue
        for sno, raw in vals.items():
            s = report.samples.setdefault(sno, ParsedSample(sno))
            target = s.meta if match.kind == "meta" else s.values
            if match.key == "sample_no":
                continue
            # aynı parametre birden çok satırda gelirse ilkini koru
            target.setdefault(match.key, raw.strip())
    for sno in sample_nos:
        report.samples.setdefault(sno, ParsedSample(sno))


# --------------------------------------------------- 1. sayfa bilgi alanları
_HEADER_PATTERNS = {
    "report_no": r"test\s*report\s*:?\s*([a-z]{2,6}\d{4,})",
    "registration_nr": r"registration\s*nr\.?\s*:?\s*([0-9a-z\-/]+)",
    "component": r"component\s*:\s*([^\s:]+)",
    "motor_no": r"equipment\s*desc\.?\s*:?\s*([^\s:]+)",
    "component_desc": r"component\s*desc\.?\s*:?\s*([^\s:]+)",
    "fleet_nr": r"fleet\s*nr\.?\s*:?\s*([0-9a-z\-/]+)",
    "ref_id": r"ref\.?\s*id\s*:?\s*([0-9a-z\-/]+)",
    "serial_nr": r"serial\s*nr\.?\s*:?\s*([0-9a-z\-/]+)",
    "sample_nr": r"sample\s*nr\.?\s*:?\s*([a-z]{2,6}\d{4,})",
    "date_received": r"received\s*date\s*:?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
    "date_taken": r"date\s*sample\s*taken\s*:\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
    "date_analysis": r"date\s*of\s*analysis\s*:\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
    "lubricant": r"lubricant\s*in\s*use\s*:?\s*([^\n]+)",
    "motor_hours": r"equipment\s*\(h\)\s*:\s*([\d.,]+)",
    "oil_hours": r"lubricant\s*\(h\)\s*:\s*([\d.,]+)",
    "topup": r"top-?\s*up\s*\([^)]*\)\s*:\s*([\d.,]+)",
    "technician": r"technician\s*:\s*(.+?)(?:\s{2,}|\s+administration|$)",
    "customer": r"customer\s*name\s*:?\s*(.+?)(?:\s{2,}|$)",
}


def _search(texts: list[str], pattern: str) -> str | None:
    rx = re.compile(pattern, re.MULTILINE)
    for t in texts:
        if not t:
            continue
        f = fold(t)
        m = rx.search(f)
        if m:
            return t[m.start(1):m.end(1)].strip()
    return None


def _parse_header(texts: list[str], report: ParsedReport):
    h = report.header
    for key, pat in _HEADER_PATTERNS.items():
        if key in h:
            continue
        v = _search(texts, pat)
        if v:
            if key == "report_no":
                report.report_no = report.report_no or v.upper()
            else:
                h[key] = v
    if "sample_nr" in h:
        h["sample_nr"] = h["sample_nr"].upper()
    full = texts[2] if len(texts) > 2 else texts[0]
    if "lab_diagnosis" not in h and full:
        lines = full.splitlines()
        for i, line in enumerate(lines):
            m = _DIAG_BANNER_RE.search(fold(line))
            if not m:
                continue
            h["lab_diagnosis"] = _COLOR_NAMES.get(m.group(1), m.group(1))
            if m.group(2):
                h["lab_diagnosis_date"] = m.group(2)
            comment = []
            for nxt in lines[i + 1:]:
                if re.search(r"analy[sz]ed by|diagnosed by", fold(nxt)):
                    break
                comment.append(nxt.strip())
            h["lab_comment"] = " ".join(c for c in comment if c).strip()
            break


# --------------------------------------------------------------- giriş
def parse_pdf(path: str | Path, matcher: LabelMatcher | None = None,
              allow_ocr: bool = True) -> ParsedReport:
    path = str(path)
    matcher = matcher or LabelMatcher()
    report = ParsedReport(file=path)
    try:
        pages = _words_from_pdf(path)
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"PDF açılamadı: {exc}") from exc
    if sum(len(p["words"]) for p in pages) < 30:
        if not allow_ocr:
            raise ParseError("PDF metin katmanı içermiyor (taranmış belge).")
        pages = _words_from_ocr(path)
        report.used_ocr = True
        report.warnings.append("PDF taranmış görüntü; OCR kullanıldı. Değerleri mutlaka kontrol edin.")

    for p in pages:
        _parse_header(p["texts"], report)
        _parse_table(p["words"], matcher, report)

    finalize_report(report)
    return report


def finalize_report(report: ParsedReport):
    """Başlık bilgilerini ana numuneye işler, eksikleri uyarı olarak ekler."""
    h = report.header
    main = report.main_sample_no
    if not report.samples:
        report.warnings.append("Rapor içinde sonuç tablosu bulunamadı.")
        return
    ms = report.samples.get(main)
    if ms is not None:
        for key in ("date_taken", "date_analysis", "motor_hours", "oil_hours", "topup"):
            if key not in ms.meta and h.get(key):
                ms.meta[key] = h[key]
        if "date_received" in h:
            ms.meta.setdefault("date_received", h["date_received"])
    # Tutarlılık kontrolleri
    for s in report.samples.values():
        if not s.values:
            report.warnings.append(f"{s.sample_no}: hiç ölçüm değeri okunamadı.")
        if s.meta.get("date_taken") and not parse_date(s.meta["date_taken"]):
            report.warnings.append(f"{s.sample_no}: tarih okunamadı ({s.meta['date_taken']}).")
    if not h.get("motor_no"):
        report.warnings.append("Motor numarası (Equipment Desc.) bulunamadı; elle girin.")
    for u in report.unmatched:
        report.warnings.append(f"Tanınmayan satır: '{u.label}'")


def lab_info_json(report: ParsedReport) -> str:
    keep = ("registration_nr", "component", "component_desc", "fleet_nr", "ref_id",
            "serial_nr", "technician", "customer", "lab_diagnosis_date", "lubricant")
    return json.dumps({k: report.header[k] for k in keep if report.header.get(k)},
                      ensure_ascii=False)
