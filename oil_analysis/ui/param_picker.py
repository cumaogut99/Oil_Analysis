"""Hazır gruplu, çoklu seçimli parametre seçici (açılır panel)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QGridLayout, QListWidget, QListWidgetItem, QMenu, QToolButton,
                               QVBoxLayout, QWidget, QWidgetAction)

from ..parameters import ADDITIVE, CONTAMINANT, FTIR, PHYSICAL, WEAR
from . import theme
from .common import button, hint

ELEMENT_CATEGORIES = (WEAR, CONTAMINANT, ADDITIVE)


def element_keys(params):
    """Spektrometri ile ölçülen tüm elementler (PQ hariç)."""
    return [p.key for p in params if p.category in ELEMENT_CATEGORIES and p.key != "pq"]


PRESETS = [
    ("Tüm elementler (spektrometri)", lambda ps: element_keys(ps)),
    ("Aşınma elementleri", lambda ps: [p.key for p in ps if p.category == WEAR and p.key != "pq"]),
    ("Kirletici elementler", lambda ps: [p.key for p in ps if p.category == CONTAMINANT]),
    ("Katkı elementleri", lambda ps: [p.key for p in ps if p.category == ADDITIVE]),
    ("Fiziksel (viskozite, TBN, TAN)", lambda ps: [p.key for p in ps if p.category == PHYSICAL]),
    ("FTIR / kirlilik", lambda ps: [p.key for p in ps if p.category == FTIR]),
]


class ParamPicker(QToolButton):
    """changed sinyali: seçim değişti. auto=True ise 'uyarı/alarm verenler' modu."""
    changed = Signal()

    def __init__(self, state, allow_auto: bool = True, default_auto: bool = True,
                 default_keys=None, parent=None):
        super().__init__(parent)
        self.state = state
        self.allow_auto = allow_auto
        self.auto = allow_auto and default_auto
        self.keys = list(default_keys or [])
        self.setPopupMode(QToolButton.InstantPopup)
        self.setIcon(theme.icon("stats"))
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setCursor(Qt.PointingHandCursor)
        self.menu_ = QMenu(self)
        self.panel = QWidget()
        lay = QVBoxLayout(self.panel)
        lay.setContentsMargins(8, 8, 8, 8)
        grid = QGridLayout()
        grid.setSpacing(6)
        presets = list(PRESETS)
        if allow_auto:
            b = button("Uyarı/alarm verenler (otomatik)", "wand", "primary")
            b.clicked.connect(self.set_auto)
            grid.addWidget(b, 0, 0, 1, 2)
        for i, (label, fn) in enumerate(presets):
            b = button(label)
            b.clicked.connect(lambda _c=False, f=fn: self.set_keys(f(self.state.params)))
            grid.addWidget(b, 1 + i // 2, i % 2)
        bc = button("Temizle", "trash", "ghost")
        bc.clicked.connect(lambda: self.set_keys([]))
        grid.addWidget(bc, 1 + (len(presets) + 1) // 2, 0)
        lay.addLayout(grid)
        lay.addWidget(hint("veya tek tek işaretleyin:"))
        self.list = QListWidget()
        self.list.setMinimumHeight(320)
        self.list.setMinimumWidth(420)
        self.list.itemChanged.connect(self._on_item)
        lay.addWidget(self.list)
        act = QWidgetAction(self.menu_)
        act.setDefaultWidget(self.panel)
        self.menu_.addAction(act)
        self.setMenu(self.menu_)
        self.reload()

    def reload(self):
        self.list.blockSignals(True)
        self.list.clear()
        for p in self.state.params:
            it = QListWidgetItem(self.state.param_label(p.key))
            it.setData(Qt.UserRole, p.key)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if (not self.auto and p.key in self.keys) else Qt.Unchecked)
            self.list.addItem(it)
        self.list.blockSignals(False)
        self._update_text()

    def _on_item(self, _it):
        self.auto = False
        self.keys = [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                     if self.list.item(i).checkState() == Qt.Checked]
        self._update_text()
        self.changed.emit()

    def set_auto(self):
        self.auto = True
        self.keys = []
        self.reload()
        self.menu_.close()
        self.changed.emit()

    def set_keys(self, keys, close=True):
        self.auto = False
        self.keys = list(keys)
        self.reload()
        if close:
            self.menu_.close()
        self.changed.emit()

    def _update_text(self):
        if self.auto:
            txt = "Otomatik (uyarı/alarm verenler)"
        elif not self.keys:
            txt = "Parametre seçilmedi"
        else:
            for label, fn in PRESETS:
                if set(fn(self.state.params)) == set(self.keys):
                    txt = f"{label} ({len(self.keys)})"
                    break
            else:
                names = [self.state.pmap[k].name.split(" (")[0] for k in self.keys if k in self.state.pmap]
                txt = ", ".join(names[:4]) + (f" +{len(names) - 4}" if len(names) > 4 else "")
        self.setText("Parametreler: " + txt + "  ▾")
        self.setMinimumWidth(min(self.sizeHint().width(), 520))
