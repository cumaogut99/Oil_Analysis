"""İstatistik ve limit önerisi sekmesi + değer inceleme / hariç tutma paneli."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QInputDialog, QLabel, QMessageBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..stats import METHODS, compute_limits, describe
from ..textnorm import fmt_num, format_date
from . import theme
from .common import AppState, FilterBar, MplWidget, button, hint, ro_item, style_table

HEADS = ["Parametre", "Yön", "n", "Hariç", "Min", "Max", "Ortalama", "Std", "Medyan", "P95",
         "Alt uyarı", "Alt alarm", "Üst uyarı", "Üst alarm", "Hız n", "Hız ort. (/100sa)",
         "Hız uyarı", "Hız alarm", "Not"]
DIR_TEXT = {"up": "↑ yüksek kötü", "down": "↓ düşük kötü", "both": "↕ iki yönlü"}
ROBUST_Z = 3.5


def robust_z(values: list[float]) -> list[float | None]:
    """Medyan/MAD tabanlı dayanıklı z-skoru (Iglewicz-Hoaglin)."""
    x = np.array([v for v in values if v is not None], dtype=float)
    if len(x) < 5:
        return [None] * len(values)
    med = np.median(x)
    mad = np.median(np.abs(x - med))
    if mad == 0:
        return [None] * len(values)
    return [None if v is None else float(0.6745 * (v - med) / mad) for v in values]


class StatsTab(QWidget):
    title = "İstatistik & Limitler"
    subtitle = "Popülasyon istatistikleri, önerilen uyarı/alarm limitleri ve istatistik dışı değerler"
    icon = "stats"

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.rows = []
        self.current_key = None
        self._filling = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)

        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 12, 14, 12)
        self.filters = FilterBar(state)
        self.filters.changed.connect(self.refresh)
        cl.addWidget(self.filters)
        opts = QHBoxLayout()
        opts.addWidget(QLabel("Limit yöntemi:"))
        self.method = QComboBox()
        for k, v in METHODS.items():
            self.method.addItem(v, k)
        self.method.currentIndexChanged.connect(self.refresh)
        opts.addWidget(self.method)
        self.c_trim = QCheckBox("Limit hesabında uç değerleri otomatik ayıkla")
        self.c_trim.toggled.connect(self.refresh)
        opts.addWidget(self.c_trim)
        opts.addStretch(1)
        b_save = button("Bu yöntemi varsayılan yap", "save")
        b_save.clicked.connect(self.save_method)
        b_exp = button("Excel'e aktar", "export")
        b_exp.clicked.connect(self.export)
        opts.addWidget(b_save)
        opts.addWidget(b_exp)
        cl.addLayout(opts)
        self.info = hint("")
        cl.addWidget(self.info)
        lay.addWidget(card)

        split = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(0, len(HEADS))
        self.table.setHorizontalHeaderLabels(HEADS)
        style_table(self.table)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.itemSelectionChanged.connect(self._on_select)
        split.addWidget(self.table)

        # ---- değer inceleme paneli
        panel = QFrame()
        panel.setObjectName("Card")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(12, 10, 12, 10)
        self.p_title = QLabel("Değer inceleme")
        self.p_title.setObjectName("SectionTitle")
        pl.addWidget(self.p_title)
        pl.addWidget(hint("Absürt değerleri işaretleyerek istatistik dışı bırakın. Hariç tutulan "
                          "değerler ortalama, min/max, limit, hız ve korelasyon hesaplarına katılmaz. "
                          f"Dayanıklı z > {ROBUST_Z:g} olanlar 'uç değer adayı' olarak vurgulanır."))
        self.plot = MplWidget(toolbar=False)
        self.plot.setMinimumHeight(150)
        pl.addWidget(self.plot, 2)
        self.vtable = QTableWidget(0, 7)
        self.vtable.setHorizontalHeaderLabels(["Hariç", "Değer", "z", "Analiz No", "Motor", "Tarih", "Neden"])
        style_table(self.vtable)
        self.vtable.horizontalHeader().setStretchLastSection(True)
        self.vtable.itemChanged.connect(self._on_value_item_changed)
        pl.addWidget(self.vtable, 3)
        row = QHBoxLayout()
        self.b_suggest = button("Önerilen uç değerleri hariç tut", "wand", "primary")
        self.b_suggest.clicked.connect(self.exclude_suggested)
        self.b_clear = button("Bu parametrede hariçleri kaldır", "include")
        self.b_clear.clicked.connect(self.clear_param)
        row.addWidget(self.b_suggest)
        row.addWidget(self.b_clear)
        row.addStretch(1)
        pl.addLayout(row)
        split.addWidget(panel)
        split.setSizes([900, 520])
        lay.addWidget(split, 1)
        state.changed.connect(self.on_state_changed)
        self.on_state_changed()

    # ------------------------------------------------------------- yükleme
    def on_state_changed(self):
        st = self.state.settings
        self.method.blockSignals(True)
        self.method.setCurrentIndex(max(0, self.method.findData(st.get("method", "normal"))))
        self.method.blockSignals(False)
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

    def _samples(self):
        return [s for s in self.filters.apply(self.state.samples) if not s.is_fresh]

    def refresh(self, *_):
        st = self.state
        samples = self._samples()
        sets = self._settings()
        ev = st.evaluator
        self.rows = []
        for p in st.params:
            all_vals = [s.values.get(p.key) for s in samples]
            if not any(v is not None for v in all_vals):
                continue
            vals = [s.stat_value(p.key) for s in samples]
            n_excl = sum(1 for s in samples if s.values.get(p.key) is not None and s.is_excluded(p.key))
            d = describe(vals)
            lim = compute_limits(vals, p.direction, sets)
            rvals = ([ev.rates.get(s.id, {}).get(p.key) for s in samples if not s.is_excluded(p.key)]
                     if p.key in ev.rate_keys else [])
            rd = describe(rvals) if rvals else {"n": 0}
            rlim = compute_limits(rvals, "up", sets) if rvals else None
            self.rows.append((p, d, lim, rd, rlim, n_excl))
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.rows))
        sel_row = None
        for i, (p, d, lim, rd, rlim, n_excl) in enumerate(self.rows):
            if p.key == self.current_key:
                sel_row = i
            g = d.get
            cells = [
                ro_item(st.param_label(p.key)), ro_item(DIR_TEXT.get(p.direction, p.direction)),
                ro_item(d["n"], d["n"]), ro_item(n_excl or "", n_excl, status=1 if n_excl else None),
                ro_item(fmt_num(g("min"))), ro_item(fmt_num(g("max"))),
                ro_item(fmt_num(g("mean"))), ro_item(fmt_num(g("std"))),
                ro_item(fmt_num(g("median"))), ro_item(fmt_num(g("p95"))),
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
        if sel_row is None and self.rows:
            sel_row = 0
        if sel_row is not None:
            self.table.selectRow(sel_row)
        self.table.blockSignals(False)
        total_excl = sum(r[5] for r in self.rows)
        self.info.setText(
            f"<b>{len(samples)}</b> numune ({self.filters.description()}); sıfır yağlar hariç. "
            f"İstatistik dışı bırakılmış değer: <b>{total_excl}</b>. Yöntem: {METHODS[sets['method']]} — "
            + (f"P{sets['pct_warn']:g}/P{sets['pct_alarm']:g}" if sets["method"] == "percentile"
               else f"μ±{sets['k_warn']:g}σ / μ±{sets['k_alarm']:g}σ")
            + f"; en az {sets['min_n']} numune. Hız = ppm artışı / 100 sa yağ çalışması.")
        self._on_select()

    # --------------------------------------------------------- inceleme
    def _on_select(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        r = rows[0].row() if rows else None
        if r is None or r >= len(self.rows):
            self.current_key = None
            self.vtable.setRowCount(0)
            self.plot.reset()
            self.plot.draw()
            return
        self.current_key = self.rows[r][0].key
        self._fill_values()

    def _value_rows(self):
        key = self.current_key
        samples = [s for s in self._samples() if s.values.get(key) is not None]
        zs = robust_z([s.stat_value(key) for s in samples])
        rows = list(zip(samples, zs))
        rows.sort(key=lambda t: -(t[0].values.get(key) or 0))
        return rows

    def _is_suggested(self, z, direction):
        if z is None:
            return False
        if direction == "up":
            return z > ROBUST_Z
        if direction == "down":
            return z < -ROBUST_Z
        return abs(z) > ROBUST_Z

    def _fill_values(self):
        key = self.current_key
        p = self.state.pmap[key]
        rows = self._value_rows()
        self._vrows = rows
        n_sugg = sum(1 for s, z in rows if self._is_suggested(z, p.direction) and not s.is_excluded(key))
        self.p_title.setText(f"Değer inceleme — {self.state.param_label(key)}")
        self.b_suggest.setText(f"Önerilen uç değerleri hariç tut ({n_sugg})")
        self.b_suggest.setEnabled(n_sugg > 0)
        self._filling = True
        self.vtable.setRowCount(len(rows))
        muted = theme.token("status_excluded_fg", "#94a3b8")
        from PySide6.QtGui import QColor
        for i, (s, z) in enumerate(rows):
            excluded = s.is_excluded(key)
            chk = QTableWidgetItem()
            flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            if not s.stats_excluded:
                flags |= Qt.ItemIsUserCheckable
            chk.setFlags(flags)
            chk.setCheckState(Qt.Checked if excluded else Qt.Unchecked)
            if s.stats_excluded:
                chk.setToolTip("Numunenin tamamı hariç (numune detayından değiştirilir)")
            sugg = self._is_suggested(z, p.direction)
            note = s.stats_note if s.stats_excluded else s.excluded.get(key, "")
            cells = [chk,
                     ro_item(fmt_num(s.values.get(key), 3), s.values.get(key), status=2 if sugg else None),
                     ro_item("" if z is None else f"{z:+.1f}", z,
                             tooltip="Uç değer adayı" if sugg else None),
                     ro_item(s.sample_no), ro_item(s.motor_no or ""),
                     ro_item(format_date(s.date_taken)), QTableWidgetItem(note or "")]
            cells[-1].setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable |
                               (Qt.ItemIsEditable if not s.stats_excluded else Qt.NoItemFlags))
            cells[-1].setToolTip("Neden yazmak için çift tıklayın")
            for c, it in enumerate(cells):
                if excluded and c > 0:
                    it.setForeground(QColor(muted))
                self.vtable.setItem(i, c, it)
        self.vtable.resizeColumnsToContents()
        self._filling = False
        self._draw_hist(rows, key, p.direction)

    def _draw_hist(self, rows, key, direction):
        fig = self.plot.reset()
        ax = fig.add_subplot(111)
        inc = np.array([s.values[key] for s, _z in rows if not s.is_excluded(key)], dtype=float)
        exc = np.array([s.values[key] for s, _z in rows if s.is_excluded(key)], dtype=float)
        # Eksen dahil edilen değerlere göre; aralık dışındaki hariç değerler sayı olarak belirtilir
        base = inc if len(inc) >= 2 else (np.concatenate([inc, exc]) if len(exc) else inc)
        outside = 0
        if len(base):
            lo, hi = float(base.min()), float(base.max())
            pad = (hi - lo) * 0.08 or 1.0
            bins = np.linspace(lo - pad, hi + pad, min(30, max(6, len(base) // 2)) + 1)
            ax.hist(inc, bins=bins, color=theme.token("primary"), alpha=0.85, label="Dahil")
            if len(exc):
                in_rng = exc[(exc >= bins[0]) & (exc <= bins[-1])]
                outside = len(exc) - len(in_rng)
                if len(in_rng):
                    ax.hist(in_rng, bins=bins, color=theme.token("chart_na"), alpha=0.9,
                            label="Hariç", hatch="//")
            ax.set_xlim(bins[0], bins[-1])
        if outside:
            ax.set_title(f"{outside} hariç değer grafik aralığının dışında", fontsize=8,
                         color=theme.token("text_muted"), loc="right")
        lim = next((r[2] for r in self.rows if r[0].key == key), None)
        if lim is not None:
            for v, col in ((lim.hi_warn, "chart_warn"), (lim.hi_alarm, "chart_alarm"),
                           (lim.lo_warn, "chart_warn"), (lim.lo_alarm, "chart_alarm")):
                if v is not None and len(base) and bins[0] <= v <= bins[-1]:
                    ax.axvline(v, color=theme.token(col), ls="--", lw=1.2)
        ax.set_yticks([])
        ax.spines["left"].set_visible(False)
        if ax.get_legend_handles_labels()[0] and len(exc):
            ax.legend(loc="upper left")
        self.plot.draw()

    def _on_value_item_changed(self, item: QTableWidgetItem):
        if self._filling or self.current_key is None:
            return
        r, c = item.row(), item.column()
        s, _z = self._vrows[r]
        if s.stats_excluded:
            return
        key = self.current_key
        chk = self.vtable.item(r, 0)
        note_item = self.vtable.item(r, 6)
        want = chk.checkState() == Qt.Checked
        note = note_item.text().strip() if note_item else ""
        if c == 6 and not want and note:
            want = True  # neden yazıldıysa hariç tut
        self.state.db.set_excluded(s.id, key, want, note)
        self.state.reload()

    def exclude_suggested(self):
        key = self.current_key
        if key is None:
            return
        p = self.state.pmap[key]
        cand = [s for s, z in self._value_rows() if self._is_suggested(z, p.direction)
                and not s.is_excluded(key)]
        if not cand:
            return
        lst = "\n".join(f"  {s.sample_no} ({s.motor_no or '-'}): {fmt_num(s.values[key], 3)}" for s in cand[:15])
        note, ok = QInputDialog.getText(
            self, "Uç değerleri hariç tut",
            f"{len(cand)} değer istatistik dışı bırakılacak:\n{lst}\n\nNeden (opsiyonel):",
            text="Uç değer (dayanıklı z > 3.5)")
        if not ok:
            return
        for s in cand:
            self.state.db.set_excluded(s.id, key, True, note, commit=False)
        self.state.db.commit()
        self.state.reload()

    def clear_param(self):
        key = self.current_key
        if key is None:
            return
        if QMessageBox.question(self, "Hariçleri kaldır",
                                f"{self.state.param_label(key)} için tüm hariç tutmalar kaldırılsın mı?\n"
                                "(Tamamen hariç tutulmuş numuneler etkilenmez)") != QMessageBox.Yes:
            return
        self.state.db.clear_exclusions(key)
        self.state.reload()

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
        for p, d, lim, rd, rlim, n_excl in self.rows:
            ws.append([self.state.param_label(p.key), DIR_TEXT.get(p.direction), d["n"], n_excl,
                       d.get("min"), d.get("max"), d.get("mean"), d.get("std"), d.get("median"),
                       d.get("p95"), lim.lo_warn, lim.lo_alarm, lim.hi_warn, lim.hi_alarm,
                       rd.get("n"), rd.get("mean"), rlim.hi_warn if rlim else None,
                       rlim.hi_alarm if rlim else None, lim.note])
        wx = wb.create_sheet("Hariç Tutulanlar")
        wx.append(["Analiz No", "Motor", "Tarih", "Parametre", "Değer", "Neden"])
        for s in self._samples():
            for key in s.values:
                if s.is_excluded(key):
                    wx.append([s.sample_no, s.motor_no, s.date_taken, self.state.param_label(key),
                               s.values.get(key), s.stats_note if s.stats_excluded else s.excluded.get(key)])
        try:
            wb.save(path)
        except OSError as exc:
            QMessageBox.critical(self, "Hata", str(exc))
