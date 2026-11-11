"""SQLite veritabanı katmanı (tek dosya, taşınabilir)."""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .parameters import BUILTIN_PARAMS, CATEGORIES, OTHER, ParamDef
from .textnorm import normalize_label, parse_date, parse_number

SCHEMA_VERSION = 2

SAMPLE_TYPES = ["Belirtilmemiş", "Rodaj", "Green", "Saha", "Sıfır Yağ", "Diğer"]
FRESH_OIL = "Sıfır Yağ"
UNSPECIFIED = "Belirtilmemiş"
PLATFORM_GROUPS = ["Belirtilmemiş", "Baykar", "TUSAŞ", "TEI"]

DEFAULT_SETTINGS = {
    # İstatistiksel limit yöntemi: normal | lognormal | percentile
    "method": "normal",
    "trim_outliers": True,
    "k_warn": 2.0,
    "k_alarm": 3.0,
    "pct_warn": 95.0,
    "pct_alarm": 99.0,
    "min_n": 6,
    # Referans popülasyonu gruplama anahtarları
    "group_by": ["oil_type", "sample_type"],
    "use_rate": True,
    # Taze yağa göre değişim eşikleri (%)
    "additive_drop_warn": 25.0,
    "additive_drop_alarm": 40.0,
    "visc_change_warn": 10.0,
    "visc_change_alarm": 20.0,
    "tbn_ratio_warn": 0.6,
    "tbn_ratio_alarm": 0.5,
    # Yağ sınıfına göre 100°C viskozite aralığı (SAE J300)
    "visc_limits": {"0W40": [12.5, 16.3], "5W30": [9.3, 12.5]},
    # Sabit (mutlak) limitler: key -> {lo_alarm, lo_warn, hi_warn, hi_alarm}
    "fixed_limits": {"glycol": {"hi_warn": 0.0}},
    # Parça tahmini: önceki numuneye göre "anlamlı artış" eşikleri
    "change_rel": 50.0,   # %
    "change_abs": 2.0,    # birim (ppm)
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_info(version INTEGER);
CREATE TABLE IF NOT EXISTS platforms(code TEXT PRIMARY KEY, grp TEXT NOT NULL DEFAULT 'Belirtilmemiş');
CREATE TABLE IF NOT EXISTS motors(id INTEGER PRIMARY KEY, motor_no TEXT UNIQUE NOT NULL, notes TEXT);
CREATE TABLE IF NOT EXISTS parameters(
    key TEXT PRIMARY KEY, name TEXT NOT NULL, unit TEXT, category TEXT,
    direction TEXT NOT NULL DEFAULT 'up', sort_order INTEGER, builtin INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS samples(
    id INTEGER PRIMARY KEY,
    sample_no TEXT UNIQUE NOT NULL,
    motor_id INTEGER REFERENCES motors(id) ON DELETE SET NULL,
    platform_code TEXT, sample_type TEXT, oil_type TEXT, lubricant TEXT, source TEXT,
    date_taken TEXT, date_received TEXT, date_analysis TEXT, date_diagnosis TEXT,
    motor_hours REAL, oil_hours REAL, topup REAL,
    lab_diagnosis TEXT, lab_diag_letter TEXT, lab_comment TEXT, lab_info TEXT,
    user_comment TEXT, origin TEXT, source_file TEXT, imported_at TEXT);
CREATE TABLE IF NOT EXISTS measurements(
    sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
    param_key TEXT NOT NULL REFERENCES parameters(key),
    value REAL, raw TEXT,
    PRIMARY KEY(sample_id, param_key));
CREATE TABLE IF NOT EXISTS aliases(alias TEXT PRIMARY KEY, target TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS part_sources(
    id INTEGER PRIMARY KEY, param_key TEXT NOT NULL, part TEXT NOT NULL, note TEXT,
    sort_order INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_samples_motor ON samples(motor_id);
CREATE INDEX IF NOT EXISTS ix_meas_param ON measurements(param_key);
"""

SAMPLE_FIELDS = ["platform_code", "sample_type", "oil_type", "lubricant", "source",
                 "date_taken", "date_received", "date_analysis", "date_diagnosis",
                 "motor_hours", "oil_hours", "topup", "lab_diagnosis", "lab_diag_letter",
                 "lab_comment", "lab_info", "user_comment", "origin", "source_file"]


@dataclass
class Sample:
    id: int
    sample_no: str
    motor_no: str | None
    platform_code: str | None = None
    platform_group: str = UNSPECIFIED
    sample_type: str = UNSPECIFIED
    oil_type: str | None = None
    lubricant: str | None = None
    source: str | None = None
    date_taken: str | None = None
    date_received: str | None = None
    date_analysis: str | None = None
    date_diagnosis: str | None = None
    motor_hours: float | None = None
    oil_hours: float | None = None
    topup: float | None = None
    lab_diagnosis: str | None = None
    lab_diag_letter: str | None = None
    lab_comment: str | None = None
    lab_info: dict = field(default_factory=dict)
    user_comment: str | None = None
    origin: str | None = None
    source_file: str | None = None
    values: dict = field(default_factory=dict)   # key -> float | None
    raws: dict = field(default_factory=dict)     # key -> ham metin
    excluded: dict = field(default_factory=dict)  # key -> hariç tutma notu (istatistik dışı)
    stats_excluded: bool = False                  # numunenin tamamı istatistik dışı
    stats_note: str | None = None

    @property
    def is_fresh(self):
        return self.sample_type == FRESH_OIL

    def is_excluded(self, key: str) -> bool:
        return self.stats_excluded or key in self.excluded

    def stat_value(self, key: str):
        """İstatistik/limit hesabında kullanılacak değer (hariç tutulduysa None)."""
        if self.is_excluded(key):
            return None
        return self.values.get(key)

    def sort_key(self):
        return (self.date_taken or "", self.motor_hours or 0, self.sample_no)


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init()

    def close(self):
        self.conn.close()

    # ------------------------------------------------------------ kurulum
    def _init(self):
        c = self.conn
        c.executescript(_SCHEMA)
        self._migrate()
        if c.execute("SELECT COUNT(*) FROM schema_info").fetchone()[0] == 0:
            c.execute("INSERT INTO schema_info VALUES (?)", (SCHEMA_VERSION,))
        else:
            c.execute("UPDATE schema_info SET version=?", (SCHEMA_VERSION,))
        for i, p in enumerate(BUILTIN_PARAMS):
            c.execute("""INSERT INTO parameters(key,name,unit,category,direction,sort_order,builtin)
                         VALUES (?,?,?,?,?,?,1)
                         ON CONFLICT(key) DO UPDATE SET sort_order=excluded.sort_order""",
                      (p.key, p.name, p.unit, p.category, p.direction, i))
        c.commit()

    def _columns(self, table):
        return {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}

    def _migrate(self):
        """Eski veritabanı dosyalarını yeni sürüme yükseltir (veri kaybı olmadan)."""
        c = self.conn
        mcols = self._columns("measurements")
        if "excluded" not in mcols:
            c.execute("ALTER TABLE measurements ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0")
        if "exclude_note" not in mcols:
            c.execute("ALTER TABLE measurements ADD COLUMN exclude_note TEXT")
        scols = self._columns("samples")
        if "stats_excluded" not in scols:
            c.execute("ALTER TABLE samples ADD COLUMN stats_excluded INTEGER NOT NULL DEFAULT 0")
        if "stats_note" not in scols:
            c.execute("ALTER TABLE samples ADD COLUMN stats_note TEXT")

    # ------------------------------------------------------- hariç tutma
    def set_excluded(self, sid: int, key: str, excluded: bool, note: str | None = None,
                     commit: bool = True):
        self.conn.execute("UPDATE measurements SET excluded=?, exclude_note=? "
                          "WHERE sample_id=? AND param_key=?",
                          (1 if excluded else 0, (note or None) if excluded else None, sid, key))
        if commit:
            self.conn.commit()

    def set_sample_excluded(self, sid: int, excluded: bool, note: str | None = None):
        self.conn.execute("UPDATE samples SET stats_excluded=?, stats_note=? WHERE id=?",
                          (1 if excluded else 0, (note or None) if excluded else None, sid))
        self.conn.commit()

    def clear_exclusions(self, key: str | None = None):
        if key:
            self.conn.execute("UPDATE measurements SET excluded=0, exclude_note=NULL WHERE param_key=?", (key,))
        else:
            self.conn.execute("UPDATE measurements SET excluded=0, exclude_note=NULL")
            self.conn.execute("UPDATE samples SET stats_excluded=0, stats_note=NULL")
        self.conn.commit()

    # -------------------------------------------------- parça kaynakları
    def part_sources(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for r in self.conn.execute(
                "SELECT param_key, part, note FROM part_sources ORDER BY param_key, sort_order, id"):
            out.setdefault(r[0], []).append({"part": r[1], "note": r[2] or ""})
        return out

    def save_part_sources(self, key: str, rows: list[dict]):
        self.conn.execute("DELETE FROM part_sources WHERE param_key=?", (key,))
        for i, r in enumerate(rows):
            part = (r.get("part") or "").strip()
            if part:
                self.conn.execute("INSERT INTO part_sources(param_key, part, note, sort_order) "
                                  "VALUES (?,?,?,?)", (key, part, (r.get("note") or "").strip(), i))
        self.conn.commit()

    # ------------------------------------------------------------ ayarlar
    def settings(self) -> dict:
        s = json.loads(json.dumps(DEFAULT_SETTINGS))
        for row in self.conn.execute("SELECT key, value FROM settings"):
            try:
                s[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                pass
        return s

    def save_settings(self, values: dict):
        for k, v in values.items():
            self.conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",
                              (k, json.dumps(v, ensure_ascii=False)))
        self.conn.commit()

    # --------------------------------------------------------- parametreler
    def parameters(self) -> list[ParamDef]:
        rows = self.conn.execute(
            "SELECT * FROM parameters ORDER BY sort_order, key").fetchall()
        builtin = {p.key: p for p in BUILTIN_PARAMS}
        out = []
        for r in rows:
            if r["key"] in builtin:
                out.append(builtin[r["key"]])
            else:
                out.append(ParamDef(r["key"], r["name"], r["unit"] or "",
                                    r["category"] or OTHER, r["direction"] or "up"))
        order = {c: i for i, c in enumerate(CATEGORIES)}
        idx = {p.key: i for i, p in enumerate(out)}
        out.sort(key=lambda p: (order.get(p.category, 99), idx[p.key]))
        return out

    def custom_parameters(self) -> list[ParamDef]:
        builtin = {p.key for p in BUILTIN_PARAMS}
        return [p for p in self.parameters() if p.key not in builtin]

    def add_parameter(self, name: str, unit: str = "", category: str = OTHER,
                      direction: str = "up") -> str:
        base = "x_" + (normalize_label(name).replace(" ", "_") or "param")
        key, i = base, 1
        while self.conn.execute("SELECT 1 FROM parameters WHERE key=?", (key,)).fetchone():
            i += 1
            key = f"{base}_{i}"
        n = self.conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM parameters").fetchone()[0]
        self.conn.execute("INSERT INTO parameters VALUES (?,?,?,?,?,?,0)",
                          (key, name, unit, category, direction, n))
        self.conn.commit()
        return key

    # -------------------------------------------------------------- alias
    def aliases(self) -> dict[str, str]:
        return {r["alias"]: r["target"] for r in self.conn.execute("SELECT * FROM aliases")}

    def set_alias(self, label: str, target: str):
        norm = normalize_label(label)
        if norm:
            self.conn.execute("INSERT OR REPLACE INTO aliases VALUES (?,?)", (norm, target))
            self.conn.commit()

    def delete_alias(self, alias: str):
        self.conn.execute("DELETE FROM aliases WHERE alias=?", (alias,))
        self.conn.commit()

    # ---------------------------------------------------------- platformlar
    def platforms(self) -> dict[str, str]:
        return {r["code"]: r["grp"] for r in
                self.conn.execute("SELECT * FROM platforms ORDER BY code")}

    def set_platform(self, code: str, grp: str = UNSPECIFIED):
        code = (code or "").strip()
        if code:
            self.conn.execute("INSERT OR REPLACE INTO platforms VALUES (?,?)", (code, grp))
            self.conn.commit()

    def ensure_platform(self, code: str | None):
        code = (code or "").strip()
        if code:
            self.conn.execute("INSERT OR IGNORE INTO platforms(code) VALUES (?)", (code,))

    def delete_platform(self, code: str):
        self.conn.execute("DELETE FROM platforms WHERE code=?", (code,))
        self.conn.commit()

    # -------------------------------------------------------------- motorlar
    def motor_id(self, motor_no: str | None, create=True) -> int | None:
        motor_no = (motor_no or "").strip().upper()
        if not motor_no:
            return None
        r = self.conn.execute("SELECT id FROM motors WHERE motor_no=?", (motor_no,)).fetchone()
        if r:
            return r["id"]
        if not create:
            return None
        return self.conn.execute("INSERT INTO motors(motor_no) VALUES (?)", (motor_no,)).lastrowid

    def motors(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT motor_no FROM motors ORDER BY motor_no")]

    def last_info_for_motor(self, motor_no: str) -> dict:
        r = self.conn.execute(
            """SELECT s.platform_code, s.oil_type FROM samples s JOIN motors m ON m.id=s.motor_id
               WHERE m.motor_no=? ORDER BY s.date_taken DESC LIMIT 1""",
            ((motor_no or "").upper(),)).fetchone()
        return dict(r) if r else {}

    # ------------------------------------------------------------- numuneler
    def sample_exists(self, sample_no: str) -> bool:
        return self.conn.execute("SELECT 1 FROM samples WHERE sample_no=?",
                                 (sample_no.strip().upper(),)).fetchone() is not None

    def save_sample(self, sample_no: str, motor_no: str | None, meta: dict,
                    values: dict, overwrite: bool = False, commit: bool = True) -> str:
        """Numuneyi kaydeder. Dönüş: 'inserted' | 'updated' | 'skipped'.

        meta: SAMPLE_FIELDS anahtarları (ham veya dönüştürülmüş)
        values: param_key -> ham metin veya sayı
        """
        sample_no = sample_no.strip().upper()
        c = self.conn
        existing = c.execute("SELECT id FROM samples WHERE sample_no=?", (sample_no,)).fetchone()
        if existing and not overwrite:
            return "skipped"
        rec = {k: meta.get(k) for k in SAMPLE_FIELDS}
        for k in ("date_taken", "date_received", "date_analysis", "date_diagnosis"):
            rec[k] = parse_date(rec[k]) if rec[k] else None
        for k in ("motor_hours", "oil_hours", "topup"):
            rec[k] = parse_number(rec[k])
        if isinstance(rec.get("lab_info"), dict):
            rec["lab_info"] = json.dumps(rec["lab_info"], ensure_ascii=False)
        rec["sample_type"] = rec.get("sample_type") or UNSPECIFIED
        rec["platform_code"] = (rec.get("platform_code") or "").strip() or None
        rec["oil_type"] = (rec.get("oil_type") or "").strip().upper() or None
        self.ensure_platform(rec["platform_code"])
        mid = self.motor_id(motor_no)
        now = _dt.datetime.now().isoformat(timespec="seconds")
        if existing:
            sid = existing["id"]
            sets = ", ".join(f"{k}=?" for k in SAMPLE_FIELDS)
            c.execute(f"UPDATE samples SET motor_id=?, {sets}, imported_at=? WHERE id=?",
                      [mid] + [rec[k] for k in SAMPLE_FIELDS] + [now, sid])
            # üzerine yazarken kullanıcının hariç tutma kararlarını koru
            kept = c.execute("SELECT param_key, exclude_note FROM measurements "
                             "WHERE sample_id=? AND excluded=1", (sid,)).fetchall()
            c.execute("DELETE FROM measurements WHERE sample_id=?", (sid,))
            status = "updated"
        else:
            cols = ", ".join(SAMPLE_FIELDS)
            qs = ", ".join("?" for _ in SAMPLE_FIELDS)
            sid = c.execute(
                f"INSERT INTO samples(sample_no, motor_id, {cols}, imported_at) VALUES (?,?,{qs},?)",
                [sample_no, mid] + [rec[k] for k in SAMPLE_FIELDS] + [now]).lastrowid
            status = "inserted"
        self._write_values(sid, values)
        if existing:
            for key, note in kept:
                self.set_excluded(sid, key, True, note, commit=False)
        if commit:
            c.commit()
        return status

    def _write_values(self, sid: int, values: dict):
        known = {r[0] for r in self.conn.execute("SELECT key FROM parameters")}
        for key, raw in values.items():
            if key not in known:
                continue
            val = parse_number(raw)
            raw_s = None if raw is None else str(raw).strip()
            if val is None and not raw_s:
                continue
            self.conn.execute(
                """INSERT INTO measurements(sample_id, param_key, value, raw) VALUES (?,?,?,?)
                   ON CONFLICT(sample_id, param_key) DO UPDATE SET value=excluded.value, raw=excluded.raw""",
                (sid, key, val, raw_s))

    def update_sample(self, sid: int, motor_no: str | None, meta: dict, values: dict | None = None):
        rec = dict(meta)
        for k in ("date_taken", "date_received", "date_analysis", "date_diagnosis"):
            if k in rec:
                rec[k] = parse_date(rec[k]) if rec[k] else None
        for k in ("motor_hours", "oil_hours", "topup"):
            if k in rec:
                rec[k] = parse_number(rec[k])
        if "oil_type" in rec:
            rec["oil_type"] = (rec["oil_type"] or "").strip().upper() or None
        if "platform_code" in rec:
            rec["platform_code"] = (rec["platform_code"] or "").strip() or None
            self.ensure_platform(rec["platform_code"])
        keys = [k for k in rec if k in SAMPLE_FIELDS]
        params = [rec[k] for k in keys]
        sql = "UPDATE samples SET motor_id=?" + "".join(f", {k}=?" for k in keys) + " WHERE id=?"
        self.conn.execute(sql, [self.motor_id(motor_no)] + params + [sid])
        if values is not None:
            for key, raw in values.items():
                if raw is None or str(raw).strip() == "":
                    self.conn.execute("DELETE FROM measurements WHERE sample_id=? AND param_key=?",
                                      (sid, key))
            self._write_values(sid, {k: v for k, v in values.items()
                                     if v is not None and str(v).strip() != ""})
        self.conn.commit()

    def delete_sample(self, sid: int):
        self.conn.execute("DELETE FROM samples WHERE id=?", (sid,))
        self.conn.commit()

    def load_samples(self) -> list[Sample]:
        plat = self.platforms()
        rows = self.conn.execute(
            """SELECT s.*, m.motor_no FROM samples s LEFT JOIN motors m ON m.id=s.motor_id""").fetchall()
        samples: dict[int, Sample] = {}
        for r in rows:
            d = dict(r)
            try:
                info = json.loads(d.get("lab_info") or "{}")
            except json.JSONDecodeError:
                info = {}
            s = Sample(id=d["id"], sample_no=d["sample_no"], motor_no=d["motor_no"],
                       platform_group=plat.get(d["platform_code"] or "", UNSPECIFIED)
                       if d["platform_code"] else UNSPECIFIED,
                       lab_info=info, stats_excluded=bool(d.get("stats_excluded")),
                       stats_note=d.get("stats_note"),
                       **{k: d[k] for k in SAMPLE_FIELDS if k != "lab_info"})
            s.sample_type = s.sample_type or UNSPECIFIED
            samples[s.id] = s
        for r in self.conn.execute(
                "SELECT sample_id, param_key, value, raw, excluded, exclude_note FROM measurements"):
            s = samples.get(r[0])
            if s is not None:
                s.values[r[1]] = r[2]
                s.raws[r[1]] = r[3]
                if r[4]:
                    s.excluded[r[1]] = r[5] or ""
        return sorted(samples.values(), key=Sample.sort_key)

    def commit(self):
        self.conn.commit()
