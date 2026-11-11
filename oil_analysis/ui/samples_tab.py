"""Numune listesi ve numune detay/değerlendirme penceresi."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from ..db import PLATFORM_GROUPS, SAMPLE_TYPES, Sample
from ..evaluation import STATUS_TEXT
from ..textnorm import fmt_num, format_date
from .common import STATUS_BG, AppState, FilterBar, ro_item

COLUMNS = ["Durum", "Analiz No", "Motor", "Platform", "Grup", "Numune Tipi", "Yağ",
           "Numune Tarihi", "Motor sa", "Yağ sa", "SGS Teşhisi", "Dikkat Gerektirenler",
           "Değerlendirme Yorumu"]


class SamplesTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        lay = QVBoxLayout(self)
        self.filters = FilterBar(state, with_motor=True, with_fresh=True)
        self.filters.changed.connect(self.refresh)
        top = QHBoxLayout()
        top.addWidget(self.filters, 1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Ara (analiz no, motor, yorum)…")
        self.search.textChanged.connect(self.refresh)
        top.addWidget(self.search)
        lay.addLayout(top)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self.open_selected)
        lay.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.info = QLabel()
        bottom.addWidget(self.info, 1)
        b_open = QPushButton("Detay / Değerlendir")
        b_open.clicked.connect(self.open_selected)
        b_del = QPushButton("Sil")
        b_del.clicked.connect(self.delete_selected)
        bottom.addWidget(b_open)
        bottom.addWidget(b_del)
        lay.addLayout(bottom)
        state.changed.connect(self.on_state_changed)
        self.refresh()

    def on_state_changed(self):
        self.filters.refresh_options()
        self.refresh()

    def refresh(self):
        st = self.state
        q = self.search.text().strip().lower()
        rows = self.filters.apply(st.samples)
        if q:
            rows = [s for s in rows if q in " ".join(
                str(x or "") for x in (s.sample_no, s.motor_no, s.user_comment, s.lab_comment,
                                        s.platform_code)).lower()]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        counts = {0: 0, 1: 0, 2: 0}
        for i, s in enumerate(reversed(rows)):
            status, flagged = st.evaluator.overall(s)
            if status in counts:
                counts[status] += 1
            vals = [
                ro_item("Sıfır Yağ" if s.is_fresh else STATUS_TEXT[status],
                        -1 if status is None else status, status),
                ro_item(s.sample_no),
                ro_item(s.motor_no or ""),
                ro_item(s.platform_code or ""),
                ro_item(s.platform_group if s.platform_code else ""),
                ro_item(s.sample_type),
                ro_item(s.oil_type or ""),
                ro_item(format_date(s.date_taken), s.date_taken or ""),
                ro_item(fmt_num(s.motor_hours), s.motor_hours),
                ro_item(fmt_num(s.oil_hours), s.oil_hours),
                ro_item(s.lab_diagnosis or s.lab_diag_letter or "",
                        tooltip=("SGS (analiz firması) teşhisi:\n" + (s.lab_comment or ""))
                        if (s.lab_comment or s.lab_diagnosis) else None),
                ro_item(", ".join(flagged), len(flagged), tooltip="\n".join(flagged) or None),
                ro_item((s.user_comment or "").replace("\n", " ")),
            ]
            for c, it in enumerate(vals):
                if c == 0:
                    it.setData(Qt.UserRole, s.id)
                self.table.setItem(i, c, it)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(11, min(self.table.columnWidth(11), 320))
        self.info.setText(f"{len(rows)} numune  •  Normal: {counts[0]}  •  Uyarı: {counts[1]}"
                          f"  •  Alarm: {counts[2]}")

    def _selected_ids(self):
        ids = []
        for idx in self.table.selectionModel().selectedRows():
            it = self.table.item(idx.row(), 0)
            if it is not None:
                ids.append(it.data(Qt.UserRole))
        return ids

    def open_selected(self, *_):
        ids = self._selected_ids()
        if not ids:
            return
        s = next((x for x in self.state.samples if x.id == ids[0]), None)
        if s is not None:
            SampleDialog(self.state, s, self).exec()

    def delete_selected(self):
        ids = self._selected_ids()
        if not ids:
            return
        if QMessageBox.question(self, "Sil", f"{len(ids)} numune silinsin mi?") != QMessageBox.Yes:
            return
        for sid in ids:
            self.state.db.delete_sample(sid)
        self.state.reload()


class SampleDialog(QDialog):
    """Numune bilgileri, ölçümler, limitler, SGS yorumu ve kullanıcı değerlendirmesi."""

    def __init__(self, state: AppState, s: Sample, parent=None):
        super().__init__(parent)
        self.state, self.s = state, s
        self.setWindowTitle(f"Numune {s.sample_no}")
        self.resize(1250, 800)
        lay = QVBoxLayout(self)
        split = QSplitter(Qt.Horizontal)
        lay.addWidget(split, 1)

        # ----- sol: bilgiler ve yorumlar
        left = QWidget()
        ll = QVBoxLayout(left)
        g = QGroupBox("Numune Bilgileri")
        form = QFormLayout(g)
        self.e_motor = QLineEdit(s.motor_no or "")
        self.e_platform = QComboBox()
        self.e_platform.setEditable(True)
        self.e_platform.addItems([""] + sorted(state.platforms))
        self.e_platform.setCurrentText(s.platform_code or "")
        self.e_type = QComboBox()
        self.e_type.addItems(SAMPLE_TYPES)
        self.e_type.setCurrentText(s.sample_type)
        self.e_oil = QComboBox()
        self.e_oil.setEditable(True)
        self.e_oil.addItems([""] + state.oil_types())
        self.e_oil.setCurrentText(s.oil_type or "")
        self.e_date = QLineEdit(format_date(s.date_taken))
        self.e_mh = QLineEdit(fmt_num(s.motor_hours))
        self.e_oh = QLineEdit(fmt_num(s.oil_hours))
        form.addRow("Analiz No:", QLabel(f"<b>{s.sample_no}</b>  ({s.origin or ''})"))
        form.addRow("Motor No:", self.e_motor)
        form.addRow("Platform:", self.e_platform)
        grp = state.platforms.get(s.platform_code or "", "") if s.platform_code else ""
        form.addRow("Platform grubu:", QLabel(grp or "— (Ayarlar > Platformlar)"))
        form.addRow("Numune tipi:", self.e_type)
        form.addRow("Yağ tipi:", self.e_oil)
        form.addRow("Numune tarihi:", self.e_date)
        form.addRow("Motor çalışma (sa):", self.e_mh)
        form.addRow("Yağ çalışma (sa):", self.e_oh)
        if s.lubricant:
            form.addRow("Yağ:", QLabel(s.lubricant))
        ll.addWidget(g)

        sg = QGroupBox("SGS (Analiz Firması) Değerlendirmesi — bilgi amaçlı")
        sl = QVBoxLayout(sg)
        diag = s.lab_diagnosis or "-"
        if s.lab_diag_letter:
            diag += f"  (SGS kodu: {s.lab_diag_letter})"
        sl.addWidget(QLabel(f"SGS teşhisi: <b>{diag}</b>"))
        lab = QTextEdit(s.lab_comment or "")
        lab.setReadOnly(True)
        lab.setMaximumHeight(110)
        sl.addWidget(lab)
        if s.lab_info:
            sl.addWidget(QLabel("; ".join(f"{k}: {v}" for k, v in s.lab_info.items())))
        ll.addWidget(sg)

        ug = QGroupBox("Değerlendirme Yorumu (kullanıcı)")
        ul = QVBoxLayout(ug)
        self.e_comment = QTextEdit(s.user_comment or "")
        ul.addWidget(self.e_comment)
        ll.addWidget(ug, 1)
        split.addWidget(left)

        # ----- sağ: ölçümler
        right = QWidget()
        rl = QVBoxLayout(right)
        pop, desc = state.evaluator.ref_population(s)
        status, _ = state.evaluator.overall(s)
        rl.addWidget(QLabel(f"Genel durum: <b>{STATUS_TEXT[status]}</b>   •   Referans grubu: {desc}"
                            f"   •   Hız birimi: ppm / 100 sa yağ çalışması"))
        heads = ["Parametre", "Değer", "Durum", "Uyarı limiti", "Alarm limiti", "Sıfır yağ",
                 "Değişim %", "Artış hızı", "Hız uyarı/alarm", "Açıklama"]
        self.table = QTableWidget(0, len(heads))
        self.table.setHorizontalHeaderLabels(heads)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        rl.addWidget(self.table, 1)
        rl.addWidget(QLabel("Not: 'Değer' sütunu düzenlenebilir (okuma hatası düzeltmek için). "
                            "Boş bırakılan değer silinir."))
        split.addWidget(right)
        split.setSizes([380, 870])
        self._fill_values()

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Save).setText("Kaydet")
        bb.button(QDialogButtonBox.Close).setText("Kapat")
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _fill_values(self):
        st, s = self.state, self.s
        ev = st.evaluator.evaluate(s)
        keys = [p.key for p in st.params if p.key in s.values or p.key in s.raws]
        self.table.setRowCount(len(keys))
        self._row_keys = keys
        for i, key in enumerate(keys):
            e = ev.get(key)
            raw = s.raws.get(key)
            v = s.values.get(key)
            name = ro_item(st.param_label(key))
            val = QTableWidgetItem(fmt_num(v, 3) if v is not None else (raw or ""))
            stt = e.status if e else None
            lim = e.limits if e else None
            rl = e.rate_limits if e else None

            def lim_txt(lo, hi):
                parts = []
                if lo is not None:
                    parts.append(f"< {fmt_num(lo)}")
                if hi is not None:
                    parts.append(f"> {fmt_num(hi)}")
                return "  ".join(parts)

            items = [
                name, val,
                ro_item(STATUS_TEXT.get(stt, "—"), status=stt),
                ro_item(lim_txt(lim.lo_warn, lim.hi_warn) if lim else "",
                        tooltip=lim.note if lim else None),
                ro_item(lim_txt(lim.lo_alarm, lim.hi_alarm) if lim else "",
                        tooltip=lim.note if lim else None),
                ro_item(fmt_num(e.fresh) if e else ""),
                ro_item(f"{e.change_pct:+.0f}" if e and e.change_pct is not None else ""),
                ro_item(fmt_num(e.rate) if e and e.rate is not None else ""),
                ro_item(f"{fmt_num(rl.hi_warn)} / {fmt_num(rl.hi_alarm)}" if rl and rl.valid else "",
                        tooltip=rl.note if rl else None),
                ro_item("; ".join(e.reasons) if e else "",
                        tooltip="\n".join(e.reasons) if e and e.reasons else None),
            ]
            if stt in STATUS_BG:
                val.setBackground(STATUS_BG[stt])
            for c, it in enumerate(items):
                self.table.setItem(i, c, it)
        self.table.resizeColumnsToContents()

    def save(self):
        values = {}
        for i, key in enumerate(self._row_keys):
            new = self.table.item(i, 1).text().strip()
            old = self.s.values.get(key)
            old_txt = fmt_num(old, 3) if old is not None else (self.s.raws.get(key) or "")
            if new != old_txt:
                values[key] = new
        meta = {
            "platform_code": self.e_platform.currentText(),
            "sample_type": self.e_type.currentText(),
            "oil_type": self.e_oil.currentText(),
            "date_taken": self.e_date.text(),
            "motor_hours": self.e_mh.text(),
            "oil_hours": self.e_oh.text(),
            "user_comment": self.e_comment.toPlainText().strip() or None,
        }
        self.state.db.update_sample(self.s.id, self.e_motor.text(), meta, values)
        self.state.reload()
        self.accept()


__all__ = ["SamplesTab", "SampleDialog", "PLATFORM_GROUPS"]
