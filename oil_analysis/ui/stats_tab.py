"""İstatistik ve limit önerisi sekmesi."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QSplitter, QTableWidget, QVBoxLayout,
                               QWidget)

from ..stats import METHODS, compute_limits, describe
from ..textnorm import fmt_num
from .common import AppState, FilterBar, MplWidget, ro_item

HEADS = ["Parametre", "Yön", "n", "Min", "Max", "Ortalama", "Std", "Medyan", "P95",
         "Alt uyarı", "Alt alarm", "Üst uyarı", "Üst alarm", "Hız n", "Hız ort. (/100sa)",
         "Hız uyarı", "Hız alarm", "Not"]
DIR_TEXT = {"up": "↑ yüksek kötü", "down": "↓ düşük kötü", "both": "↕ iki yönlü"}


class StatsTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.rows = []
        lay = QVBoxLayout(self)
        self.filters = FilterBar(state)
        self.filters.changed.connect(self.refresh)
        lay.addWidget(self.filters)
        opts = QHBoxLayout()
        opts.addWidget(QLabel("Limit yöntemi:"))
        self.method = QComboBox()
        for k, v in METHODS.items():
            self.method.addItem(v, k)
        self.method.currentIndexChanged.connect(self.refresh)
        opts.addWidget(self.method)
        self.c_trim = QCheckBox("Uç değerleri ayıkla")
        self.c_trim.toggled.connect(self.refresh)
        opts.addWidget(self.c_trim)
        opts.addStretch(1)
        b_save = QPushButton("Bu yöntemi varsayılan yap")
        b_save.clicked.connect(self.save_method)
        b_exp = QPushButton("Excel'e aktar…")
        b_exp.clicked.connect(self.export)
        opts.addWidget(b_save)
        opts.addWidget(b_exp)
        lay.addLayout(opts)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        split = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, len(HEADS))
        self.table.setHorizontalHeaderLabels(HEADS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(False)
        self.table.itemSelectionChanged.connect(self.draw_hist)
        split.addWidget(self.table)
        self.plot = MplWidget()
        split.addWidget(self.plot)
        split.setSizes([500, 300])
        lay.addWidget(split, 1)
        state.changed.connect(self.on_state_changed)
        self.on_state_changed()

    def on_state_changed(self):
        st = self.state.settings
        for w, val in ((self.method, st.get("method", "normal")),):
            w.blockSignals(True)
            w.setCurrentIndex(max(0, w.findData(val)))
            w.blockSignals(False)
        self.c_trim.blockSignals(True)
        self.c_trim.setChecked(bool(st.get("trim_outliers", True)))
        self.c_trim.blockSignals(False)
        self.filters.refresh_options()
        self.refresh()

    def _settings(self):
        s = dict(self.state.settings)
        s["method"] = self.method.currentData()
        s["trim_outliers"] = self.c_trim.isChecked()
        return s

    def save_method(self):
        self.state.db.save_settings({"method": self.method.currentData(),
                                     "trim_outliers": self.c_trim.isChecked()})
        self.state.reload()

    def refresh(self, *_):
        st = self.state
        samples = [s for s in self.filters.apply(st.samples) if not s.is_fresh]
        sets = self._settings()
        ev = st.evaluator
        self.rows = []
        for p in st.params:
            vals = [s.values.get(p.key) for s in samples]
            d = describe(vals)
            if d["n"] == 0:
                continue
            lim = compute_limits(vals, p.direction, sets)
            rvals = [ev.rates.get(s.id, {}).get(p.key) for s in samples] if p.key in ev.rate_keys else []
            rd = describe(rvals) if rvals else {"n": 0}
            rlim = compute_limits(rvals, "up", sets) if rvals else None
            self.rows.append((p, d, lim, rd, rlim, vals))
        self.table.setRowCount(len(self.rows))
        for i, (p, d, lim, rd, rlim, _v) in enumerate(self.rows):
            cells = [
                ro_item(st.param_label(p.key)), ro_item(DIR_TEXT.get(p.direction, p.direction)),
                ro_item(d["n"]), ro_item(fmt_num(d["min"])), ro_item(fmt_num(d["max"])),
                ro_item(fmt_num(d["mean"])), ro_item(fmt_num(d["std"])),
                ro_item(fmt_num(d["median"])), ro_item(fmt_num(d["p95"])),
                ro_item(fmt_num(lim.lo_warn), status=1 if lim.lo_warn is not None else None),
                ro_item(fmt_num(lim.lo_alarm), status=2 if lim.lo_alarm is not None else None),
                ro_item(fmt_num(lim.hi_warn), status=1 if lim.hi_warn is not None else None),
                ro_item(fmt_num(lim.hi_alarm), status=2 if lim.hi_alarm is not None else None),
                ro_item(rd.get("n", 0) or ""), ro_item(fmt_num(rd.get("mean"))),
                ro_item(fmt_num(rlim.hi_warn) if rlim else ""),
                ro_item(fmt_num(rlim.hi_alarm) if rlim else ""),
                ro_item(lim.note),
            ]
            for c, it in enumerate(cells):
                self.table.setItem(i, c, it)
        self.table.resizeColumnsToContents()
        self.info.setText(
            f"<b>{len(samples)}</b> numune ({self.filters.description()}). Sıfır yağ numuneleri "
            f"hariç. Yöntem: {METHODS[sets['method']]}; uyarı/alarm: "
            + (f"P{sets['pct_warn']:g}/P{sets['pct_alarm']:g}" if sets["method"] == "percentile"
               else f"μ+{sets['k_warn']:g}σ / μ+{sets['k_alarm']:g}σ")
            + f"; en az {sets['min_n']} numune. Hız = ppm artışı / 100 sa yağ çalışması "
              "(aynı yağ dönemindeki önceki numuneye, yoksa sıfır yağa göre).")
        self.draw_hist()

    def draw_hist(self):
        fig = self.plot.figure
        fig.clear()
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        r = rows[0].row() if rows else (self.table.currentRow() if self.table.currentRow() >= 0 else None)
        if r is None or r >= len(self.rows):
            self.plot.draw()
            return
        p, d, lim, _rd, _rl, vals = self.rows[r]
        x = np.array([v for v in vals if v is not None], dtype=float)
        ax = fig.add_subplot(111)
        ax.hist(x, bins=min(30, max(5, len(x) // 2)), color="#90a4ae", edgecolor="white")
        for v, col, lab in ((lim.hi_warn, "#f9a825", "Üst uyarı"), (lim.hi_alarm, "#c62828", "Üst alarm"),
                            (lim.lo_warn, "#f9a825", "Alt uyarı"), (lim.lo_alarm, "#c62828", "Alt alarm")):
            if v is not None:
                ax.axvline(v, color=col, ls="--", label=f"{lab}: {fmt_num(v)}")
        ax.set_title(f"{self.state.param_label(p.key)} dağılımı (n={len(x)})", fontsize=10)
        if ax.get_legend_handles_labels()[0]:
            ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        self.plot.draw()

    def export(self):
        if not self.rows:
            return
        path, _ = QFileDialog.getSaveFileName(self, "İstatistikleri kaydet", "istatistik.xlsx",
                                              "Excel (*.xlsx)")
        if not path:
            return
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "İstatistik"
        ws.append([f"Filtre: {self.filters.description()}",
                   f"Yöntem: {METHODS[self.method.currentData()]}"])
        ws.append(HEADS)
        for p, d, lim, rd, rlim, _v in self.rows:
            ws.append([self.state.param_label(p.key), DIR_TEXT.get(p.direction), d["n"], d["min"],
                       d["max"], d["mean"], d["std"], d["median"], d["p95"], lim.lo_warn,
                       lim.lo_alarm, lim.hi_warn, lim.hi_alarm, rd.get("n"), rd.get("mean"),
                       rlim.hi_warn if rlim else None, rlim.hi_alarm if rlim else None, lim.note])
        try:
            wb.save(path)
        except OSError as exc:
            QMessageBox.critical(self, "Hata", str(exc))
