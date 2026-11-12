"""İstatistik ve limit hesaplama.

Kaynaklar / yaklaşım:
* ASTM D7720 - Yağ analizinde ölçüm alarm limitlerinin istatistiksel olarak
  belirlenmesi kılavuzu: popülasyon dağılımından uyarı/alarm limitleri,
  çarpık dağılımlar için parametrik olmayan (yüzdelik) yaklaşım.
* JOAP (Joint Oil Analysis Program) yaklaşımı: yalnız mutlak değer değil,
  çalışma saatine göre artış hızı (ppm / saat) limitleri.
* Aşınma metali verileri genelde sağa çarpıktır; bu yüzden log-normal seçenek.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

METHODS = {
    "normal": "Normal dağılım (μ + kσ)",
    "lognormal": "Log-normal (çarpık veriler için)",
    "percentile": "Yüzdelik (parametrik olmayan)",
}


@dataclass
class Limits:
    n: int = 0
    n_used: int = 0
    lo_alarm: float | None = None
    lo_warn: float | None = None
    hi_warn: float | None = None
    hi_alarm: float | None = None
    note: str = ""

    @property
    def valid(self):
        return any(v is not None for v in (self.lo_alarm, self.lo_warn, self.hi_warn, self.hi_alarm))


def clean(values) -> np.ndarray:
    arr = np.array([v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))],
                   dtype=float)
    return arr


def describe(values) -> dict:
    x = clean(values)
    n = len(x)
    if n == 0:
        return {"n": 0}
    return {
        "n": n,
        "min": float(x.min()),
        "max": float(x.max()),
        "mean": float(x.mean()),
        "std": float(x.std(ddof=1)) if n > 1 else 0.0,
        "median": float(np.median(x)),
        "p05": float(np.percentile(x, 5)),
        "p95": float(np.percentile(x, 95)),
    }


def trim_outliers(x: np.ndarray, sides: set[str], z: float = 3.0, max_iter: int = 10) -> np.ndarray:
    """Uç değer ayıklama (yalnızca kötü yöndeki uç değerler).

    1) Medyan/MAD tabanlı dayanıklı z-skoru (Iglewicz-Hoaglin, |z| > 3.5).
       Küçük örneklemde tek bir büyük değerin σ'yı şişirip kendini
       gizlemesini (maskeleme) önler.
    2) Ardından tekrarlı 3σ ayıklama.
    """
    x = np.asarray(x, dtype=float)
    if len(x) >= 5:
        med = np.median(x)
        mad = np.median(np.abs(x - med))
        if mad > 0:
            rz = 0.6745 * (x - med) / mad
            mask = np.ones(len(x), dtype=bool)
            if "up" in sides:
                mask &= rz <= 3.5
            if "down" in sides:
                mask &= rz >= -3.5
            if mask.sum() >= max(5, int(0.75 * len(x))):
                x = x[mask]
    for _ in range(max_iter):
        if len(x) < 5:
            break
        m, s = x.mean(), x.std(ddof=1)
        if s == 0:
            break
        mask = np.ones(len(x), dtype=bool)
        if "up" in sides:
            mask &= x <= m + z * s
        if "down" in sides:
            mask &= x >= m - z * s
        if mask.all():
            break
        x = x[mask]
    return x


def compute_limits(values, direction: str, settings: dict) -> Limits:
    x = clean(values)
    lim = Limits(n=len(x))
    min_n = int(settings.get("min_n", 6))
    if len(x) < min_n:
        lim.note = f"Yetersiz veri (n={len(x)} < {min_n})"
        return lim
    sides = {"up", "down"} if direction == "both" else {direction}
    if settings.get("trim_outliers", True):
        x = trim_outliers(x, sides)
    lim.n_used = len(x)
    method = settings.get("method", "normal")
    kw, ka = float(settings.get("k_warn", 2)), float(settings.get("k_alarm", 3))
    pw, pa = float(settings.get("pct_warn", 95)), float(settings.get("pct_alarm", 99))

    if method == "percentile":
        hi_w, hi_a = np.percentile(x, pw), np.percentile(x, pa)
        lo_w, lo_a = np.percentile(x, 100 - pw), np.percentile(x, 100 - pa)
    elif method == "lognormal":
        if (x < 0).any():
            lim.note = "Negatif değer var; normal yöntem kullanıldı"
            m, s = x.mean(), x.std(ddof=1)
            hi_w, hi_a, lo_w, lo_a = m + kw * s, m + ka * s, m - kw * s, m - ka * s
        else:
            y = np.log1p(x)
            m, s = y.mean(), y.std(ddof=1)
            hi_w, hi_a = np.expm1(m + kw * s), np.expm1(m + ka * s)
            lo_w, lo_a = np.expm1(m - kw * s), np.expm1(m - ka * s)
    else:
        m, s = x.mean(), x.std(ddof=1)
        hi_w, hi_a, lo_w, lo_a = m + kw * s, m + ka * s, m - kw * s, m - ka * s

    if float(np.ptp(x)) == 0.0:
        lim.note = "Değişkenlik yok (tüm değerler eşit)"
        return lim
    if "up" in sides:
        lim.hi_warn, lim.hi_alarm = float(hi_w), float(hi_a)
    if "down" in sides:
        lim.lo_warn, lim.lo_alarm = max(float(lo_w), 0.0), max(float(lo_a), 0.0)
    return lim


def classify(value: float | None, lim: Limits) -> int | None:
    """0: normal, 1: uyarı, 2: alarm, None: değerlendirilemedi."""
    if value is None or not lim.valid:
        return None
    if lim.hi_alarm is not None and value > lim.hi_alarm:
        return 2
    if lim.lo_alarm is not None and value < lim.lo_alarm:
        return 2
    if lim.hi_warn is not None and value > lim.hi_warn:
        return 1
    if lim.lo_warn is not None and value < lim.lo_warn:
        return 1
    return 0
