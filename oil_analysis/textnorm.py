"""Metin normalizasyonu, sayı ve tarih ayrıştırma yardımcıları.

Raporlar farklı kişilerce hazırlandığında aynı alan farklı yazılabiliyor
("Ca mg/kg", "Kalsiyum mg/kg", "Calcium"...). Buradaki fonksiyonlar etiketleri
karşılaştırılabilir tek bir biçime indirger.
"""
from __future__ import annotations

import datetime as _dt
import re
import unicodedata

# Tek karakter -> tek karakter eşleşme (uzunluk korunur; regex indeksleri
# orijinal metinde de geçerli kalır).
_FOLD_MAP = {
    "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "İ": "i", "I": "i",
    "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u",
    "â": "a", "Â": "a", "î": "i", "Î": "i", "û": "u", "Û": "u",
    "µ": "u", "μ": "u", "²": "2", "³": "3", "°": " ", "º": " ",
    " ": " ", "’": "'", "‘": "'", "–": "-", "—": "-",
}


def fold(text: str) -> str:
    """Türkçe karakterleri ASCII'ye indirger ve küçük harfe çevirir.

    Uzunluk korunur: fold(s)[i] her zaman s[i]'ye karşılık gelir.
    """
    out = []
    for ch in text:
        m = _FOLD_MAP.get(ch)
        if m is None:
            low = ch.lower()
            if len(low) != 1:
                low = ch
            dec = unicodedata.normalize("NFKD", low)
            base = "".join(c for c in dec if not unicodedata.combining(c))
            m = base if len(base) == 1 else low
        out.append(m)
    return "".join(out)


_UNIT_PATTERNS = [
    r"mg\s*koh\s*/\s*g", r"mgkoh\s*/?\s*g", r"mg\s*/\s*kg", r"\bppm\b",
    r"mm\s*2\s*/\s*s", r"\bcst\b", r"a\s*/\s*0[.,]?\s*1\s*mm", r"a\s*/\s*cm",
    r"\(\s*(?:h|sa|saat|gallon|gal|ppm|%)?\s*\)", r"%",
]
_UNIT_RE = re.compile("|".join(_UNIT_PATTERNS))


def unit_hint(label: str) -> str | None:
    """Etikette geçen birimden ipucu çıkarır ('pct', 'mgkg' veya None)."""
    f = fold(label)
    if "%" in f:
        return "pct"
    if re.search(r"mg\s*/\s*kg|\bppm\b", f):
        return "mgkg"
    return None


def normalize_label(label: str) -> str:
    """Etiketi karşılaştırma anahtarına çevirir.

    'Viskozite 40°C mm²/s' -> 'viskozite 40 c'
    'Ca mg/kg'             -> 'ca'
    'Motor Çalışma Süresi (sa)' -> 'motor calisma suresi'
    """
    f = fold(label or "")
    f = _UNIT_RE.sub(" ", f)
    f = re.sub(r"[^a-z0-9]+", " ", f)
    return re.sub(r"\s+", " ", f).strip()


# ----------------------------------------------------------------- sayılar
MISSING_TOKENS = {"imp", "n/a", "na", "-", "--", "", "nd", "yok", "none"}
_NUM_RE = re.compile(r"^[<>]?\s*-?\d+(?:[.,]\d+)*$")


def parse_number(raw) -> float | None:
    """'1266,3' -> 1266.3, '0.00' -> 0.0, 'IMP' -> None, '<1' -> 1.0."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().replace(" ", "")
    if fold(s) in MISSING_TOKENS:
        return None
    if not _NUM_RE.match(s):
        return None
    s = s.lstrip("<>")
    if "," in s and "." in s:
        # Hangisi sondaysa ondalık ayıracı odur.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------- tarihler
_DATE_RE = re.compile(r"(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{2,4})")
_ISO_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


def parse_date(raw) -> str | None:
    """Gün/ay/yıl biçimindeki tarihi ISO (YYYY-MM-DD) metne çevirir."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, _dt.datetime):
        return raw.date().isoformat()
    if isinstance(raw, _dt.date):
        return raw.isoformat()
    s = str(raw).strip()
    m = _ISO_RE.search(s)
    if m:
        try:
            return _dt.date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        except ValueError:
            return None
    m = _DATE_RE.search(s)
    if not m:
        return None
    d, mo, y = int(m[1]), int(m[2]), int(m[3])
    if y < 100:
        y += 2000
    try:
        return _dt.date(y, mo, d).isoformat()
    except ValueError:
        # Ay/gün yer değiştirmiş olabilir (ör. Excel'de m/d)
        try:
            return _dt.date(y, d, mo).isoformat()
        except ValueError:
            return None


def format_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return _dt.date.fromisoformat(iso).strftime("%d.%m.%Y")
    except ValueError:
        return iso


def fmt_num(v, digits: int = 2) -> str:
    if v is None:
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f != f:  # NaN
        return ""
    if abs(f) >= 1000 or f == int(f):
        return f"{f:.0f}" if f == int(f) else f"{f:.1f}"
    return f"{f:.{digits}f}".rstrip("0").rstrip(".")
