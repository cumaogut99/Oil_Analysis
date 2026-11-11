"""Trend grafikleri: tek motorun geçmişi veya filtrelenmiş tüm motorlar."""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QLabel, QListWidget,
                               QListWidgetItem, QSplitter, QVBoxLayout, QWidget)

from . import theme
from .common import AppState, FilterBar, MplWidget, hint

ALL_MOTORS = "— Tüm motorlar (filtreye göre) —"
X_OPTIONS = {"Motor çalışma saati": "motor_hours", "Yağ çalışma saati": "oil_hours",
             "Numune tarihi": "date_taken"}
DEFAULT_KEYS = ["fe", "cu", "al", "pb"]


class TrendTab(QWidget):
    title = "Trend"
    subtitle = "Motor bazında veya filtrelenmiş tüm motorlarda parametre trendleri"
    icon = "trend"

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)
        fcard = QFrame()
        fcard.setObjectName("Card")
        fl = QVBoxLayout(fcard)
        fl.setContentsMargins(14, 10, 14, 10)
        self.filters = FilterBar(state)
        self.filters.changed.connect(self.redraw)
        fl.addWidget(self.filters)
        lay.addWidget(fcard)
        split = QSplitter(Qt.Horizontal)
        lay.addWidget(split, 1)

        left = QFrame()
        left.setObjectName("Card")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 12, 12)
        ll.addWidget(QLabel("Motor:"))
        self.motor = QComboBox()
        self.motor.currentIndexChanged.connect(self.redraw)
        ll.addWidget(self.motor)
        ll.addWidget(QLabel("X ekseni:"))
        self.xaxis = QComboBox()
        self.xaxis.addItems(list(X_OPTIONS))
        self.xaxis.currentIndexChanged.connect(self.redraw)
        ll.addWidget(self.xaxis)
        self.c_lim = QCheckBox("Uyarı/alarm limitlerini göster")
        self.c_lim.setChecked(True)
        self.c_lim.toggled.connect(self.redraw)
        ll.addWidget(self.c_lim)
        self.c_rate = QCheckBox("Artış hızını çiz (ppm/100 sa)")
        self.c_rate.toggled.connect(self.redraw)
        ll.addWidget(self.c_rate)
        ll.addWidget(QLabel("Parametreler (en fazla 8):"))
        self.plist = QListWidget()
        self.plist.itemChanged.connect(self.redraw)
        ll.addWidget(self.plist, 1)
        ll.addWidget(hint("Nokta rengi: yeşil normal, turuncu uyarı, kırmızı alarm. "
                          "✕ işaretli noktalar istatistikten hariç tutulmuştur."))
        split.addWidget(left)
        pcard = QFrame()
        pcard.setObjectName("Card")
        pl = QVBoxLayout(pcard)
        pl.setContentsMargins(8, 8, 8, 8)
        self.plot = MplWidget()
        pl.addWidget(self.plot)
        split.addWidget(pcard)
        split.setSizes([260, 1000])
        state.changed.connect(self.on_state_changed)
        self.on_state_changed()

    def on_state_changed(self):
        self.filters.refresh_options()
        cur = self.motor.currentText()
        self.motor.blockSignals(True)
        self.motor.clear()
        self.motor.addItem(ALL_MOTORS)
        self.motor.addItems(sorted({s.motor_no for s in self.state.samples if s.motor_no}))
        i = self.motor.findText(cur)
        self.motor.setCurrentIndex(i if i >= 0 else 0)
        self.motor.blockSignals(False)
        checked = self._checked_keys() or DEFAULT_KEYS
        self.plist.blockSignals(True)
        self.plist.clear()
        for p in self.state.params:
            it = QListWidgetItem(self.state.param_label(p.key))
            it.setData(Qt.UserRole, p.key)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if p.key in checked else Qt.Unchecked)
            self.plist.addItem(it)
        self.plist.blockSignals(False)
        self.redraw()

    def _checked_keys(self):
        return [self.plist.item(i).data(Qt.UserRole) for i in range(self.plist.count())
                if self.plist.item(i).checkState() == Qt.Checked]

    def _x(self, s, xkey):
        v = getattr(s, xkey)
        if xkey == "date_taken":
            try:
                return dt.date.fromisoformat(v) if v else None
            except ValueError:
                return None
        return v

    def redraw(self, *_):
        st = self.state
        fig = self.plot.reset()
        keys = self._checked_keys()[:8]
        if not keys:
            self.plot.draw()
            return
        xkey = X_OPTIONS[self.xaxis.currentText()]
        motor = self.motor.currentText()
        samples = self.filters.apply(st.samples)
        single = motor and motor != ALL_MOTORS
        if single:
            samples = [s for s in samples if s.motor_no == motor]
        use_rate = self.c_rate.isChecked()
        ncols = 2 if len(keys) > 3 else 1
        nrows = (len(keys) + ncols - 1) // ncols
        axes = fig.subplots(nrows, ncols, squeeze=False, sharex=True)
        ev = st.evaluator
        for idx, key in enumerate(keys):
            ax = axes[idx // ncols][idx % ncols]
            p = st.pmap.get(key)
            title = st.param_label(key) + (" — artış hızı (/100 sa)" if use_rate else "")
            ax.set_title(title, fontsize=9)
            groups: dict[str, list] = {}
            for s in samples:
                y = ev.rates.get(s.id, {}).get(key) if use_rate else s.values.get(key)
                x = self._x(s, xkey)
                if y is None or x is None:
                    continue
                stt = ev.evaluate(s).get(key)
                groups.setdefault(s.motor_no or "?", []).append(
                    (x, y, stt.status if stt else None, s, s.is_excluded(key)))
            for mno, pts in groups.items():
                pts.sort(key=lambda t: t[0])
                xs, ys = [t[0] for t in pts], [t[1] for t in pts]
                inc = [t for t in pts if not t[4]]
                exc = [t for t in pts if t[4]]
                if single:
                    ax.plot(xs, ys, "-", color=theme.token("chart_line"), lw=1.4, zorder=1, alpha=0.8)
                    ax.scatter([t[0] for t in inc], [t[1] for t in inc],
                               c=[theme.chart_status(t[2]) for t in inc], s=42, zorder=2,
                               edgecolors=theme.token("surface"), linewidths=1.0)
                    for x, y, _st, s, _e in pts:
                        ax.annotate(s.sample_no[-3:], (x, y), fontsize=6, xytext=(3, 4),
                                    textcoords="offset points", color=theme.token("text_muted"))
                else:
                    ax.plot([t[0] for t in inc], [t[1] for t in inc], "-o", ms=3, lw=0.9,
                            alpha=0.8, label=mno)
                if exc:
                    ax.scatter([t[0] for t in exc], [t[1] for t in exc], marker="x", s=40,
                               color=theme.token("chart_na"), zorder=3, linewidths=1.4)
            # Limit çizgileri: referans grubu, son numuneye göre
            if self.c_lim.isChecked() and samples:
                ref = samples[-1] if single else next((s for s in reversed(samples) if not s.is_fresh), None)
                if ref is not None and not ref.is_fresh:
                    lim = ev.rate_limits(ref, key) if use_rate else ev.limits(ref, key)
                    if lim is not None:
                        for v, col, ls in ((lim.hi_warn, "chart_warn", "--"), (lim.hi_alarm, "chart_alarm", "--"),
                                           (lim.lo_warn, "chart_warn", ":"), (lim.lo_alarm, "chart_alarm", ":")):
                            if v is not None:
                                ax.axhline(v, color=theme.token(col), ls=ls, lw=1.1)
                    if key == "visc100" and not use_rate and ref.oil_type:
                        rng = st.settings.get("visc_limits", {}).get(ref.oil_type)
                        if rng:
                            ax.axhspan(rng[0], rng[1], color=theme.token("chart_band"), alpha=0.08)
            if p is not None and p.unit and not use_rate:
                ax.set_ylabel(p.unit, fontsize=8)
            ax.tick_params(labelsize=7)
            if not single and idx == 0 and 1 < len(groups) <= 15:
                ax.legend(fontsize=6, ncol=2)
        for idx in range(len(keys), nrows * ncols):
            axes[idx // ncols][idx % ncols].set_visible(False)
        for ax in axes[-1]:
            ax.set_xlabel(self.xaxis.currentText(), fontsize=8)
        if xkey == "date_taken":
            fig.autofmt_xdate()
        fig.suptitle(("Motor " + motor) if single else f"Tüm motorlar — {self.filters.description()}",
                     fontsize=10)
        self.plot.draw()
