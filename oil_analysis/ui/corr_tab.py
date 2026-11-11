"""Parametreler arası ilişki (korelasyon) sekmesi."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QSplitter,
                               QVBoxLayout, QWidget)

from ..parameters import CATEGORIES, PARTICLE
from ..stats import correlation
from .common import AppState, FilterBar, MplWidget

HOURS = {"_motor_hours": "Motor saati", "_oil_hours": "Yağ saati"}


class CorrelationTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.keys, self.r, self.n, self.cols = [], None, None, {}
        lay = QVBoxLayout(self)
        self.filters = FilterBar(state)
        self.filters.changed.connect(self.refresh)
        lay.addWidget(self.filters)
        opts = QHBoxLayout()
        opts.addWidget(QLabel("Yöntem:"))
        self.method = QComboBox()
        self.method.addItem("Spearman (sıra, uç değere dayanıklı)", "spearman")
        self.method.addItem("Pearson (doğrusal)", "pearson")
        self.method.currentIndexChanged.connect(self.refresh)
        opts.addWidget(self.method)
        self.c_rate = QCheckBox("Artış hızlarıyla (ppm/100 sa)")
        self.c_rate.toggled.connect(self.refresh)
        opts.addWidget(self.c_rate)
        opts.addWidget(QLabel("  Kategoriler:"))
        self.cat_checks = {}
        for c in CATEGORIES:
            cb = QCheckBox(c)
            cb.setChecked(c != PARTICLE)
            cb.toggled.connect(self.refresh)
            opts.addWidget(cb)
            self.cat_checks[c] = cb
        opts.addStretch(1)
        lay.addLayout(opts)
        self.info = QLabel("Isı haritasında bir hücreye tıklayarak iki parametrenin dağılım grafiğini görün. "
                           "|r| ≥ 0.7 güçlü, 0.4–0.7 orta ilişki. Korelasyon nedensellik göstermez.")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        split = QSplitter(Qt.Horizontal)
        self.heat = MplWidget()
        self.scatter = MplWidget()
        split.addWidget(self.heat)
        split.addWidget(self.scatter)
        split.setSizes([800, 450])
        lay.addWidget(split, 1)
        self.heat.canvas.mpl_connect("button_press_event", self.on_click)
        state.changed.connect(self.on_state_changed)
        self.on_state_changed()

    def on_state_changed(self):
        self.filters.refresh_options()
        self.refresh()

    def refresh(self, *_):
        st = self.state
        samples = [s for s in self.filters.apply(st.samples) if not s.is_fresh]
        use_rate = self.c_rate.isChecked()
        cats = {c for c, cb in self.cat_checks.items() if cb.isChecked()}
        cols = {}
        if not use_rate:
            cols["_motor_hours"] = [s.motor_hours for s in samples]
            cols["_oil_hours"] = [s.oil_hours for s in samples]
        ev = st.evaluator
        for p in st.params:
            if p.category not in cats:
                continue
            if use_rate:
                if p.key not in ev.rate_keys:
                    continue
                vals = [ev.rates.get(s.id, {}).get(p.key) for s in samples]
            else:
                vals = [s.values.get(p.key) for s in samples]
            arr = [v for v in vals if v is not None]
            if len(arr) >= 5 and len(set(arr)) > 1:
                cols[p.key] = vals
        self.cols = cols
        self.samples = samples
        fig = self.heat.figure
        fig.clear()
        if len(cols) < 2:
            self.r = None
            self.heat.draw()
            return
        self.keys, self.r, self.n = correlation(cols, self.method.currentData())
        ax = fig.add_subplot(111)
        im = ax.imshow(self.r, cmap="RdBu_r", vmin=-1, vmax=1)
        labels = [HOURS.get(k) or st.pmap[k].name.split(" (")[0] for k in self.keys]
        ax.set_xticks(range(len(labels)), labels, rotation=90, fontsize=7)
        ax.set_yticks(range(len(labels)), labels, fontsize=7)
        if len(labels) <= 25:
            for i in range(len(labels)):
                for j in range(len(labels)):
                    v = self.r[i, j]
                    if not np.isnan(v) and i != j:
                        ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=5.5,
                                color="white" if abs(v) > 0.6 else "black")
        fig.colorbar(im, ax=ax, shrink=0.8)
        ax.set_title(f"Korelasyon matrisi — {len(samples)} numune", fontsize=10)
        self.heat.draw()
        self._draw_top_pairs()

    def _draw_top_pairs(self):
        """En güçlü ilişkileri sağ panelde listeler."""
        fig = self.scatter.figure
        fig.clear()
        ax = fig.add_subplot(111)
        ax.axis("off")
        pairs = []
        k = len(self.keys)
        for i in range(k):
            for j in range(i + 1, k):
                v = self.r[i, j]
                if not np.isnan(v):
                    pairs.append((abs(v), v, i, j))
        pairs.sort(reverse=True)
        lines = ["En güçlü ilişkiler (|r|, n):", ""]
        for _a, v, i, j in pairs[:20]:
            lines.append(f"{v:+.2f}  (n={self.n[i, j]})   {self._name(i)} ↔ {self._name(j)}")
        ax.text(0, 1, "\n".join(lines), va="top", family="monospace", fontsize=8)
        self.scatter.draw()

    def _name(self, i):
        k = self.keys[i]
        return HOURS.get(k) or self.state.pmap[k].name.split(" (")[0]

    def on_click(self, event):
        if event.inaxes is None or self.r is None or event.xdata is None:
            return
        j, i = int(round(event.xdata)), int(round(event.ydata))
        if not (0 <= i < len(self.keys) and 0 <= j < len(self.keys)) or i == j:
            return
        a, b = self.cols[self.keys[j]], self.cols[self.keys[i]]
        pts = [(x, y, s) for x, y, s in zip(a, b, self.samples) if x is not None and y is not None]
        fig = self.scatter.figure
        fig.clear()
        ax = fig.add_subplot(111)
        motors = sorted({s.motor_no or "?" for _x, _y, s in pts})
        cmap = {m: i for i, m in enumerate(motors)}
        ax.scatter([p[0] for p in pts], [p[1] for p in pts],
                   c=[cmap[p[2].motor_no or "?"] for p in pts], cmap="tab20", s=25)
        if len(pts) >= 3:
            xs = np.array([p[0] for p in pts], dtype=float)
            ys = np.array([p[1] for p in pts], dtype=float)
            if np.ptp(xs) > 0:
                m, c = np.polyfit(xs, ys, 1)
                xx = np.linspace(xs.min(), xs.max(), 50)
                ax.plot(xx, m * xx + c, "--", color="#c62828", lw=1)
        ax.set_xlabel(self._name(j), fontsize=8)
        ax.set_ylabel(self._name(i), fontsize=8)
        ax.set_title(f"r = {self.r[i, j]:+.2f}  (n={self.n[i, j]}) — renk: motor", fontsize=9)
        ax.grid(alpha=0.3)
        self.scatter.draw()
