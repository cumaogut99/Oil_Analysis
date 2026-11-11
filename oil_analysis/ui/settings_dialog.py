"""Ayarlar: platformlar, viskozite aralıkları, sabit limitler, değerlendirme, eşleştirmeler."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from ..db import PLATFORM_GROUPS
from ..evaluation import GROUP_LABELS
from ..stats import METHODS
from ..textnorm import fmt_num, parse_number
from .common import AppState


def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setStretchLastSection(True)
    return t


def _buttons(table, add_fn):
    row = QHBoxLayout()
    b_add = QPushButton("Satır ekle")
    b_add.clicked.connect(add_fn)
    b_del = QPushButton("Seçili satırı sil")
    b_del.clicked.connect(lambda: table.removeRow(table.currentRow()) if table.currentRow() >= 0 else None)
    row.addWidget(b_add)
    row.addWidget(b_del)
    row.addStretch(1)
    return row


class SettingsDialog(QDialog):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Ayarlar")
        self.resize(820, 600)
        st = state.settings
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs, 1)

        # ---------------- platformlar
        w = QWidget()
        wl = QVBoxLayout(w)
        wl.addWidget(QLabel("Platform kodlarını (C9, C10…) sınıflandırma grubuna (Baykar / TUSAŞ / TEI) "
                            "atayın. Gruplar filtrelerde ve referans popülasyonunda kullanılır."))
        self.t_plat = _table(["Platform kodu", "Grup"])
        for code, grp in state.platforms.items():
            self._add_plat(code, grp)
        wl.addWidget(self.t_plat, 1)
        wl.addLayout(_buttons(self.t_plat, lambda: self._add_plat("", PLATFORM_GROUPS[0])))
        tabs.addTab(w, "Platformlar")

        # ---------------- viskozite
        w = QWidget()
        wl = QVBoxLayout(w)
        wl.addWidget(QLabel("Yağ sınıfına göre 100°C kinematik viskozite aralığı (cSt). Dışı = alarm."))
        self.t_visc = _table(["Yağ tipi", "Min", "Max"])
        for oil, (lo, hi) in st.get("visc_limits", {}).items():
            self._add_row(self.t_visc, [oil, fmt_num(lo), fmt_num(hi)])
        wl.addWidget(self.t_visc, 1)
        wl.addLayout(_buttons(self.t_visc, lambda: self._add_row(self.t_visc, ["", "", ""])))
        tabs.addTab(w, "Viskozite Aralıkları")

        # ---------------- sabit limitler
        w = QWidget()
        wl = QVBoxLayout(w)
        wl.addWidget(QLabel("Kesin limitiniz olan parametreler için mutlak limitler (boş = yok). "
                            "İstatistiksel limitlere ek olarak uygulanır; en kötü sonuç geçerlidir."))
        self.t_fixed = _table(["Parametre", "Alt alarm", "Alt uyarı", "Üst uyarı", "Üst alarm"])
        for key, d in (st.get("fixed_limits") or {}).items():
            self._add_fixed(key, d)
        wl.addWidget(self.t_fixed, 1)
        wl.addLayout(_buttons(self.t_fixed, lambda: self._add_fixed(None, {})))
        tabs.addTab(w, "Sabit Limitler")

        # ---------------- değerlendirme
        w = QWidget()
        form = QFormLayout(w)
        self.method = QComboBox()
        for k, v in METHODS.items():
            self.method.addItem(v, k)
        self.method.setCurrentIndex(max(0, self.method.findData(st["method"])))
        form.addRow("İstatistiksel limit yöntemi:", self.method)
        self.trim = QCheckBox("Limit hesabından önce uç değerleri ayıkla (MAD + 3σ)")
        self.trim.setChecked(bool(st["trim_outliers"]))
        form.addRow(self.trim)
        self.k_warn = self._dspin(st["k_warn"], 0.5, 6, 0.1)
        self.k_alarm = self._dspin(st["k_alarm"], 0.5, 8, 0.1)
        form.addRow("Uyarı: μ + k·σ, k =", self.k_warn)
        form.addRow("Alarm: μ + k·σ, k =", self.k_alarm)
        self.p_warn = self._dspin(st["pct_warn"], 50, 99.9, 0.5)
        self.p_alarm = self._dspin(st["pct_alarm"], 50, 99.99, 0.5)
        form.addRow("Yüzdelik yöntem uyarı (P):", self.p_warn)
        form.addRow("Yüzdelik yöntem alarm (P):", self.p_alarm)
        self.min_n = QSpinBox()
        self.min_n.setRange(3, 1000)
        self.min_n.setValue(int(st["min_n"]))
        form.addRow("Limit için en az numune sayısı:", self.min_n)
        grp_row = QHBoxLayout()
        self.group_checks = {}
        for k, lab in GROUP_LABELS.items():
            cb = QCheckBox(lab)
            cb.setChecked(k in st.get("group_by", []))
            grp_row.addWidget(cb)
            self.group_checks[k] = cb
        gw = QWidget()
        gw.setLayout(grp_row)
        form.addRow("Referans grubu (aynı olanlar):", gw)
        form.addRow(QLabel("<i>Grup yetersizse (n < en az sayı) sondan başlayarak kriterler gevşetilir.</i>"))
        self.use_rate = QCheckBox("Artış hızı (ppm/100 sa) limitlerini de uygula")
        self.use_rate.setChecked(bool(st.get("use_rate", True)))
        form.addRow(self.use_rate)
        self.add_w = self._dspin(st["additive_drop_warn"], 1, 100, 1)
        self.add_a = self._dspin(st["additive_drop_alarm"], 1, 100, 1)
        form.addRow("Katkı elementi düşüşü uyarı (%):", self.add_w)
        form.addRow("Katkı elementi düşüşü alarm (%):", self.add_a)
        self.vis_w = self._dspin(st["visc_change_warn"], 1, 100, 1)
        self.vis_a = self._dspin(st["visc_change_alarm"], 1, 100, 1)
        form.addRow("Viskozite değişimi uyarı (±%):", self.vis_w)
        form.addRow("Viskozite değişimi alarm (±%):", self.vis_a)
        self.tbn_w = self._dspin(st["tbn_ratio_warn"], 0.05, 1, 0.05)
        self.tbn_a = self._dspin(st["tbn_ratio_alarm"], 0.05, 1, 0.05)
        form.addRow("TBN / taze TBN uyarı oranı <", self.tbn_w)
        form.addRow("TBN / taze TBN alarm oranı <", self.tbn_a)
        self.ch_rel = self._dspin(st.get("change_rel", 50), 1, 1000, 5)
        self.ch_abs = self._dspin(st.get("change_abs", 2), 0, 1000, 0.5)
        form.addRow("Parça tahmini: anlamlı artış (%) ≥", self.ch_rel)
        form.addRow("Parça tahmini: anlamlı artış (birim) ≥", self.ch_abs)
        tabs.addTab(w, "Değerlendirme")

        # ---------------- eşleştirmeler
        w = QWidget()
        wl = QVBoxLayout(w)
        wl.addWidget(QLabel("İçe aktarma sırasında öğretilen etiket eşleştirmeleri."))
        self.t_alias = _table(["Normalize etiket", "Hedef"])
        for a, t in sorted(state.db.aliases().items()):
            self._add_row(self.t_alias, [a, t], editable=False)
        wl.addWidget(self.t_alias, 1)
        b = QPushButton("Seçili eşleştirmeyi sil")
        b.clicked.connect(self._del_alias)
        wl.addWidget(b)
        tabs.addTab(w, "Etiket Eşleştirmeleri")

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Kaydet")
        bb.button(QDialogButtonBox.Save).setProperty("variant", "primary")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    @staticmethod
    def _dspin(val, lo, hi, step):
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setSingleStep(step)
        sp.setDecimals(2)
        sp.setValue(float(val))
        return sp

    @staticmethod
    def _add_row(table, values, editable=True):
        r = table.rowCount()
        table.insertRow(r)
        for c, v in enumerate(values):
            it = QTableWidgetItem(str(v))
            if not editable:
                from PySide6.QtCore import Qt
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            table.setItem(r, c, it)

    def _add_plat(self, code, grp):
        r = self.t_plat.rowCount()
        self.t_plat.insertRow(r)
        self.t_plat.setItem(r, 0, QTableWidgetItem(code))
        cb = QComboBox()
        cb.addItems(PLATFORM_GROUPS)
        cb.setCurrentText(grp or PLATFORM_GROUPS[0])
        self.t_plat.setCellWidget(r, 1, cb)

    def _add_fixed(self, key, d):
        r = self.t_fixed.rowCount()
        self.t_fixed.insertRow(r)
        cb = QComboBox()
        for p in self.state.params:
            cb.addItem(self.state.param_label(p.key), p.key)
        if key:
            cb.setCurrentIndex(max(0, cb.findData(key)))
        self.t_fixed.setCellWidget(r, 0, cb)
        for c, k in enumerate(("lo_alarm", "lo_warn", "hi_warn", "hi_alarm"), start=1):
            v = d.get(k)
            self.t_fixed.setItem(r, c, QTableWidgetItem("" if v is None else fmt_num(v, 4)))

    def _del_alias(self):
        r = self.t_alias.currentRow()
        if r < 0:
            return
        self.state.db.delete_alias(self.t_alias.item(r, 0).text())
        self.t_alias.removeRow(r)

    def save(self):
        db = self.state.db
        # platformlar
        existing = set(self.state.platforms)
        seen = set()
        for r in range(self.t_plat.rowCount()):
            it = self.t_plat.item(r, 0)
            code = it.text().strip() if it else ""
            if code:
                db.set_platform(code, self.t_plat.cellWidget(r, 1).currentText())
                seen.add(code)
        for code in existing - seen:
            db.delete_platform(code)
        visc = {}
        for r in range(self.t_visc.rowCount()):
            vals = [(self.t_visc.item(r, c).text().strip() if self.t_visc.item(r, c) else "") for c in range(3)]
            lo, hi = parse_number(vals[1]), parse_number(vals[2])
            if vals[0] and lo is not None and hi is not None:
                visc[vals[0].upper()] = [lo, hi]
        fixed = {}
        for r in range(self.t_fixed.rowCount()):
            key = self.t_fixed.cellWidget(r, 0).currentData()
            d = {}
            for c, k in enumerate(("lo_alarm", "lo_warn", "hi_warn", "hi_alarm"), start=1):
                it = self.t_fixed.item(r, c)
                v = parse_number(it.text()) if it and it.text().strip() else None
                if v is not None:
                    d[k] = v
            if d:
                fixed[key] = d
        if self.k_alarm.value() < self.k_warn.value() or self.p_alarm.value() < self.p_warn.value():
            QMessageBox.warning(self, "Ayarlar", "Alarm eşiği uyarı eşiğinden küçük olamaz.")
            return
        db.save_settings({
            "method": self.method.currentData(),
            "trim_outliers": self.trim.isChecked(),
            "k_warn": self.k_warn.value(), "k_alarm": self.k_alarm.value(),
            "pct_warn": self.p_warn.value(), "pct_alarm": self.p_alarm.value(),
            "min_n": self.min_n.value(),
            "group_by": [k for k, cb in self.group_checks.items() if cb.isChecked()],
            "use_rate": self.use_rate.isChecked(),
            "additive_drop_warn": self.add_w.value(), "additive_drop_alarm": self.add_a.value(),
            "visc_change_warn": self.vis_w.value(), "visc_change_alarm": self.vis_a.value(),
            "tbn_ratio_warn": self.tbn_w.value(), "tbn_ratio_alarm": self.tbn_a.value(),
            "change_rel": self.ch_rel.value(), "change_abs": self.ch_abs.value(),
            "visc_limits": visc,
            "fixed_limits": fixed,
        })
        self.state.reload()
        self.accept()
