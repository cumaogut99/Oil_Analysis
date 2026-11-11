"""Arayüzde ortak kullanılan bileşenler."""
from __future__ import annotations

import matplotlib

matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel,  # noqa: E402
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..db import FRESH_OIL, PLATFORM_GROUPS, SAMPLE_TYPES, Database  # noqa: E402
from ..evaluation import Evaluator  # noqa: E402

STATUS_BG = {0: QColor("#d7f0d8"), 1: QColor("#fff3a6"), 2: QColor("#f5a3a3")}
STATUS_MPL = {None: "#9e9e9e", 0: "#2e7d32", 1: "#f9a825", 2: "#c62828"}
ALL = "Tümü"


class AppState(QObject):
    """Veritabanı, ayarlar, numuneler ve değerlendirici - tek yerden."""
    changed = Signal()

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.reload(emit=False)

    def set_db(self, db: Database):
        if self.db is not None:
            self.db.close()
        self.db = db
        self.reload()

    def reload(self, emit: bool = True):
        self.settings = self.db.settings()
        self.params = self.db.parameters()
        self.pmap = {p.key: p for p in self.params}
        self.samples = self.db.load_samples()
        self.platforms = self.db.platforms()
        self.evaluator = Evaluator(self.samples, self.params, self.settings)
        if emit:
            self.changed.emit()

    def param_label(self, key: str) -> str:
        p = self.pmap.get(key)
        if p is None:
            return key
        return f"{p.name} [{p.unit}]" if p.unit else p.name

    def oil_types(self) -> list[str]:
        return sorted({s.oil_type for s in self.samples if s.oil_type}
                      | set(self.settings.get("visc_limits", {})))


class NumItem(QTableWidgetItem):
    """Sayısal sıralanabilen tablo hücresi."""

    def __init__(self, text: str, sort_value=None):
        super().__init__(text)
        self.sort_value = sort_value

    def __lt__(self, other):
        a = self.sort_value
        b = getattr(other, "sort_value", None)
        if a is None and b is None:
            return self.text() < other.text()
        if a is None:
            return True
        if b is None:
            return False
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


def ro_item(text, sort_value=None, status=None, tooltip=None) -> QTableWidgetItem:
    it = NumItem("" if text is None else str(text), sort_value)
    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    if status in STATUS_BG:
        it.setBackground(STATUS_BG[status])
    if tooltip:
        it.setToolTip(tooltip)
    return it


class MplWidget(QWidget):
    def __init__(self, parent=None, toolbar=True):
        super().__init__(parent)
        self.figure = Figure(figsize=(6, 4), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        if toolbar:
            lay.addWidget(NavigationToolbar2QT(self.canvas, self))
        lay.addWidget(self.canvas)

    def draw(self):
        self.canvas.draw_idle()


class FilterBar(QWidget):
    """Platform grubu / platform / yağ tipi / numune tipi / motor filtresi."""
    changed = Signal()

    def __init__(self, state: AppState, with_motor=False, with_fresh=False, parent=None):
        super().__init__(parent)
        self.state = state
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.group = self._combo(lay, "Platform grubu:")
        self.platform = self._combo(lay, "Platform:")
        self.oil = self._combo(lay, "Yağ tipi:")
        self.stype = self._combo(lay, "Numune tipi:")
        self.motor = self._combo(lay, "Motor:") if with_motor else None
        self.fresh = None
        if with_fresh:
            self.fresh = QCheckBox("Sıfır yağları göster")
            self.fresh.toggled.connect(self.changed)
            lay.addWidget(self.fresh)
        lay.addStretch(1)
        self.refresh_options()

    def _combo(self, lay, label):
        lay.addWidget(QLabel(label))
        cb = QComboBox()
        cb.setMinimumWidth(110)
        cb.currentIndexChanged.connect(lambda _i: self.changed.emit())
        lay.addWidget(cb)
        return cb

    @staticmethod
    def _fill(cb: QComboBox, items):
        cur = cb.currentText()
        cb.blockSignals(True)
        cb.clear()
        cb.addItem(ALL)
        cb.addItems([i for i in items if i])
        idx = cb.findText(cur)
        cb.setCurrentIndex(idx if idx >= 0 else 0)
        cb.blockSignals(False)

    def refresh_options(self):
        st = self.state
        self._fill(self.group, PLATFORM_GROUPS)
        self._fill(self.platform, sorted(st.platforms))
        self._fill(self.oil, st.oil_types())
        self._fill(self.stype, [t for t in SAMPLE_TYPES if t != FRESH_OIL])
        if self.motor is not None:
            self._fill(self.motor, sorted({s.motor_no for s in st.samples if s.motor_no}))

    def apply(self, samples, include_fresh=None):
        g, p, o, t = (self.group.currentText(), self.platform.currentText(),
                      self.oil.currentText(), self.stype.currentText())
        m = self.motor.currentText() if self.motor is not None else ALL
        if include_fresh is None:
            include_fresh = bool(self.fresh and self.fresh.isChecked())
        out = []
        for s in samples:
            if s.is_fresh:
                if include_fresh and (o == ALL or s.oil_type == o):
                    out.append(s)
                continue
            if g != ALL and s.platform_group != g:
                continue
            if p != ALL and (s.platform_code or "") != p:
                continue
            if o != ALL and (s.oil_type or "") != o:
                continue
            if t != ALL and s.sample_type != t:
                continue
            if m != ALL and s.motor_no != m:
                continue
            out.append(s)
        return out

    def description(self) -> str:
        parts = []
        for lab, cb in (("Grup", self.group), ("Platform", self.platform), ("Yağ", self.oil),
                        ("Tip", self.stype), ("Motor", self.motor)):
            if cb is not None and cb.currentText() != ALL:
                parts.append(f"{lab}: {cb.currentText()}")
        return ", ".join(parts) or "Tüm numuneler"
