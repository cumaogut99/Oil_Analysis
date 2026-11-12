"""Grafik noktalarında fare ile üzerine gelince bilgi kutusu (tooltip) ve vurgulama."""
from __future__ import annotations

import numpy as np
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QToolTip

from . import theme


class ChartHover:
    """matplotlib grafiğine Qt tooltip'i ve grup (motor) vurgulaması ekler.

    add_points(scatter, htmls, groups): her nokta için HTML metin ve grup adı
    add_line(group, line): aynı gruba ait çizgiler (vurgulama için)
    """

    def __init__(self, canvas, radius_px: float = 9.0):
        self.canvas = canvas
        self.radius = radius_px
        self.clear()
        canvas.mpl_connect("motion_notify_event", self._on_move)
        canvas.mpl_connect("figure_leave_event", lambda _e: self._reset())
        canvas.mpl_connect("axes_leave_event", lambda _e: self._reset())

    def clear(self):
        self.items = []          # (artist, htmls, groups)
        self.lines = {}          # grup -> [Line2D]
        self.rings = {}          # ax -> vurgulama halkası
        self._current = None
        self._group = None

    def add_points(self, artist, htmls, groups=None):
        self.items.append((artist, list(htmls), list(groups) if groups else [None] * len(htmls)))

    def add_line(self, group, line):
        line._base_lw = line.get_linewidth()
        line._base_alpha = line.get_alpha() if line.get_alpha() is not None else 1.0
        self.lines.setdefault(group, []).append(line)

    # ---------------------------------------------------------------- olay
    def _hit(self, event):
        best = None
        for artist, htmls, groups in self.items:
            if artist.axes is not event.inaxes or not artist.get_visible():
                continue
            offs = np.asarray(artist.get_offsets(), dtype=float)
            if not len(offs):
                continue
            pix = artist.axes.transData.transform(offs)
            d = np.hypot(pix[:, 0] - event.x, pix[:, 1] - event.y)
            i = int(np.argmin(d))
            if d[i] <= self.radius and (best is None or d[i] < best[0]):
                best = (d[i], artist, i, htmls[i], groups[i], offs[i])
        return best

    def _on_move(self, event):
        if event.inaxes is None:
            self._reset()
            return
        hit = self._hit(event)
        if hit is None:
            if self._current is not None:
                self._reset()
            return
        _d, artist, i, html, group, xy = hit
        key = (id(artist), i)
        if key == self._current:
            return
        self._current = key
        QToolTip.showText(QCursor.pos(), html, self.canvas)
        self._ring(artist.axes, xy)
        self._highlight(group)
        self.canvas.draw_idle()

    def _ring(self, ax, xy):
        for r in self.rings.values():
            r.set_visible(False)
        ring = self.rings.get(ax)
        if ring is None:
            ring = ax.scatter([xy[0]], [xy[1]], s=190, facecolors="none",
                              edgecolors=theme.token("primary", "#2563eb"), linewidths=2.0, zorder=50)
            self.rings[ax] = ring
        ring.set_offsets([xy])
        ring.set_visible(True)

    def _highlight(self, group):
        if group == self._group or len(self.lines) < 2:
            self._group = group
            return
        self._group = group
        for g, lines in self.lines.items():
            for ln in lines:
                if group is None:
                    ln.set_linewidth(ln._base_lw)
                    ln.set_alpha(ln._base_alpha)
                elif g == group:
                    ln.set_linewidth(ln._base_lw + 1.8)
                    ln.set_alpha(1.0)
                    ln.set_zorder(20)
                else:
                    ln.set_alpha(0.15)
                    ln.set_zorder(1)

    def _reset(self):
        if self._current is None and self._group is None:
            return
        self._current = None
        QToolTip.hideText()
        for r in self.rings.values():
            r.set_visible(False)
        self._highlight(None)
        self.canvas.draw_idle()
