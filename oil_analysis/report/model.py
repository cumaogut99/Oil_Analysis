"""Rapor içerik modeli.

Rapor; kapak bilgisi + sıralı bloklardan (başlık, paragraf, tablo, görsel...)
oluşur. PDF ve DOCX yazıcıları aynı modeli kullanır; böylece iki çıktı aynı
içeriğe sahip olur. İçindekiler, 1. ve 2. seviye başlıklardan üretilir.
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
from dataclasses import dataclass, field

from ..evaluation import STATUS_TEXT, Evaluator
from ..parts import diagnose
from ..stats import METHODS, compute_limits, describe
from ..textnorm import fmt_num, format_date

# (anahtar, başlık, varsayılan seçili mi)
SECTIONS = [
    ("summary", "Özet", True),
    ("sample_list", "Numune Listesi", True),
    ("alarm_details", "Uyarı ve Alarm Detayları", True),
    ("user_comments", "Değerlendirme Yorumları", True),
    ("trends", "Trend Grafikleri", True),
    ("parts", "Parça Tahmini", True),
    ("stats", "İstatistikler ve Limitler", False),
    ("sgs_comments", "SGS (Analiz Firması) Yorumları", False),
    ("exclusions", "İstatistikten Hariç Tutulan Değerler", False),
]


# ------------------------------------------------------------------- bloklar
@dataclass
class Heading:
    text: str
    level: int = 1  # 1-2 içindekilerde, 3 değil


@dataclass
class Para:
    text: str
    style: str = "normal"  # normal | muted | small


@dataclass
class Table:
    headers: list
    rows: list
    statuses: list | None = None   # rows ile aynı boyutta; hücre durum rengi (0/1/2/None)
    widths: list | None = None     # göreli sütun genişlikleri
    small: bool = True


@dataclass
class Image:
    path: str
    width_cm: float = 17.0
    caption: str = ""


@dataclass
class KeyValues:
    pairs: list


@dataclass
class PageBreak:
    pass


@dataclass
class Report:
    title: str
    subtitle: str = ""
    author: str = ""
    date: str = ""
    description: str = ""
    cover_pairs: list = field(default_factory=list)
    blocks: list = field(default_factory=list)
    tmpdir: str = ""

    def headings(self, max_level=2):
        return [b for b in self.blocks if isinstance(b, Heading) and b.level <= max_level]


@dataclass
class ReportOptions:
    title: str = "Motor Yağı Analiz Raporu"
    subtitle: str = ""
    author: str = ""
    description: str = ""
    sections: list = field(default_factory=lambda: [k for k, _t, d in SECTIONS if d])
    scope_desc: str = "Tüm numuneler"
    sample_list_mode: str = "all"        # all | flagged
    trend_keys: list | None = None       # None -> uyarı/alarm veren parametreler
    trend_xkey: str = "motor_hours"
    trend_per_motor: bool = False
    max_detail_samples: int = 200


# ---------------------------------------------------------------- oluşturma
def _pname(pmap, key):
    p = pmap.get(key)
    return p.name if p else key


def _plabel(pmap, key):
    p = pmap.get(key)
    if p is None:
        return key
    return f"{p.name} [{p.unit}]" if p.unit else p.name


def _lim(lo, hi):
    parts = []
    if lo is not None:
        parts.append(f"< {fmt_num(lo)}")
    if hi is not None:
        parts.append(f"> {fmt_num(hi)}")
    return "  ".join(parts)


def build_report(samples, params, settings, ev: Evaluator, part_sources, opts: ReportOptions) -> Report:
    """samples: kapsamdaki numuneler (filtrelenmiş). Sıfır yağlar özet dışı tutulur."""
    pmap = {p.key: p for p in params}
    scope = sorted([s for s in samples if not s.is_fresh], key=lambda s: (s.motor_no or "~", s.sort_key()))
    tmpdir = tempfile.mkdtemp(prefix="yag_rapor_")
    today = dt.date.today().strftime("%d.%m.%Y")
    dates = sorted(s.date_taken for s in scope if s.date_taken)
    rng = f"{format_date(dates[0])} – {format_date(dates[-1])}" if dates else "—"
    status = {s.id: ev.overall(s) for s in scope}
    cnt = {0: 0, 1: 0, 2: 0}
    for st, _f in status.values():
        if st in cnt:
            cnt[st] += 1
    motors = sorted({s.motor_no for s in scope if s.motor_no})
    rep = Report(title=opts.title, subtitle=opts.subtitle, author=opts.author, date=today,
                 description=opts.description, tmpdir=tmpdir)
    rep.cover_pairs = [("Kapsam", opts.scope_desc), ("Numune tarihi aralığı", rng),
                       ("Numune sayısı", str(len(scope))), ("Motor sayısı", str(len(motors))),
                       ("Durum dağılımı", f"Normal {cnt[0]} • Uyarı {cnt[1]} • Alarm {cnt[2]}"),
                       ("Rapor tarihi", today)]
    if opts.author:
        rep.cover_pairs.append(("Hazırlayan", opts.author))
    B = rep.blocks
    flagged = [s for s in scope if (status[s.id][0] or 0) >= 1]
    sec = set(opts.sections)

    def section(title):
        if B:
            B.append(PageBreak())
        B.append(Heading(title, 1))

    # ---------------------------------------------------------------- özet
    if "summary" in sec:
        section("Özet")
        B.append(KeyValues(rep.cover_pairs[:5] + [("Motorlar", ", ".join(motors) or "—")]))
        if opts.description:
            B.append(Para(opts.description))
        freq = {}
        for s in scope:
            for k, e in ev.evaluate(s).items():
                if e.status in (1, 2):
                    f = freq.setdefault(k, [0, 0, set()])
                    f[e.status - 1] += 1
                    f[2].add(s.motor_no)
        B.append(Heading("En sık uyarı/alarm veren parametreler", 2))
        if freq:
            rows, sts = [], []
            for k, (w, a, ms) in sorted(freq.items(), key=lambda t: -(t[1][0] + t[1][1])):
                rows.append([_plabel(pmap, k), str(w), str(a), str(len(ms))])
                sts.append([None, 1 if w else None, 2 if a else None, None])
            B.append(Table(["Parametre", "Uyarı", "Alarm", "Motor sayısı"], rows, sts, [5, 1.3, 1.3, 1.6]))
        else:
            B.append(Para("Kapsamdaki numunelerde uyarı veya alarm yok.", "muted"))
        B.append(Heading("Değerlendirme yöntemi", 2))
        m = settings.get("method", "normal")
        B.append(Para(
            f"İstatistiksel limit yöntemi: {METHODS.get(m, m)} "
            + (f"(uyarı P{settings['pct_warn']:g}, alarm P{settings['pct_alarm']:g})" if m == "percentile"
               else f"(uyarı μ±{settings['k_warn']:g}σ, alarm μ±{settings['k_alarm']:g}σ)")
            + f"; en az {settings['min_n']} numune; uç değer ayıklama "
            + ("açık" if settings.get("trim_outliers") else "kapalı") + ". "
            "Referans grubu: " + ", ".join(settings.get("group_by", [])) + ". "
            "Ek kurallar: yağ sınıfı viskozite aralığı, taze yağa göre değişim, artış hızı (ppm/100 sa) "
            "ve sabit limitler. İstatistikten hariç tutulan değerler limit hesabına katılmaz.", "small"))

    # ------------------------------------------------------- numune listesi
    if "sample_list" in sec:
        section("Numune Listesi")
        lst = flagged if opts.sample_list_mode == "flagged" else scope
        if opts.sample_list_mode == "flagged":
            B.append(Para("Yalnızca uyarı veya alarm veren numuneler listelenmiştir.", "muted"))
        rows, sts = [], []
        for s in lst:
            st, names = status[s.id]
            rows.append([s.sample_no, s.motor_no or "", format_date(s.date_taken), s.sample_type,
                         fmt_num(s.motor_hours), fmt_num(s.oil_hours), STATUS_TEXT.get(st, "—"),
                         ", ".join(n.rstrip("!") for n in names)])
            sts.append([None] * 6 + [st, None])
        B.append(Table(["Analiz No", "Motor", "Tarih", "Tip", "Motor sa", "Yağ sa", "Durum",
                        "Dikkat gerektirenler"], rows, sts, [1.6, 1.5, 1.3, 1.1, 1.1, 0.9, 1.0, 3.5]))

    # ------------------------------------------------- uyarı/alarm detayları
    if "alarm_details" in sec:
        section("Uyarı ve Alarm Detayları")
        if not flagged:
            B.append(Para("Kapsamdaki numunelerde uyarı veya alarm yok.", "muted"))
        for s in flagged[:opts.max_detail_samples]:
            st = status[s.id][0]
            B.append(Heading(f"{s.sample_no} — {s.motor_no or '-'} — {format_date(s.date_taken)} — "
                             f"{STATUS_TEXT.get(st)}", 3))
            B.append(Para(f"Motor sa: {fmt_num(s.motor_hours) or '-'} • Yağ sa: {fmt_num(s.oil_hours) or '-'} • "
                          f"Tip: {s.sample_type} • Yağ: {s.oil_type or '-'}"
                          + (f" • SGS: {s.lab_diagnosis}" if s.lab_diagnosis else ""), "small"))
            rows, sts = [], []
            for k, e in ev.evaluate(s).items():
                if e.status not in (1, 2):
                    continue
                lim = e.limits
                rows.append([_plabel(pmap, k), fmt_num(e.value, 3),
                             _lim(lim.lo_warn, lim.hi_warn) if lim else "",
                             _lim(lim.lo_alarm, lim.hi_alarm) if lim else "", "; ".join(e.reasons)])
                sts.append([None, e.status, None, None, None])
            B.append(Table(["Parametre", "Değer", "Uyarı limiti", "Alarm limiti", "Açıklama"], rows, sts,
                           [2.6, 1.0, 1.4, 1.4, 5.0]))
            if s.user_comment:
                B.append(Para("Değerlendirme: " + s.user_comment))
        if len(flagged) > opts.max_detail_samples:
            B.append(Para(f"... ve {len(flagged) - opts.max_detail_samples} numune daha.", "muted"))

    # -------------------------------------------------------------- yorumlar
    if "user_comments" in sec:
        section("Değerlendirme Yorumları")
        cm = [s for s in scope if s.user_comment]
        if cm:
            rows = [[s.sample_no, s.motor_no or "", format_date(s.date_taken),
                     STATUS_TEXT.get(status[s.id][0], "—"), s.user_comment] for s in cm]
            sts = [[None, None, None, status[s.id][0], None] for s in cm]
            B.append(Table(["Analiz No", "Motor", "Tarih", "Durum", "Yorum"], rows, sts, [1.6, 1.5, 1.3, 1.0, 6.5]))
        else:
            B.append(Para("Kapsamdaki numunelerde değerlendirme yorumu girilmemiş.", "muted"))

    # ---------------------------------------------------------------- trend
    if "trends" in sec:
        section("Trend Grafikleri")
        keys = opts.trend_keys
        if keys is None:
            keys = [p.key for p in params if any(
                (ev.evaluate(s).get(p.key) and ev.evaluate(s)[p.key].status in (1, 2)) for s in scope)]
            B.append(Para("Kapsamda uyarı/alarm veren parametreler gösterilmektedir. Kesikli çizgiler: "
                          "turuncu uyarı, kırmızı alarm limiti.", "muted"))
        else:
            B.append(Para("Kesikli çizgiler: turuncu uyarı, kırmızı alarm limiti. Halkalı noktalar "
                          "uyarı/alarm veren numunelerdir.", "muted"))
        if not keys:
            B.append(Para("Gösterilecek parametre yok.", "muted"))
        n = 0
        for k in keys:
            if not any(s.values.get(k) is not None for s in scope):
                continue
            B.append(Heading(_pname(pmap, k), 2))
            groups = ([[s for s in scope if s.motor_no == m] for m in motors]
                      if opts.trend_per_motor and len(motors) > 1 else [scope])
            for g in groups:
                if not any(s.values.get(k) is not None for s in g):
                    continue
                n += 1
                path = os.path.join(tmpdir, f"trend_{n}.png")
                title = f"{_pname(pmap, k)} — {g[0].motor_no}" if len(groups) > 1 else None
                from .charts import trend_chart
                trend_chart(path, g, k, ev, settings, pmap, opts.trend_xkey, title=title)
                B.append(Image(path, 17.0))

    # ---------------------------------------------------------- parça tahmini
    if "parts" in sec:
        section("Parça Tahmini")
        B.append(Para("Önceki numuneye göre anlamlı artan veya uyarı/alarm veren malzemelerin, Malzeme "
                      "Kaynakları'nda tanımlı olası kaynak parçaları puanlanmıştır (alarm 3, uyarı 2, "
                      "artış 1). Bu bir ön tahmindir; kesin teşhis için muayene gerekir.", "small"))
        any_row = False
        for s in flagged[:opts.max_detail_samples]:
            changes, ranked = diagnose(s, ev, part_sources, settings)
            if not ranked:
                continue
            any_row = True
            B.append(Heading(f"{s.sample_no} — {s.motor_no or '-'} — {format_date(s.date_taken)}", 3))
            B.append(Para("Değişen malzemeler: " + ", ".join(
                f"{_pname(pmap, c.key).split(' (')[0]} {fmt_num(c.prev)}→{fmt_num(c.value)}" for c in changes),
                "small"))
            top = ranked[0].score
            rows = [[p.part, f"{p.score:g}", ", ".join(p.elements)] for p in ranked[:6]]
            sts = [[2 if p.score >= top and len(p.elements) > 1 else (1 if p.score >= 0.6 * top else None),
                    None, None] for p in ranked[:6]]
            B.append(Table(["Olası parça", "Puan", "İşaret eden malzemeler"], rows, sts, [5, 1, 4]))
        if not any_row:
            B.append(Para("Tahmin üretilecek numune yok (uyarı/alarm yok veya malzeme kaynakları tanımlanmamış).",
                          "muted"))

    # ------------------------------------------------------------ istatistik
    if "stats" in sec:
        section("İstatistikler ve Limitler")
        B.append(Para("Kapsamdaki numunelerden hesaplanmıştır; istatistikten hariç tutulan değerler dahil "
                      "değildir.", "small"))
        rows, sts = [], []
        for p in params:
            vals = [s.stat_value(p.key) for s in scope]
            d = describe(vals)
            if not d["n"]:
                continue
            lim = compute_limits(vals, p.direction, settings)
            rows.append([_plabel(pmap, p.key), str(d["n"]), fmt_num(d["min"]), fmt_num(d["max"]),
                         fmt_num(d["mean"]), fmt_num(d["std"]),
                         _lim(lim.lo_warn, lim.hi_warn), _lim(lim.lo_alarm, lim.hi_alarm)])
            sts.append([None] * 6 + [1 if lim.valid else None, 2 if lim.valid else None])
        B.append(Table(["Parametre", "n", "Min", "Max", "Ort.", "Std", "Uyarı", "Alarm"], rows, sts,
                       [3.2, 0.6, 1, 1, 1, 1, 1.6, 1.6]))

    if "sgs_comments" in sec:
        section("SGS (Analiz Firması) Yorumları")
        cm = [s for s in scope if s.lab_comment or s.lab_diagnosis]
        if cm:
            rows = [[s.sample_no, s.motor_no or "", format_date(s.date_taken), s.lab_diagnosis or "",
                     s.lab_comment or ""] for s in cm]
            sgs = {"Yeşil": 0, "Sarı": 1, "Turuncu": 1, "Kırmızı": 2}
            sts = [[None, None, None, sgs.get(s.lab_diagnosis), None] for s in cm]
            B.append(Table(["Analiz No", "Motor", "Tarih", "SGS teşhisi", "SGS yorumu"], rows, sts,
                           [1.6, 1.5, 1.3, 1.2, 6.3]))
        else:
            B.append(Para("SGS yorumu bulunan numune yok.", "muted"))

    if "exclusions" in sec:
        section("İstatistikten Hariç Tutulan Değerler")
        rows = []
        for s in scope:
            for k, v in s.values.items():
                if s.is_excluded(k):
                    rows.append([s.sample_no, s.motor_no or "", format_date(s.date_taken), _plabel(pmap, k),
                                 fmt_num(v, 3), (s.stats_note if s.stats_excluded else s.excluded.get(k)) or ""])
        if rows:
            B.append(Table(["Analiz No", "Motor", "Tarih", "Parametre", "Değer", "Neden"], rows, None,
                           [1.6, 1.5, 1.3, 2.6, 1.0, 3.5]))
        else:
            B.append(Para("Hariç tutulan değer yok.", "muted"))
    return rep
