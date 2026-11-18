"""Arayüz regresyon testleri (ekransız, offscreen)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from oil_analysis.db import Database  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from oil_analysis.ui import theme
    a = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theme.apply(a, "light")
    return a


@pytest.fixture()
def window(app, tmp_path):
    from PySide6.QtCore import QSettings

    from oil_analysis.ui.main_window import MainWindow
    db = Database(tmp_path / "ui.db")
    for m in range(4):
        for k in range(3):
            db.save_sample(f"E{m}{k:02d}", f"TMS2201{m}",
                           {"sample_type": "Saha", "oil_type": "0W40", "motor_hours": 100 + 10 * k,
                            "oil_hours": 20 + 10 * k, "date_taken": f"{k + 1:02d}/0{m + 1}/2026"},
                           {"fe": 10 + k + (80 if (m, k) == (2, 2) else 0), "visc100": 12.8, "cu": 3})
    db.close()
    qs = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    w = MainWindow(str(tmp_path / "ui.db"), qs)
    w.show()
    app.processEvents()
    yield w
    w.close()


def _motors(sp):
    return {sp.table.item(r, 2).text() for r in range(sp.table.rowCount())}


def test_motor_filter_select_and_clear(window, app):
    sp = window.pages[0]
    assert len(_motors(sp)) == 4
    for _ in range(3):  # tekrar tekrar seç / kaldır
        sp.filters.motor.setCurrentText("TMS22012")
        app.processEvents()
        assert _motors(sp) == {"TMS22012"}
        sp.filters.motor.setCurrentIndex(0)
        app.processEvents()
        assert len(_motors(sp)) == 4
    # parametre filtresiyle birlikte
    sp.picker.set_keys(["fe"])
    sp.show_mode.setCurrentIndex(1)
    app.processEvents()
    assert _motors(sp) == {"TMS22012"}
    sp.show_mode.setCurrentIndex(0)
    sp.picker.set_auto()
    app.processEvents()
    assert len(_motors(sp)) == 4


def test_sample_dialog_rename_and_add_visc40(window, app):
    from PySide6.QtCore import Qt

    from oil_analysis.ui.samples_tab import SampleDialog
    st = window.state
    s = next(x for x in st.samples if x.sample_no == "E000")
    d = SampleDialog(st, s, window)
    keys = d._row_keys
    assert "visc40" in keys  # değeri olmasa da listelenir
    d.e_no.setText("e000-duz")
    i = keys.index("visc40")
    d.table.item(i, 2).setText("71,4")
    # tüm parametreleri göster: kaydedilmemiş düzenleme korunur
    d.c_all.setChecked(True)
    assert len(d._row_keys) > len(keys)
    assert d.table.item(d._row_keys.index("visc40"), 2).text() == "71,4"
    assert d.table.item(d._row_keys.index("ni"), 0).foreground().color().name() != "#000000"
    d.save()
    s2 = next(x for x in st.samples if x.id == s.id)
    assert s2.sample_no == "E000-DUZ"
    assert s2.values["visc40"] == pytest.approx(71.4)
    assert Qt  # noqa


def test_rename_rejects_duplicate(tmp_path):
    db = Database(tmp_path / "r.db")
    db.save_sample("A1", "M", {}, {"fe": 1})
    db.save_sample("A2", "M", {}, {"fe": 1})
    a1 = next(s for s in db.load_samples() if s.sample_no == "A1")
    assert db.rename_sample(a1.id, "a2") is False
    assert db.rename_sample(a1.id, "a3") is True
    assert {s.sample_no for s in db.load_samples()} == {"A2", "A3"}
