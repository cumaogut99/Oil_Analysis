"""PDF ve Excel içe aktarma önizleme / onay pencereleri."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..db import SAMPLE_TYPES, UNSPECIFIED
from ..excel_importer import SheetResult, default_type_for_sheet
from ..importer import apply_mappings, save_excel, save_report
from ..parameters import META_FIELDS
from ..pdf_parser import ParsedReport
from ..textnorm import parse_number
from .common import AppState

IGNORE = "— Yoksay —"
NEW_PARAM = "+ Yeni parametre oluştur…"


class UnmatchedWidget(QGroupBox):
    """Tanınmayan satırları kullanıcıya eşleştirtir; isterse hatırlar."""

    def __init__(self, state: AppState, unmatched, parent=None):
        super().__init__("Tanınmayan satırlar — eşleştirin (bir kez eşleştirilen etiket hatırlanır)", parent)
        self.state = state
        self.unmatched = unmatched
        lay = QVBoxLayout(self)
        self.table = QTableWidget(len(unmatched), 4)
        self.table.setHorizontalHeaderLabels(["Rapordaki etiket", "Örnek değerler", "Eşleştir", "Hatırla"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.combos, self.remember = [], []
        for i, u in enumerate(unmatched):
            self.table.setItem(i, 0, QTableWidgetItem(u.label))
            self.table.setItem(i, 1, QTableWidgetItem(", ".join(list(u.values.values())[:6])))
            cb = QComboBox()
            cb.addItem(IGNORE, "ignore")
            cb.addItem(NEW_PARAM, "new")
            for p in state.params:
                cb.addItem(f"Parametre: {state.param_label(p.key)}", f"param:{p.key}")
            for k, v in META_FIELDS.items():
                if k not in ("sample_no",):
                    cb.addItem(f"Bilgi alanı: {v}", f"meta:{k}")
            cb.currentIndexChanged.connect(lambda _i, c=cb, lab=u.label: self._on_change(c, lab))
            self.table.setCellWidget(i, 2, cb)
            chk = QCheckBox()
            chk.setChecked(True)
            self.table.setCellWidget(i, 3, chk)
            self.combos.append(cb)
            self.remember.append(chk)
        self.table.resizeColumnsToContents()
        lay.addWidget(self.table)
        self.setVisible(bool(unmatched))

    def _on_change(self, cb: QComboBox, label: str):
        if cb.currentData() != "new":
            return
        name, ok = QInputDialog.getText(self, "Yeni parametre", "Parametre adı:", text=label)
        if not ok or not name.strip():
            cb.setCurrentIndex(0)
            return
        unit, _ = QInputDialog.getText(self, "Yeni parametre", "Birim (opsiyonel):")
        key = self.state.db.add_parameter(name.strip(), unit.strip())
        for other in self.combos:
            other.addItem(f"Parametre: {name.strip()}", f"param:{key}")
        cb.setCurrentIndex(cb.count() - 1)

    def mapping(self) -> dict[str, str]:
        out = {}
        for u, cb, chk in zip(self.unmatched, self.combos, self.remember):
            tgt = cb.currentData()
            if tgt == "new":
                tgt = "ignore"
            out[u.norm] = tgt
            if chk.isChecked():
                self.state.db.set_alias(u.label, tgt)
        return out


class PdfImportDialog(QDialog):
    def __init__(self, state: AppState, report: ParsedReport, parent=None):
        super().__init__(parent)
        self.state, self.report = state, report
        self.result_counts = None
        self.setWindowTitle(f"PDF Rapor İçe Aktar — {Path(report.file).name}")
        self.resize(1200, 820)
        lay = QVBoxLayout(self)
        h = report.header
        main = report.main_sample_no

        top = QHBoxLayout()
        g = QGroupBox("Ana numune")
        form = QFormLayout(g)
        form.addRow("Analiz No:", QLabel(f"<b>{main}</b>" + (" (OCR)" if report.used_ocr else "")))
        self.e_motor = QLineEdit(h.get("motor_no", ""))
        self.e_motor.editingFinished.connect(self._motor_changed)
        form.addRow("Motor No:", self.e_motor)
        self.e_platform = QComboBox()
        self.e_platform.setEditable(True)
        self.e_platform.addItems([""] + sorted(state.platforms))
        form.addRow("Platform (opsiyonel):", self.e_platform)
        self.e_type = QComboBox()
        self.e_type.addItems(SAMPLE_TYPES)
        form.addRow("Numune tipi:", self.e_type)
        self.e_oil = QComboBox()
        self.e_oil.setEditable(True)
        self.e_oil.addItems([""] + state.oil_types())
        form.addRow("Yağ tipi:", self.e_oil)
        form.addRow("Yağ (rapordan):", QLabel(h.get("lubricant", "-")))
        top.addWidget(g, 1)

        sg = QGroupBox("SGS (analiz firması) teşhisi ve yorumu")
        sl = QVBoxLayout(sg)
        sl.addWidget(QLabel(f"Teşhis: <b>{h.get('lab_diagnosis', '-')}</b>  {h.get('lab_diagnosis_date', '')}"))
        t = QPlainTextEdit(h.get("lab_comment", ""))
        t.setReadOnly(True)
        t.setMaximumHeight(90)
        sl.addWidget(t)
        sl.addWidget(QLabel("Kendi değerlendirmeniz (opsiyonel):"))
        self.e_comment = QPlainTextEdit()
        self.e_comment.setMaximumHeight(70)
        sl.addWidget(self.e_comment)
        top.addWidget(sg, 2)
        lay.addLayout(top)
        self._motor_changed()

        # ----- değer tablosu
        snos = list(report.samples)
        keys = []
        for s in report.samples.values():
            for k in s.values:
                if k not in keys:
                    keys.append(k)
        order = {p.key: i for i, p in enumerate(state.params)}
        keys.sort(key=lambda k: order.get(k, 999))
        meta_keys = ["date_taken", "motor_hours", "oil_hours", "lab_diag_letter"]
        self.table = QTableWidget(len(meta_keys) + len(keys), len(snos))
        heads = []
        for sno in snos:
            tag = " ★" if sno == main else ""
            if state.db.sample_exists(sno):
                tag += " (kayıtlı)"
            heads.append(sno + tag)
        self.table.setHorizontalHeaderLabels(heads)
        self.table.setVerticalHeaderLabels([META_FIELDS[k] for k in meta_keys]
                                           + [state.param_label(k) for k in keys])
        for c, sno in enumerate(snos):
            s = report.samples[sno]
            for r, k in enumerate(meta_keys):
                it = QTableWidgetItem(str(s.meta.get(k, "")))
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                it.setBackground(QColor("#eef3fb"))
                self.table.setItem(r, c, it)
            for r, k in enumerate(keys, start=len(meta_keys)):
                raw = s.values.get(k, "")
                it = QTableWidgetItem(raw)
                if raw and parse_number(raw) is None:
                    it.setForeground(QColor("#9e9e9e"))
                if sno == main:
                    it.setBackground(QColor("#fffbe6"))
                self.table.setItem(r, c, it)
        self._keys, self._snos, self._meta_n = keys, snos, len(meta_keys)
        self.table.resizeColumnsToContents()
        lay.addWidget(QLabel("Okunan değerler (★ ana numune; hücreler düzenlenebilir — okuma hatası "
                             "varsa düzeltin):"))
        self.table.setMinimumHeight(320)
        lay.addWidget(self.table, 1)

        self.unmatched = UnmatchedWidget(state, report.unmatched)
        self.unmatched.setMaximumHeight(190)
        lay.addWidget(self.unmatched)

        if report.warnings:
            w = QLabel("⚠ " + "\n⚠ ".join(report.warnings))
            w.setStyleSheet("color:#8a5300")
            w.setWordWrap(True)
            lay.addWidget(w)

        opts = QHBoxLayout()
        self.c_hist = QCheckBox("Rapordaki geçmiş numunelerden veritabanında olmayanları da ekle")
        self.c_hist.setChecked(True)
        self.c_over = QCheckBox("Ana numune kayıtlıysa üzerine yaz")
        opts.addWidget(self.c_hist)
        opts.addWidget(self.c_over)
        opts.addStretch(1)
        lay.addLayout(opts)

        bb = QDialogButtonBox()
        bb.addButton("Kaydet", QDialogButtonBox.AcceptRole)
        bb.addButton("Bu dosyayı atla", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _motor_changed(self):
        info = self.state.db.last_info_for_motor(self.e_motor.text())
        if info.get("platform_code") and not self.e_platform.currentText():
            self.e_platform.setCurrentText(info["platform_code"])
        if not self.e_oil.currentText():
            import re
            m = re.search(r"\b(\d{1,2}W-?\d{2})\b", self.report.header.get("lubricant", ""), re.I)
            oil = (m.group(1).replace("-", "").upper() if m else None) or info.get("oil_type")
            if oil:
                self.e_oil.setCurrentText(oil)

    def save(self):
        motor = self.e_motor.text().strip()
        if not motor:
            QMessageBox.warning(self, "Eksik bilgi", "Motor numarası girilmelidir.")
            return
        if not self.e_oil.currentText().strip():
            if QMessageBox.question(self, "Yağ tipi", "Yağ tipi boş. Yine de kaydedilsin mi? "
                                    "(Yağ tipine göre limitler uygulanamaz)") != QMessageBox.Yes:
                return
        # tablo düzenlemelerini geri yaz
        for c, sno in enumerate(self._snos):
            s = self.report.samples[sno]
            for r, k in enumerate(self._keys, start=self._meta_n):
                it = self.table.item(r, c)
                txt = it.text().strip() if it else ""
                if txt:
                    s.values[k] = txt
                else:
                    s.values.pop(k, None)
        mapping = self.unmatched.mapping()
        apply_mappings(list(self.report.samples.values()), self.report.unmatched, mapping)
        self.result_counts = save_report(
            self.state.db, self.report, motor_no=motor,
            platform_code=self.e_platform.currentText().strip() or None,
            sample_type=self.e_type.currentText(), oil_type=self.e_oil.currentText().strip() or None,
            include_history=self.c_hist.isChecked(), overwrite_main=self.c_over.isChecked(),
            user_comment=self.e_comment.toPlainText().strip() or None)
        self.accept()


class ExcelImportDialog(QDialog):
    def __init__(self, state: AppState, path: str, sheets: list[SheetResult], parent=None):
        super().__init__(parent)
        self.state, self.path, self.sheets = state, path, sheets
        self.result_counts = None
        self.setWindowTitle(f"Excel İçe Aktar — {Path(path).name}")
        self.resize(900, 650)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Her sayfa için varsayılan numune tipini seçin (Excel'de 'Numune Tipi' "
                             "satırı varsa o kullanılır; 'SIFIR YAĞ' sütunları otomatik tanınır)."))
        self.table = QTableWidget(len(sheets), 4)
        self.table.setHorizontalHeaderLabels(["Sayfa", "Analiz sayısı", "Varsayılan numune tipi", "Uyarılar"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.type_combos = {}
        for i, sh in enumerate(sheets):
            self.table.setItem(i, 0, QTableWidgetItem(sh.name))
            self.table.setItem(i, 1, QTableWidgetItem(str(len(sh.samples))))
            cb = QComboBox()
            cb.addItems(SAMPLE_TYPES)
            cb.setCurrentText(default_type_for_sheet(sh.name))
            self.table.setCellWidget(i, 2, cb)
            self.type_combos[sh.name] = cb
            self.table.setItem(i, 3, QTableWidgetItem("; ".join(sh.warnings)))
        self.table.resizeColumnsToContents()
        lay.addWidget(self.table)

        all_unmatched, seen = [], set()
        for sh in sheets:
            for u in sh.unmatched:
                if u.norm not in seen:
                    seen.add(u.norm)
                    all_unmatched.append(u)
        self.unmatched = UnmatchedWidget(state, all_unmatched)
        lay.addWidget(self.unmatched, 1)

        total = sum(len(sh.samples) for sh in sheets)
        existing = sum(1 for sh in sheets for s in sh.samples if state.db.sample_exists(s.sample_no))
        lay.addWidget(QLabel(f"Toplam {total} analiz; {existing} tanesi veritabanında zaten kayıtlı."))
        self.c_over = QCheckBox("Kayıtlı analizlerin üzerine yaz")
        lay.addWidget(self.c_over)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("İçe aktar")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def save(self):
        mapping = self.unmatched.mapping()
        for sh in self.sheets:
            apply_mappings(sh.samples, sh.unmatched, mapping)
        types = {name: cb.currentText() or UNSPECIFIED for name, cb in self.type_combos.items()}
        self.result_counts = save_excel(self.state.db, self.sheets, types,
                                        overwrite=self.c_over.isChecked(),
                                        source_file=Path(self.path).name)
        self.accept()


__all__ = ["PdfImportDialog", "ExcelImportDialog", "QWidget"]
