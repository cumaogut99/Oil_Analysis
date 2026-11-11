"""Parametre kataloğu ve etiket eşleştirme (rapor farklılıklarını giderme).

Eşleştirme sırası (ilk başarılı olan kazanır):
  1. Kullanıcının daha önce öğrettiği eşleştirmeler (veritabanındaki `aliases`)
  2. Kural tabanlı eşleştirme (regex) - meta alanlar ve fiziksel/FTIR parametreleri
  3. Element adları/sembolleri için tam eşleşme (Ca / Kalsiyum / Calcium)
  4. Bulanık (fuzzy) eşleştirme - yazım hataları için (difflib, eşik 0.85)
Hiçbiri tutmazsa etiket "eşleşmeyen" olarak kullanıcıya sorulur.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from .textnorm import normalize_label, unit_hint

# Kategoriler
PHYSICAL = "Fiziksel"
FTIR = "FTIR / Kirlilik"
ADDITIVE = "Katkı Elementleri"
CONTAMINANT = "Kirletici Elementler"
WEAR = "Aşınma Elementleri"
PARTICLE = "Partikül"
OTHER = "Diğer"

CATEGORIES = [PHYSICAL, FTIR, WEAR, CONTAMINANT, ADDITIVE, PARTICLE, OTHER]

# direction: 'up' -> yüksek değer kötü, 'down' -> düşük değer kötü, 'both'


@dataclass(frozen=True)
class ParamDef:
    key: str
    name: str
    unit: str
    category: str
    direction: str
    aliases: tuple[str, ...] = ()


def _el(sym, tr, en, category, direction):
    return ParamDef(sym.lower(), f"{sym} ({tr})", "ppm", category, direction,
                    (sym.lower(), normalize_label(tr), en))


BUILTIN_PARAMS: list[ParamDef] = [
    ParamDef("visc40", "Viskozite 40°C", "cSt", PHYSICAL, "both"),
    ParamDef("visc100", "Viskozite 100°C", "cSt", PHYSICAL, "both"),
    ParamDef("vi", "Viskozite İndeksi", "", PHYSICAL, "down",
             ("viskozite indeks", "viskozite indeksi", "viscosity index", "vi")),
    ParamDef("tbn", "TBN", "mgKOH/g", PHYSICAL, "down",
             ("tbn", "toplam baz sayisi", "total base number")),
    ParamDef("tan", "TAN", "mgKOH/g", PHYSICAL, "up",
             ("tan", "toplam asit sayisi", "total acid number")),
    ParamDef("diesel", "Yakıt Seyrelmesi (Dizel)", "%", FTIR, "up",
             ("diesel", "dizel", "yakit", "fuel dilution")),
    ParamDef("gasoline", "Benzin", "%", FTIR, "up", ("gasoline", "benzin")),
    ParamDef("glycol", "Glikol", "%", FTIR, "up", ("glikol", "glycol")),
    ParamDef("nitration", "Nitrasyon", "A/cm", FTIR, "up", ("nitration", "nitrasyon")),
    ParamDef("oxidation", "Oksidasyon", "A/cm", FTIR, "up", ("oxidation", "oksidasyon")),
    ParamDef("soot", "Kurum (Soot)", "A/cm", FTIR, "up", ("soot 1980", "soot", "kurum")),
    ParamDef("water_pct", "Su İçeriği (%)", "%", FTIR, "up", ("su icerigi", "water")),
    ParamDef("water_ppm", "Su İçeriği (mg/kg)", "mg/kg", FTIR, "up"),
    ParamDef("sulfation", "Sülfatasyon", "A/cm", FTIR, "up",
             ("sulfation", "sulfatasyon", "sulphation")),
    # Aşınma
    _el("Fe", "Demir", "iron", WEAR, "up"),
    _el("Cu", "Bakır", "copper", WEAR, "up"),
    _el("Al", "Alüminyum", "aluminium", WEAR, "up"),
    _el("Cr", "Krom", "chromium", WEAR, "up"),
    _el("Pb", "Kurşun", "lead", WEAR, "up"),
    _el("Ni", "Nikel", "nickel", WEAR, "up"),
    _el("Ag", "Gümüş", "silver", WEAR, "up"),
    _el("Sn", "Kalay", "tin", WEAR, "up"),
    _el("Ti", "Titanyum", "titanium", WEAR, "up"),
    _el("V", "Vanadyum", "vanadium", WEAR, "up"),
    ParamDef("pq", "PQ Index", "", WEAR, "up", ("pq index wpi", "pq index", "pq indeks", "pq")),
    # Kirletici
    _el("Si", "Silisyum", "silicon", CONTAMINANT, "up"),
    _el("Na", "Sodyum", "sodium", CONTAMINANT, "up"),
    _el("K", "Potasyum", "potassium", CONTAMINANT, "up"),
    # Katkı
    _el("Ba", "Baryum", "barium", ADDITIVE, "down"),
    _el("Ca", "Kalsiyum", "calcium", ADDITIVE, "down"),
    _el("Mg", "Magnezyum", "magnesium", ADDITIVE, "down"),
    _el("Mo", "Molibden", "molybdenum", ADDITIVE, "down"),
    _el("P", "Fosfor", "phosphorus", ADDITIVE, "down"),
    _el("Zn", "Çinko", "zinc", ADDITIVE, "down"),
    _el("B", "Bor", "boron", ADDITIVE, "down"),
    # Partikül
    ParamDef("as4059_4", "SAE AS4059 >4µm(c)", "adet", PARTICLE, "up"),
    ParamDef("as4059_6", "SAE AS4059 >6µm(c)", "adet", PARTICLE, "up"),
    ParamDef("as4059_14", "SAE AS4059 >14µm(c)", "adet", PARTICLE, "up"),
    ParamDef("as4059_21", "SAE AS4059 >21µm(c)", "adet", PARTICLE, "up"),
    ParamDef("as4059_38", "SAE AS4059 >38µm(c)", "adet", PARTICLE, "up"),
    ParamDef("as4059_70", "SAE AS4059 >70µm(c)", "adet", PARTICLE, "up"),
    ParamDef("as4059_class", "SAE AS4059 Sınıfı", "", PARTICLE, "up"),
    ParamDef("iso4406", "Partikül Sayımı ISO 4406", "", PARTICLE, "up"),
]

# Additive elementlerden hangileri "taze yağa göre tükenme" ile izlenir
ADDITIVE_KEYS = {p.key for p in BUILTIN_PARAMS if p.category == ADDITIVE}

# --------------------------------------------------------------- meta alanlar
META_FIELDS = {
    "seq": "Sıra No",
    "sample_no": "Analiz No",
    "test_suite": "Test Paketi",
    "date_taken": "Numune Tarihi",
    "date_analysis": "Analiz Tarihi",
    "date_diagnosis": "Teşhis Tarihi",
    "motor_hours": "Motor Çalışma Süresi (sa)",
    "oil_hours": "Yağ Çalışma Süresi (sa)",
    "topup": "Yağ İlavesi",
    "motor_no": "Motor Numarası",
    "platform": "Platform",
    "source": "Analiz Kaynağı",
    "oil_type": "Yağ Tipi",
    "sample_type": "Numune Tipi",
    "lab_diag_letter": "SGS Teşhis Kodu",
}

_META_RULES: list[tuple[str, re.Pattern]] = [
    (k, re.compile(p)) for k, p in [
        ("seq", r"^(sequential number|sira no|sira)$"),
        ("sample_no", r"^(sample (number|nr|no)|analiz no|numune (no|nr|numarasi)|test report)$"),
        ("test_suite", r"^test (suite|paketi)"),
        ("date_diagnosis", r"^(diagnosis date|teshis tarihi)"),
        ("date_analysis", r"^(date of analysis|analiz tarihi|analysis date)"),
        ("date_taken", r"^(date sample taken|tarih|numune (alma )?tarihi|sampling date)$"),
        ("motor_hours", r"^(equipment (life|h|hours?)|motor calisma suresi|motor saati|ekipman (omru|saati))"),
        ("oil_hours", r"^(lubricant (life|h|hours?)|yag calisma suresi|yag saati|yag omru)"),
        ("topup", r"^(top ?up|yag ilavesi)"),
        ("motor_no", r"^(motor (numarasi|no|nr)|equipment desc)"),
        ("platform", r"^platform"),
        ("source", r"^(analiz kaynagi|kaynak|laboratuvar)$"),
        ("oil_type", r"^(yag (tipi|turu|sinifi)|oil type)$"),
        ("sample_type", r"^(numune (tipi|turu)|analiz tipi)$"),
        ("lab_diag_letter", r"^(diagnosis|teshis)$"),
    ]
]

# Fiziksel / FTIR parametreleri için kurallar (normalize edilmiş etiket üzerinde)
_PARAM_RULES: list[tuple[str, re.Pattern]] = [
    (k, re.compile(p)) for k, p in [
        ("vi", r"(viskozite|viscosity|visc) (indeks|indeksi|index)|^vi$"),
        ("visc40", r"(viskozite|viscosity|visc|kv)\b.*\b40( c)?\b"),
        ("visc100", r"(viskozite|viscosity|visc|kv)\b.*\b100( c)?\b"),
        ("tbn", r"^tbn\b|toplam baz|total base"),
        ("tan", r"^tan\b|toplam asit|total acid"),
        ("diesel", r"^(diesel|dizel|yakit|fuel)\b"),
        ("gasoline", r"^(gasoline|benzin)\b"),
        ("glycol", r"^(glikol|glycol)\b"),
        ("nitration", r"^nitra"),
        ("oxidation", r"^(oxidation|oksidasyon)\b"),
        ("soot", r"^(soot|kurum)\b"),
        ("sulfation", r"^(sulfation|sulphation|sulfatasyon)\b"),
        ("water", r"^(su|water)( icerigi| content)?$"),
        ("pq", r"^pq\b"),
        ("as4059_class", r"^(sae )?as ?4059$"),
        ("iso4406", r"iso ?4406"),
    ]
]
_AS4059_SIZE_RE = re.compile(r"as ?4059 (\d+) ?u?m")

# Tablo grup başlıkları (değer içermez) - PDF hizalamasında atlanır
HEADER_RE = re.compile(
    r"\bastm\b|^results$|^end of analytical|^partikul sae|^icp spektrometri|"
    r"^spektrometri|^yag analizoru|^sonuclar$"
)

ELEMENT_TABLE: dict[str, str] = {}
for _p in BUILTIN_PARAMS:
    if _p.category in (WEAR, CONTAMINANT, ADDITIVE) and _p.key != "pq":
        for _a in _p.aliases:
            ELEMENT_TABLE[normalize_label(_a)] = _p.key


@dataclass
class Match:
    kind: str  # 'meta' | 'param' | 'ignore'
    key: str
    how: str  # 'learned' | 'rule' | 'element' | 'fuzzy'


class LabelMatcher:
    """Etiket -> (meta|param) eşleştirici."""

    def __init__(self, learned: dict[str, str] | None = None,
                 extra_params: list[ParamDef] | None = None):
        # learned: normalize edilmiş etiket -> 'param:key' | 'meta:key' | 'ignore'
        self.learned = dict(learned or {})
        self.params = list(BUILTIN_PARAMS) + list(extra_params or [])
        self._fuzzy_pool: list[tuple[str, str]] = []
        for p in self.params:
            names = set(p.aliases) | {normalize_label(p.name)}
            for a in names:
                a = normalize_label(a)
                if len(a) >= 4:
                    self._fuzzy_pool.append((a, p.key))

    def match(self, label: str) -> Match | None:
        norm = normalize_label(label)
        if not norm:
            return None
        hint = unit_hint(label)

        tgt = self.learned.get(norm)
        if tgt:
            if tgt == "ignore":
                return Match("ignore", "", "learned")
            kind, _, key = tgt.partition(":")
            return Match(kind, key, "learned")

        for key, rx in _META_RULES:
            if rx.search(norm):
                return Match("meta", key, "rule")

        m = _AS4059_SIZE_RE.search(norm)
        if m:
            return Match("param", f"as4059_{m.group(1)}", "rule")

        for key, rx in _PARAM_RULES:
            if rx.search(norm):
                if key == "water":
                    key = "water_ppm" if hint == "mgkg" else "water_pct"
                return Match("param", key, "rule")

        if norm in ELEMENT_TABLE:
            return Match("param", ELEMENT_TABLE[norm], "element")
        # 'ca kalsiyum' gibi birleşik etiketler
        toks = norm.split()
        if 1 < len(toks) <= 3:
            keys = {ELEMENT_TABLE.get(t) for t in toks} - {None}
            if len(keys) == 1:
                return Match("param", keys.pop(), "element")

        if len(norm) >= 4 and not HEADER_RE.search(norm):
            best, best_key = 0.0, None
            for alias, key in self._fuzzy_pool:
                r = difflib.SequenceMatcher(None, norm, alias).ratio()
                if r > best:
                    best, best_key = r, key
            if best >= 0.85:
                return Match("param", best_key, "fuzzy")
        return None


def param_map(extra: list[ParamDef] | None = None) -> dict[str, ParamDef]:
    return {p.key: p for p in list(BUILTIN_PARAMS) + list(extra or [])}
