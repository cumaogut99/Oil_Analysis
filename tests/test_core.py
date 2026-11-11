import datetime as dt

import openpyxl
import pytest

from oil_analysis.db import FRESH_OIL, Database
from oil_analysis.evaluation import Evaluator
from oil_analysis.excel_importer import default_type_for_sheet, read_workbook
from oil_analysis.importer import apply_mappings, save_excel, save_report
from oil_analysis.parameters import LabelMatcher
from oil_analysis.pdf_parser import parse_pdf
from oil_analysis.stats import classify, compute_limits, correlation
from oil_analysis.textnorm import normalize_label, parse_date, parse_number
from sample_pdf import make_report


# ------------------------------------------------------------------ metin
@pytest.mark.parametrize("label,expected", [
    ("Ca mg/kg", ("param", "ca")),
    ("Kalsiyum mg/kg", ("param", "ca")),
    ("Gümüş mg/kg", ("param", "ag")),
    ("Cinko mg/kg", ("param", "zn")),
    ("Mg", ("param", "mg")),
    ("K mg/kg", ("param", "k")),
    ("Viskozite 40°C mm²/s", ("param", "visc40")),
    ("Viskozite (100°C)", ("param", "visc100")),
    ("Viskozite indeks", ("param", "vi")),
    ("TBN mgKOH/g", ("param", "tbn")),
    ("TAN mgKOH/g", ("param", "tan")),
    ("Toplam Asit  Sayısı mg KOH/g", ("param", "tan")),
    ("Su içeriği %", ("param", "water_pct")),
    ("Su içerigi mg/kg", ("param", "water_ppm")),
    ("Diesel A/0.1 mm", ("param", "diesel")),
    ("Soot 1980 A/cm", ("param", "soot")),
    ("PQ Index (WPI)", ("param", "pq")),
    ("SAE AS4059 >38µm (c)", ("param", "as4059_38")),
    ("SAE AS4059 >4µm(c)", ("param", "as4059_4")),
    ("SAE AS4059", ("param", "as4059_class")),
    ("Partikül sayimi ISO4406", ("param", "iso4406")),
    ("Equipment life (h)", ("meta", "motor_hours")),
    ("Lubricant life (h)", ("meta", "oil_hours")),
    ("Motor Çalışma Süresi (sa)", ("meta", "motor_hours")),
    ("Yağ Çalışma Süresi (sa)", ("meta", "oil_hours")),
    ("Analiz No", ("meta", "sample_no")),
    ("Motor Numarası", ("meta", "motor_no")),
    ("Magnezym", ("param", "mg")),  # yazım hatası -> bulanık eşleşme
])
def test_matcher(label, expected):
    m = LabelMatcher().match(label)
    assert m is not None, label
    assert (m.kind, m.key) == expected


def test_learned_alias_has_priority():
    m = LabelMatcher({normalize_label("Garip Etiket"): "param:fe"}).match("Garip  etiket")
    assert (m.kind, m.key, m.how) == ("param", "fe", "learned")


def test_parse_number_and_date():
    assert parse_number("1266,3") == pytest.approx(1266.3)
    assert parse_number("0.00") == 0.0
    assert parse_number("IMP") is None
    assert parse_number("1.234,5") == pytest.approx(1234.5)
    assert parse_date("23/08/2026") == "2026-08-23"
    assert parse_date("12/7/2026") == "2026-07-12"
    assert parse_date(dt.datetime(2026, 5, 25)) == "2026-05-25"


# -------------------------------------------------------------------- PDF
def _samples(n, start=89):
    out = []
    for i in range(n):
        out.append(dict(sample_no=f"ELD{start + i * 10:05d}", date=f"{10 + i}/07/2026",
                        eq=f"{1266 + i * 100},3", lub=str(90 + i), letter="TY"[i % 2],
                        values={"visc40": 66.9 + i, "visc100": 12.1, "tbn": 8.9, "diesel": "0.00",
                                "nitration": 9.34, "water_pct": "IMP", "fe": 28 + i, "ca": 2482,
                                "k": i, "v": 0, "ag": 2.7, "pq": 30 - i}))
    return out


@pytest.mark.parametrize("turkish", [False, True])
def test_pdf_multi_column(tmp_path, turkish):
    pdf = tmp_path / "r.pdf"
    make_report(pdf, _samples(6), turkish=turkish)
    r = parse_pdf(pdf)
    assert r.report_no == "ELD00139"
    assert r.main_sample_no == "ELD00139"
    assert r.header["motor_no"] == "TMS22027"
    assert r.header["lab_diagnosis"] == "Yeşil"
    assert "kabul edilebilir" in r.header["lab_comment"]
    assert len(r.samples) == 6
    s0 = r.samples["ELD00089"]
    assert s0.values["fe"] == "28" and s0.values["visc40"] == "66.9"
    assert s0.values["water_pct"] == "IMP"
    assert s0.meta["motor_hours"] == "1266,3"
    assert s0.meta["lab_diag_letter"] == "T"
    last = r.samples["ELD00139"]
    assert last.values["k"] == "5" and last.values["pq"] == "25"
    assert not r.unmatched


def test_pdf_single_column_with_drift_and_extra_rows(tmp_path):
    pdf = tmp_path / "r.pdf"
    make_report(pdf, _samples(1, 153), turkish=True, drift=0.12, diag="Kirmizi",
                extra_rows=[("SAE AS4059 >38µm (c)", ["IMP"]),
                            ("Toplam Asit Sayisi mg KOH/g", ["2.12"]),
                            ("Bilinmeyen Test", ["7"])])
    r = parse_pdf(pdf)
    s = r.samples["ELD00153"]
    assert s.values["fe"] == "28" and s.values["ag"] == "2.7"
    assert s.values["tan"] == "2.12"
    assert s.values["as4059_38"] == "IMP"
    assert r.header["lab_diagnosis"] == "Kırmızı"
    assert [u.label for u in r.unmatched] == ["Bilinmeyen Test"]


def test_pdf_save_and_mapping(tmp_path):
    pdf = tmp_path / "r.pdf"
    make_report(pdf, _samples(3), extra_rows=[("Bilinmeyen Test", ["1", "2", "3"])])
    r = parse_pdf(pdf)
    db = Database(tmp_path / "x.db")
    key = db.add_parameter("Bilinmeyen Test")
    apply_mappings(list(r.samples.values()), r.unmatched, {r.unmatched[0].norm: f"param:{key}"})
    c = save_report(db, r, motor_no="TMS22027", platform_code="C9", sample_type="Saha",
                    oil_type="0w40")
    assert c == {"inserted": 3, "updated": 0, "skipped": 0}
    c = save_report(db, r, motor_no="TMS22027", platform_code="C9", sample_type="Saha",
                    oil_type="0W40")
    assert c["skipped"] == 3
    ss = db.load_samples()
    main = [s for s in ss if s.sample_no == r.main_sample_no][0]
    assert main.sample_type == "Saha" and main.oil_type == "0W40"
    assert main.values[key] == 3.0
    assert main.motor_hours == pytest.approx(1466.3)
    assert main.lab_comment


# ------------------------------------------------------------------ Excel
def _make_excel(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "SERİ"
    labels = ["Motor Numarası", "Platform", "Analiz No", "Analiz Kaynağı", "Tarih", "Yağ Tipi",
              "Motor Çalışma Süresi (sa)", "Yağ Çalışma Süresi (sa)", None,
              "Viskosite (40°C)", "Viskozite (100°C)", "Viskozite indeks", "TBN mgKOH/g", None,
              "Su içeriği %", "Su içerigi mg/kg", None, "Ca", "Fe", "Cu", "Garip Satır"]
    for i, lab in enumerate(labels, start=1):
        ws.cell(i, 2, lab)
    ws.cell(10, 1, "ASTM D7042")
    cols = {
        3: ["TMS22070", "C9", "ELD00065", "SGS", "25/05/2026", "0W40", 194, 91.5, None,
            71.4, 11.6, 159, 10.1, None, 0.04, 453.5, None, 3130, 57, 9.4, 1],
        4: [None, "C9", "ELD00093", "SGS", dt.datetime(2026, 6, 23), "0W40", "300,1", 106.18, None,
            71.1, 12.9, 186, 9.4, None, 0.03, None, None, 2953, 57, 8.8, 2],
        6: ["MAX", None, None, None, None, None, None, None, None, 78.7, 15.7],
        8: ["SIFIR YAĞ", "-", "TU490282", "SGS", "24/10/2024", "0W40", 0, 0, None,
            73.5, 13, 181, 10.4, None, 0, None, None, 2559, 0, 0],
    }
    for c, vals in cols.items():
        for r, v in enumerate(vals, start=1):
            if v is not None:
                ws.cell(r, c, v)
    ws.merge_cells(start_row=1, start_column=3, end_row=1, end_column=4)
    wb.create_sheet("SERİ-RODAJ-GREEN")
    wb.save(path)


def test_excel_import(tmp_path):
    x = tmp_path / "y.xlsx"
    _make_excel(x)
    sheets = read_workbook(str(x))
    sh = sheets[0]
    assert sh.label_col == 2
    nos = [s.sample_no for s in sh.samples]
    assert nos == ["ELD00065", "ELD00093", "TU490282"]
    s1 = sh.samples[1]
    assert s1.meta["motor_no"] == "TMS22070"  # birleştirilmiş hücre
    assert s1.values["fe"] == 57
    fresh = sh.samples[2]
    assert fresh.meta["sample_type"] == FRESH_OIL
    assert [u.label for u in sh.unmatched] == ["Garip Satır"]
    assert default_type_for_sheet("SERİ-RODAJ-GREEN") == "Belirtilmemiş"
    assert default_type_for_sheet("RODAJ") == "Rodaj"

    db = Database(tmp_path / "x.db")
    c = save_excel(db, sheets, {"SERİ": "Saha"})
    assert c["inserted"] == 3
    ss = {s.sample_no: s for s in db.load_samples()}
    assert ss["ELD00093"].motor_hours == pytest.approx(300.1)
    assert ss["ELD00093"].date_taken == "2026-06-23"
    assert ss["ELD00065"].values["water_ppm"] == 453.5
    assert ss["TU490282"].is_fresh and ss["TU490282"].motor_no is None
    assert ss["ELD00065"].platform_code == "C9"


# ------------------------------------------------------------ istatistik
def test_limits_and_classify():
    vals = [10, 11, 9, 10, 12, 10, 11, 9, 10, 100]
    lim = compute_limits(vals, "up", {"method": "normal", "trim_outliers": True, "min_n": 6})
    assert lim.n_used == 9  # 100 ayıklandı
    assert classify(100, lim) == 2
    assert classify(10, lim) == 0
    assert lim.lo_warn is None
    pct = compute_limits(vals, "both", {"method": "percentile", "trim_outliers": False,
                                        "min_n": 6, "pct_warn": 90, "pct_alarm": 99})
    assert pct.lo_warn is not None and pct.hi_warn is not None
    few = compute_limits([1, 2], "up", {"min_n": 6})
    assert not few.valid and "Yetersiz" in few.note


def test_correlation():
    keys, r, n = correlation({"a": [1, 2, 3, 4, 5, None], "b": [2, 4, 6, 8, 10, 1],
                              "c": [5, 4, 3, 2, 1, 0]}, "spearman")
    assert r[0, 1] == pytest.approx(1.0)
    assert r[0, 2] == pytest.approx(-1.0)
    assert n[0, 1] == 5


def test_evaluator(tmp_path):
    db = Database(tmp_path / "e.db")
    db.save_sample("FRESH1", None, {"sample_type": FRESH_OIL, "oil_type": "0W40"},
                   {"ca": 2500, "visc100": 13.0, "tbn": 10.0, "fe": 0})
    for i in range(10):
        db.save_sample(f"S{i:03d}", f"M{i % 3}", {"sample_type": "Saha", "oil_type": "0W40",
                                                  "motor_hours": 100 + i, "oil_hours": 100,
                                                  "date_taken": f"{i + 1:02d}/01/2026"},
                       {"fe": 20 + (i % 3), "ca": 2400, "visc100": 12.8, "tbn": 9.0})
    db.save_sample("BAD", "M9", {"sample_type": "Saha", "oil_type": "0W40", "oil_hours": 100,
                                 "motor_hours": 500},
                   {"fe": 200, "ca": 1200, "visc100": 9.0, "tbn": 4.0, "tan": 4.5})
    ss = db.load_samples()
    ev = Evaluator(ss, db.parameters(), db.settings())
    bad = [s for s in ss if s.sample_no == "BAD"][0]
    res = ev.evaluate(bad)
    assert res["fe"].status == 2
    assert res["ca"].status == 2 and any("Katkı" in r for r in res["ca"].reasons)
    assert res["visc100"].status == 2
    assert res["tbn"].status == 2 and any("TAN" in r for r in res["tbn"].reasons)
    assert res["fe"].rate == pytest.approx(200.0)
    good = [s for s in ss if s.sample_no == "S001"][0]
    st, flagged = ev.overall(good)
    assert st == 0 and not flagged


# ------------------------------------------------- hariç tutma / parça
def _population(db, n=10):
    db.save_sample("FRESH1", None, {"sample_type": FRESH_OIL, "oil_type": "0W40"},
                   {"ca": 2500, "fe": 0, "cr": 0})
    for i in range(n):
        db.save_sample(f"S{i:03d}", "M1" if i < 5 else "M2",
                       {"sample_type": "Saha", "oil_type": "0W40", "motor_hours": 100 + i * 10,
                        "oil_hours": 10 + i * 10 if i < 5 else 10 + (i - 5) * 10,
                        "date_taken": f"{i + 1:02d}/02/2026"},
                       {"fe": 10 + i % 3, "cr": 1, "ca": 2450})


def test_exclusion_affects_stats_not_values(tmp_path):
    db = Database(tmp_path / "x.db")
    _population(db)
    db.save_sample("ABSURD", "M3", {"sample_type": "Saha", "oil_type": "0W40", "oil_hours": 50},
                   {"fe": 5000})
    ss = {s.sample_no: s for s in db.load_samples()}
    sid = ss["ABSURD"].id
    db.set_excluded(sid, "fe", True, "ölçüm hatası")
    ss = {s.sample_no: s for s in db.load_samples()}
    s = ss["ABSURD"]
    assert s.values["fe"] == 5000 and s.stat_value("fe") is None
    assert s.excluded["fe"] == "ölçüm hatası"
    ev = Evaluator(list(ss.values()), db.parameters(), db.settings())
    lim = ev.limits(s, "fe")
    assert lim.hi_alarm < 20  # 5000 limitlere girmedi
    assert ev.evaluate(s)["fe"].status == 2  # ama kendisi yine değerlendirildi
    # üzerine yazınca hariç tutma korunur
    db.save_sample("ABSURD", "M3", {"sample_type": "Saha", "oil_type": "0W40"}, {"fe": 4999},
                   overwrite=True)
    s = {x.sample_no: x for x in db.load_samples()}["ABSURD"]
    assert "fe" in s.excluded and s.values["fe"] == 4999
    # numunenin tamamı
    db.set_excluded(sid, "fe", False)
    db.set_sample_excluded(sid, True, "kontamine")
    s = {x.sample_no: x for x in db.load_samples()}["ABSURD"]
    assert s.stats_excluded and s.stat_value("fe") is None and not s.excluded


def test_migration_from_v1(tmp_path):
    import sqlite3
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.executescript("""CREATE TABLE measurements(sample_id INTEGER, param_key TEXT, value REAL, raw TEXT,
                       PRIMARY KEY(sample_id, param_key));
                       CREATE TABLE samples(id INTEGER PRIMARY KEY, sample_no TEXT UNIQUE NOT NULL,
                       motor_id INTEGER, platform_code TEXT, sample_type TEXT, oil_type TEXT,
                       lubricant TEXT, source TEXT, date_taken TEXT, date_received TEXT,
                       date_analysis TEXT, date_diagnosis TEXT, motor_hours REAL, oil_hours REAL,
                       topup REAL, lab_diagnosis TEXT, lab_diag_letter TEXT, lab_comment TEXT,
                       lab_info TEXT, user_comment TEXT, origin TEXT, source_file TEXT, imported_at TEXT);
                       INSERT INTO samples(id, sample_no) VALUES (1, 'OLD1');
                       INSERT INTO measurements VALUES (1, 'fe', 12, '12');""")
    c.commit()
    c.close()
    db = Database(p)
    s = db.load_samples()[0]
    assert s.values["fe"] == 12 and not s.excluded and not s.stats_excluded


def test_parts_diagnosis(tmp_path):
    from oil_analysis.parts import diagnose
    db = Database(tmp_path / "p.db")
    _population(db)
    db.save_part_sources("fe", [{"part": "Segmanlar", "note": ""}, {"part": "Krank mili", "note": ""}])
    db.save_part_sources("cr", [{"part": "segmanlar", "note": "krom kaplı"}])
    db.save_sample("NEW", "M1", {"sample_type": "Saha", "oil_type": "0W40", "motor_hours": 200,
                                 "oil_hours": 60, "date_taken": "01/03/2026"},
                   {"fe": 40, "cr": 6, "ca": 2450})
    ss = db.load_samples()
    ev = Evaluator(ss, db.parameters(), db.settings())
    s = [x for x in ss if x.sample_no == "NEW"][0]
    changes, ranked = diagnose(s, ev, db.part_sources(), db.settings())
    keys = [c.key for c in changes]
    assert "fe" in keys and "cr" in keys and "ca" not in keys
    fe = next(c for c in changes if c.key == "fe")
    assert fe.prev is not None and fe.delta > 0
    assert ranked[0].part == "Segmanlar" and set(ranked[0].elements) == {"Fe", "Cr"}
