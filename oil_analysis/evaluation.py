"""Numune değerlendirme motoru.

Bir ölçüm şu kurallarla değerlendirilir (en kötü sonuç geçerli):
  1. Sabit limitler (Ayarlar > Sabit Limitler; ör. glikol > 0)
  2. Viskozite 100°C için yağ sınıfı aralığı (0W40: 12.5-16.3, 5W30: 9.3-12.5)
  3. Taze (sıfır) yağa göre değişim:
       - Katkı elementleri (Ca, P, Zn, Mg, B, Mo, Ba): % düşüş
       - Viskozite 40/100°C: % değişim (±10 uyarı / ±20 alarm)
       - TBN: taze yağın %60'ı altı uyarı, %50'si altı alarm; TBN ≤ TAN alarm
  4. İstatistiksel limitler: referans popülasyonundan (aynı yağ tipi / numune
     tipi / platform grubu - ayarlanabilir) hesaplanan uyarı ve alarm limitleri
  5. Artış hızı (ppm/100 sa): aynı yağ dönemindeki bir önceki numuneye göre
     (yoksa taze yağa göre) normalize edilmiş artışın istatistiksel limitleri
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .db import Sample
from .parameters import ADDITIVE_KEYS, CONTAMINANT, FTIR, WEAR, ParamDef
from .stats import Limits, classify, compute_limits
from .textnorm import fmt_num

STATUS_TEXT = {None: "—", 0: "Normal", 1: "Uyarı", 2: "Alarm"}
GROUP_LABELS = {"oil_type": "Yağ", "sample_type": "Numune tipi",
                "platform_group": "Platform grubu", "platform_code": "Platform"}
RATE_CATEGORIES = {WEAR, CONTAMINANT, FTIR}


@dataclass
class ParamEval:
    key: str
    value: float | None
    status: int | None = None
    reasons: list = field(default_factory=list)
    limits: Limits | None = None
    rate: float | None = None
    rate_limits: Limits | None = None
    fresh: float | None = None
    change_pct: float | None = None


def _worse(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def _attr(s: Sample, key: str):
    return getattr(s, key, None) or ""


class Evaluator:
    def __init__(self, samples: list[Sample], params: list[ParamDef], settings: dict):
        self.samples = samples
        self.params = params
        self.pmap = {p.key: p for p in params}
        self.settings = settings
        self.population = [s for s in samples if not s.is_fresh]
        self.fresh_by_oil: dict[str, Sample] = {}
        for s in sorted((s for s in samples if s.is_fresh), key=Sample.sort_key):
            self.fresh_by_oil[s.oil_type or ""] = s
        self.rate_keys = {p.key for p in params
                          if p.direction == "up" and p.category in RATE_CATEGORIES}
        self.rates = self._compute_rates()
        self._lim_cache: dict = {}
        self._eval_cache: dict = {}
        self._pop_cache: dict = {}

    # ---------------------------------------------------------------- taze yağ
    def fresh_for(self, s: Sample) -> Sample | None:
        return self.fresh_by_oil.get(s.oil_type or "")

    # ------------------------------------------------------------ artış hızı
    def previous_in_period(self, s: Sample) -> Sample | None:
        """Aynı motorun aynı yağ dönemindeki bir önceki numunesi."""
        if not s.motor_no or s.oil_hours is None:
            return None
        best = None
        for p in self.population:
            if p is s or p.motor_no != s.motor_no or p.oil_hours is None:
                continue
            if p.oil_hours >= s.oil_hours:
                continue
            if s.date_taken and p.date_taken and p.date_taken > s.date_taken:
                continue
            if s.motor_hours is not None and p.motor_hours is not None:
                d_m = s.motor_hours - p.motor_hours
                d_o = s.oil_hours - p.oil_hours
                if d_m <= 0 or abs(d_m - d_o) > max(5.0, 0.1 * d_o):
                    continue  # arada yağ değişimi olmuş
            if best is None or p.oil_hours > best.oil_hours:
                best = p
        return best

    def _compute_rates(self) -> dict[int, dict[str, float]]:
        out: dict[int, dict[str, float]] = {}
        for s in self.population:
            r: dict[str, float] = {}
            if s.oil_hours and s.oil_hours > 0:
                prev = self.previous_in_period(s)
                fresh = self.fresh_for(s)
                for key in self.rate_keys:
                    v = s.values.get(key)
                    if v is None:
                        continue
                    if prev is not None and prev.values.get(key) is not None:
                        dh = s.oil_hours - prev.oil_hours
                        if dh > 0:
                            r[key] = (v - prev.values[key]) / dh * 100.0
                            continue
                    base = fresh.values.get(key) if fresh is not None else None
                    r[key] = (v - (base or 0.0)) / s.oil_hours * 100.0
            out[s.id] = r
        return out

    # ------------------------------------------------------- referans grubu
    def ref_population(self, s: Sample) -> tuple[list[Sample], str]:
        keys = list(self.settings.get("group_by", []))
        min_n = int(self.settings.get("min_n", 6))
        while True:
            sig = tuple((k, _attr(s, k)) for k in keys)
            if sig not in self._pop_cache:
                pop = [p for p in self.population if all(_attr(p, k) == v for k, v in sig)]
                desc = ", ".join(f"{GROUP_LABELS.get(k, k)}: {v or '-'}" for k, v in sig) or "Tüm numuneler"
                self._pop_cache[sig] = (pop, f"{desc} (n={len(pop)})")
            pop, desc = self._pop_cache[sig]
            if len(pop) >= min_n or not keys:
                return pop, desc
            keys.pop()

    def limits(self, s: Sample, key: str) -> Limits:
        pop, desc = self.ref_population(s)
        ck = (desc, key, "abs")
        if ck not in self._lim_cache:
            p = self.pmap.get(key)
            lim = compute_limits([q.values.get(key) for q in pop],
                                 p.direction if p else "up", self.settings)
            lim.note = (lim.note + " | " if lim.note else "") + desc
            self._lim_cache[ck] = lim
        return self._lim_cache[ck]

    def rate_limits(self, s: Sample, key: str) -> Limits | None:
        if key not in self.rate_keys or not self.settings.get("use_rate", True):
            return None
        pop, desc = self.ref_population(s)
        ck = (desc, key, "rate")
        if ck not in self._lim_cache:
            vals = [self.rates.get(q.id, {}).get(key) for q in pop]
            lim = compute_limits(vals, "up", self.settings)
            lim.note = (lim.note + " | " if lim.note else "") + desc
            self._lim_cache[ck] = lim
        return self._lim_cache[ck]

    # ----------------------------------------------------------- değerlendirme
    def evaluate(self, s: Sample) -> dict[str, ParamEval]:
        if s.id in self._eval_cache:
            return self._eval_cache[s.id]
        res: dict[str, ParamEval] = {}
        if s.is_fresh:
            for key, v in s.values.items():
                res[key] = ParamEval(key, v, None, ["Sıfır yağ referansı"])
            self._eval_cache[s.id] = res
            return res
        st = self.settings
        fresh = self.fresh_for(s)
        fixed = st.get("fixed_limits", {}) or {}
        for p in self.params:
            v = s.values.get(p.key)
            if v is None:
                continue
            e = ParamEval(p.key, v)
            # 1) sabit limitler
            fl = fixed.get(p.key)
            if fl:
                lim = Limits(lo_alarm=fl.get("lo_alarm"), lo_warn=fl.get("lo_warn"),
                             hi_warn=fl.get("hi_warn"), hi_alarm=fl.get("hi_alarm"))
                c = classify(v, lim)
                if c:
                    e.reasons.append(f"Sabit limit aşıldı ({_lim_text(lim)})")
                e.status = _worse(e.status, c)
            # 2) viskozite sınıf aralığı
            if p.key == "visc100" and s.oil_type:
                rng = (st.get("visc_limits") or {}).get(s.oil_type.upper())
                if rng and len(rng) == 2:
                    lo, hi = float(rng[0]), float(rng[1])
                    if v < lo or v > hi:
                        e.status = 2
                        e.reasons.append(f"{s.oil_type} sınıf aralığı dışında ({lo}-{hi} cSt)")
                    else:
                        e.status = _worse(e.status, 0)
            # 3) taze yağa göre değişim
            fv = fresh.values.get(p.key) if fresh is not None else None
            e.fresh = fv
            if fv not in (None, 0):
                e.change_pct = (v - fv) / fv * 100.0
                if p.key in ADDITIVE_KEYS:
                    drop = -e.change_pct
                    if drop >= st["additive_drop_alarm"]:
                        e.status = 2
                        e.reasons.append(f"Katkı tükenmesi %{drop:.0f} (taze: {fmt_num(fv)})")
                    elif drop >= st["additive_drop_warn"]:
                        e.status = _worse(e.status, 1)
                        e.reasons.append(f"Katkı azalması %{drop:.0f} (taze: {fmt_num(fv)})")
                    else:
                        e.status = _worse(e.status, 0)
                elif p.key in ("visc40", "visc100"):
                    ch = abs(e.change_pct)
                    if ch >= st["visc_change_alarm"]:
                        e.status = 2
                        e.reasons.append(f"Viskozite değişimi %{e.change_pct:+.0f} (taze: {fmt_num(fv)})")
                    elif ch >= st["visc_change_warn"]:
                        e.status = _worse(e.status, 1)
                        e.reasons.append(f"Viskozite değişimi %{e.change_pct:+.0f} (taze: {fmt_num(fv)})")
                    else:
                        e.status = _worse(e.status, 0)
                elif p.key == "tbn":
                    ratio = v / fv
                    if ratio < st["tbn_ratio_alarm"]:
                        e.status = 2
                        e.reasons.append(f"TBN taze yağın %{ratio*100:.0f}'i")
                    elif ratio < st["tbn_ratio_warn"]:
                        e.status = _worse(e.status, 1)
                        e.reasons.append(f"TBN taze yağın %{ratio*100:.0f}'i")
            if p.key == "tbn" and s.values.get("tan") is not None and v <= s.values["tan"]:
                e.status = 2
                e.reasons.append("TBN ≤ TAN")
            # 4) istatistiksel limitler
            lim = self.limits(s, p.key)
            e.limits = lim
            c = classify(v, lim)
            if c:
                e.reasons.append(("İstatistiksel alarm" if c == 2 else "İstatistiksel uyarı")
                                 + f" ({_lim_text(lim)})")
            e.status = _worse(e.status, c)
            # 5) artış hızı
            rl = self.rate_limits(s, p.key)
            e.rate = self.rates.get(s.id, {}).get(p.key)
            e.rate_limits = rl
            if rl is not None and e.rate is not None:
                c = classify(e.rate, rl)
                if c:
                    e.reasons.append(f"Artış hızı {fmt_num(e.rate)}/100sa "
                                     f"({'alarm' if c == 2 else 'uyarı'} > "
                                     f"{fmt_num(rl.hi_alarm if c == 2 else rl.hi_warn)})")
                e.status = _worse(e.status, c)
            res[p.key] = e
        self._eval_cache[s.id] = res
        return res

    def overall(self, s: Sample) -> tuple[int | None, list[str]]:
        ev = self.evaluate(s)
        worst = None
        flagged = []
        for key, e in ev.items():
            worst = _worse(worst, e.status)
            if e.status and e.status > 0:
                name = self.pmap[key].name.split(" (")[0] if key in self.pmap else key
                flagged.append((e.status, name))
        flagged.sort(key=lambda t: -t[0])
        return worst, [f"{n}{'!' if st == 2 else ''}" for st, n in flagged]


def _lim_text(lim: Limits) -> str:
    parts = []
    if lim.lo_alarm is not None or lim.lo_warn is not None:
        parts.append(f"alt: {fmt_num(lim.lo_warn)}/{fmt_num(lim.lo_alarm)}")
    if lim.hi_warn is not None or lim.hi_alarm is not None:
        parts.append(f"üst: {fmt_num(lim.hi_warn)}/{fmt_num(lim.hi_alarm)}")
    return ", ".join(parts)
