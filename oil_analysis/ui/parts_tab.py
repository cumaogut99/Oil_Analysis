"""Malzeme Kaynakları: yağda görülen malzemenin motorda hangi parçalardan gelebileceği."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMessageBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ..parameters import CONTAMINANT, FTIR, WEAR
from ..parts import DEFAULT_SOURCES
from ..textnorm import normalize_label
from . import theme
from .common import AppState, button, hint, style_table

PRIMARY_CATEGORIES = (WEAR, CONTAMINANT)


class PartsTab(QWidget):
    title = "Malzeme Kaynakları"
    subtitle = "Yağdaki her malzemenin motorda hangi parçalardan gelebileceğini tanımlayın"
    icon = "parts"

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.current = None
        self.dirty = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)
        lay.addWidget(hint(
            "Soldan bir malzeme seçin, sağ tarafa olası kaynak parçaları yazın. Numune detayındaki "
            "'Parça Tahmini' sekmesi, miktarı değişen veya uyarı/alarm veren malzemeler için bu listeyi "
            "kullanır. Aynı parçayı birden fazla malzemeye aynı adla yazarsanız (ör. 'Segmanlar' hem Fe "
            "hem Cr'de), o parça tahminde üst sıraya çıkar."))
        split = QSplitter(Qt.Horizontal)
        lay.addWidget(split, 1)

        left = QFrame()
        left.setObjectName("Card")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 12, 12)
        t = QLabel("Malzemeler")
        t.setObjectName("SectionTitle")
        ll.addWidget(t)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_select)
        ll.addWidget(self.list, 1)
        split.addWidget(left)

        right = QFrame()
        right.setObjectName("Card")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 12, 12, 12)
        self.r_title = QLabel("")
        self.r_title.setObjectName("SectionTitle")
        rl.addWidget(self.r_title)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Olası kaynak parça", "Açıklama / not"])
        style_table(self.table)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 300)
        self.table.itemChanged.connect(self._mark_dirty)
        rl.addWidget(self.table, 1)
        row = QHBoxLayout()
        b_add = button("Parça ekle", "plus")
        b_add.clicked.connect(self.add_row)
        b_del = button("Seçili satırı sil", "trash", "danger")
        b_del.clicked.connect(self.del_row)
        b_up = button("Yukarı", "chevron-up", "ghost")
        b_up.clicked.connect(lambda: self.move(-1))
        b_down = button("Aşağı", "chevron-down", "ghost")
        b_down.clicked.connect(lambda: self.move(1))
        b_lit = button("Genel literatür önerilerini ekle", "wand",
                       tooltip="Pistonlu motorlar için genel kaynak önerilerini bu malzemeye ekler "
                               "(mevcut satırlar korunur). Motorunuza göre düzenleyin.")
        b_lit.clicked.connect(self.add_defaults)
        self.b_save = button("Kaydet", "save", "primary")
        self.b_save.clicked.connect(self.save)
        for b in (b_add, b_del, b_up, b_down):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(b_lit)
        row.addWidget(self.b_save)
        rl.addLayout(row)
        split.addWidget(right)
        split.setSizes([300, 900])
        state.changed.connect(self.reload_list)
        self.reload_list()

    def _keys(self):
        """Önce aşınma/kirletici elementler, sonra diğerleri."""
        ps = self.state.params
        first = [p for p in ps if p.category in PRIMARY_CATEGORIES]
        second = [p for p in ps if p.category == FTIR]
        rest = [p for p in ps if p not in first and p not in second]
        return first + second + rest

    def reload_list(self):
        if self.dirty:
            return
        sources = self.state.db.part_sources()
        cur = self.current
        self.list.blockSignals(True)
        self.list.clear()
        sel = None
        for p in self._keys():
            n = len(sources.get(p.key, []))
            it = QListWidgetItem(f"{p.name}" + (f"   ·  {n}" if n else ""))
            it.setData(Qt.UserRole, p.key)
            it.setIcon(theme.icon("parts", theme.token("primary") if n else None, 16))
            it.setToolTip(", ".join(s["part"] for s in sources.get(p.key, [])) or "Tanımlı kaynak yok")
            self.list.addItem(it)
            if p.key == cur:
                sel = it
        self.list.blockSignals(False)
        self.list.setCurrentItem(sel or self.list.item(0))

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        r = QMessageBox.question(self, "Kaydedilmemiş değişiklik",
                                 "Bu malzemedeki değişiklikler kaydedilsin mi?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            self.save(reload=False)
            return True
        if r == QMessageBox.Discard:
            self.dirty = False
            return True
        return False

    def _on_select(self, item, prev):
        if item is None:
            return
        key = item.data(Qt.UserRole)
        if key == self.current:
            return
        if not self._confirm_discard():
            self.list.blockSignals(True)
            self.list.setCurrentItem(prev)
            self.list.blockSignals(False)
            return
        self.current = key
        self.r_title.setText(f"{self.state.param_label(key)} — olası kaynak parçalar")
        self._fill(self.state.db.part_sources().get(key, []))

    def _fill(self, rows):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for r in rows:
            self._append(r.get("part", ""), r.get("note", ""))
        self.table.blockSignals(False)
        self.dirty = False

    def _append(self, part, note):
        i = self.table.rowCount()
        self.table.insertRow(i)
        self.table.setItem(i, 0, QTableWidgetItem(part))
        self.table.setItem(i, 1, QTableWidgetItem(note))

    def _mark_dirty(self, *_):
        self.dirty = True

    def _rows(self):
        out = []
        for i in range(self.table.rowCount()):
            a, b = self.table.item(i, 0), self.table.item(i, 1)
            out.append({"part": a.text() if a else "", "note": b.text() if b else ""})
        return out

    def add_row(self):
        self._append("", "")
        self.table.setCurrentCell(self.table.rowCount() - 1, 0)
        self.table.editItem(self.table.item(self.table.rowCount() - 1, 0))
        self.dirty = True

    def del_row(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)
            self.dirty = True

    def move(self, d):
        r = self.table.currentRow()
        rows = self._rows()
        t = r + d
        if r < 0 or not 0 <= t < len(rows):
            return
        rows[r], rows[t] = rows[t], rows[r]
        self._fill(rows)
        self.dirty = True
        self.table.setCurrentCell(t, 0)

    def add_defaults(self):
        if self.current is None:
            return
        defaults = DEFAULT_SOURCES.get(self.current, [])
        if not defaults:
            QMessageBox.information(self, "Literatür", "Bu malzeme için hazır öneri yok.")
            return
        rows = self._rows()
        have = {normalize_label(r["part"]) for r in rows}
        added = 0
        for part, note in defaults:
            if normalize_label(part) not in have:
                rows.append({"part": part, "note": note})
                added += 1
        self._fill(rows)
        self.dirty = added > 0

    def save(self, reload=True):
        if self.current is None:
            return
        self.state.db.save_part_sources(self.current, self._rows())
        self.dirty = False
        if reload:
            self.reload_list()
