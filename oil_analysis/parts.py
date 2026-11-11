"""Yağdaki malzeme -> olası kaynak parça tahmini.

Kullanıcı "Malzeme Kaynakları" sekmesinde her element/parametre için olası
kaynak parçaları yazar. Bir numunede miktarı anlamlı değişen veya uyarı/alarm
veren parametreler bulunur. Bu parametrelerin kaynak parçaları birleştirilerek
puanlanır: birden çok elementin işaret ettiği parça (ör. Fe + Cr -> segman)
üst sıraya çıkar.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .db import Sample
from .evaluation import Evaluator
from .textnorm import normalize_label

# Pistonlu motorlar için genel literatür önerileri (kullanıcı isterse ekler;
# motorunuza göre düzenlenmelidir).
DEFAULT_SOURCES: dict[str, list[tuple[str, str]]] = {
    "fe": [("Silindir gömleği / silindir duvarı", "Segman-silindir sürtünmesi"),
           ("Segmanlar", "Krom kaplı değilse Fe; Cr ile birlikte artış segmana işaret eder"),
           ("Krank mili / eksantrik mili", ""), ("Dişliler", ""), ("Rulmanlar", ""),
           ("Supap / supap iticileri", ""), ("Yağ pompası", "")],
    "cr": [("Segmanlar (krom kaplı)", "Fe ile birlikte artış"), ("Silindir (krom kaplama)", ""),
           ("Rulmanlar / alaşımlı çelik parçalar", "")],
    "cu": [("Yatak burçları (bronz)", "Piston pimi burcu, kol burcu"), ("Kaymalı yataklar", ""),
           ("Yağ soğutucu", "Yeni soğutucuda ilk saatlerde Cu yüksek olabilir"), ("Pompa burçları", "")],
    "pb": [("Kaymalı yataklar (ana / biyel)", "Yatak üst kaplaması"), ("Kurşunlu yakıt", "Avgas kullanılıyorsa")],
    "sn": [("Kaymalı yataklar (yatak alaşımı)", "Pb ve Cu ile birlikte"), ("Burçlar", ""), ("Piston kaplaması", "")],
    "al": [("Piston", "Si ile birlikte artış toz kaynaklı aşınmayı gösterebilir"), ("Silindir kafası", ""),
           ("Karter / blok", ""), ("Yağ pompası gövdesi", "")],
    "ni": [("Supaplar / supap yuvaları", ""), ("Alaşımlı çelik dişliler ve miller", ""), ("Turbo parçaları", "")],
    "ag": [("Gümüş kaplı yataklar / burçlar", ""), ("Lehim bağlantıları", "")],
    "ti": [("Titanyum alaşımlı parçalar (biyel, supap yayı tablası)", "")],
    "mo": [("Segman kaplaması (molibden)", "Yağ katkısı olarak da bulunabilir")],
    "v": [("Yakıt kaynaklı (ağır yakıt)", "")],
    "si": [("Toz / kir girişi", "Hava filtresi, emme hattı kaçağı"), ("Silikon conta / sızdırmazlık", ""),
           ("Köpük önleyici katkı", "Düşük seviyede normal")],
    "na": [("Soğutma sıvısı kaçağı", "K ile birlikte"), ("Katkı paketi", "Bazı yağlarda katkı")],
    "k": [("Soğutma sıvısı kaçağı", "Na ile birlikte")],
    "b": [("Soğutma sıvısı kaçağı", "Yağ katkısı da olabilir")],
    "water_pct": [("Soğutma sıvısı kaçağı / yoğuşma", "")],
    "water_ppm": [("Soğutma sıvısı kaçağı / yoğuşma", "")],
    "glycol": [("Soğutma sıvısı kaçağı", "Silindir kafa contası, yağ soğutucu")],
    "diesel": [("Yakıt seyrelmesi", "Enjektör, yanma problemleri")],
    "soot": [("Yanma / blow-by", "Segman, enjektör, hava-yakıt oranı")],
    "pq": [("Ferromanyetik aşınma partikülleri", "Büyük demir partikülü; Fe ile karşılaştırın")],
}

STATUS_WEIGHT = {2: 3.0, 1: 2.0, 0: 1.0, None: 1.0}


@dataclass
class Change:
    key: str
    value: float
    prev: float | None
    delta: float | None
    pct: float | None
    status: int | None
    reason: str
    parts: list = field(default_factory=list)


@dataclass
class PartScore:
    part: str
    score: float
    elements: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def diagnose(s: Sample, ev: Evaluator, sources: dict[str, list[dict]], settings: dict):
    """Değişen parametreler ve puanlanmış olası parçalar."""
    if s.is_fresh:
        return [], []
    res = ev.evaluate(s)
    prev = ev.previous_sample(s)
    rel = float(settings.get("change_rel", 50.0))
    abs_min = float(settings.get("change_abs", 2.0))
    changes: list[Change] = []
    for p in ev.params:
        v = s.values.get(p.key)
        if v is None:
            continue
        e = res.get(p.key)
        status = e.status if e else None
        pv = prev.values.get(p.key) if prev is not None else None
        delta = v - pv if pv is not None else None
        pct = (delta / pv * 100.0) if (delta is not None and pv) else None
        reasons = []
        if p.direction == "up" and delta is not None and delta >= abs_min and (
                pv == 0 or (pct is not None and pct >= rel)):
            reasons.append(f"Önceki numuneye göre artış ({prev.sample_no})")
        if status and status > 0:
            reasons.extend(e.reasons)
        if not reasons:
            continue
        changes.append(Change(p.key, v, pv, delta, pct, status, "; ".join(reasons),
                              list(sources.get(p.key, []))))
    changes.sort(key=lambda c: (-(c.status or 0), -(c.pct or 0)))

    scores: dict[str, PartScore] = {}
    for c in changes:
        w = STATUS_WEIGHT.get(c.status, 1.0)
        for src in c.parts:
            norm = normalize_label(src["part"])
            if not norm:
                continue
            ps = scores.setdefault(norm, PartScore(src["part"], 0.0))
            ps.score += w
            label = ev.pmap[c.key].name.split(" (")[0] if c.key in ev.pmap else c.key
            if label not in ps.elements:
                ps.elements.append(label)
            if src.get("note"):
                ps.notes.append(src["note"])
    ranked = sorted(scores.values(), key=lambda p: (-p.score, -len(p.elements), p.part))
    return changes, ranked
