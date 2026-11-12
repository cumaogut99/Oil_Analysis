"""Kolay raporlama: içerik seçimi, kapsam, kapak bilgileri; PDF / DOCX çıktı."""
from __future__ import annotations

import os
import traceback

from PySide6.QtCore import QDate, QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDateEdit, QFileDialog,
                               QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QVBoxLayout, QWidget)

from ..report import SECTIONS, ReportOptions, build_report
from ..textnorm import format_date
from .common import AppState, FilterBar, button, hint
from .param_picker import ParamPicker

X_OPTIONS = {"Motor çalışma saati": "motor_hours", "Yağ çalışma saati": "oil_hours",
             "Numune tarihi": "date_taken"}


class ReportTab(QWidget):
    title = "Raporlama"
    subtitle = "İçeriği seçin, kapsamı belirleyin; kapak ve içindekiler içeren PDF veya Word raporu alın"
    icon = "export"

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.qs = QSettings("YagAnalizi", "MotorYagiAnaliz")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)

        # ------------------------------------------------ kapsam (tam genişlik)
        c0 = QFrame()
        c0.setObjectName("Card")
        l0 = QVBoxLayout(c0)
        l0.setContentsMargins(16, 14, 16, 14)
        t = QLabel("1. Kapsam")
        t.setObjectName("SectionTitle")
        l0.addWidget(t)
        self.filters = FilterBar(state, with_motor=True)
        self.filters.changed.connect(self._update_info)
        l0.addWidget(self.filters)
        dr = QHBoxLayout()
        self.c_date = QCheckBox("Numune tarihi aralığı:")
        self.c_date.toggled.connect(self._update_info)
        self.d_from = QDateEdit()
        self.d_to = QDateEdit()
        for d in (self.d_from, self.d_to):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd.MM.yyyy")
            d.dateChanged.connect(self._update_info)
        self.d_to.setDate(QDate.currentDate())
        self.d_from.setDate(QDate.currentDate().addMonths(-12))
        dr.addWidget(self.c_date)
        dr.addWidget(self.d_from)
        dr.addWidget(QLabel("–"))
        dr.addWidget(self.d_to)
        dr.addSpacing(20)
        self.info = QLabel()
        self.info.setObjectName("Hint")
        dr.addWidget(self.info, 1)
        l0.addLayout(dr)
        lay.addWidget(c0)

        row = QHBoxLayout()
        row.setSpacing(12)

        # ------------------------------------------------ içerik kartı
        c1 = QFrame()
        c1.setObjectName("Card")
        l1 = QVBoxLayout(c1)
        l1.setContentsMargins(16, 14, 16, 14)
        t = QLabel("2. İçerik")
        t.setObjectName("SectionTitle")
        l1.addWidget(t)
        l1.addWidget(hint("Rapora girecek bölümleri seçin. Her bölüm içindekilerde yer alır."))
        grid = QGridLayout()
        self.sec_checks = {}
        for i, (key, label, default) in enumerate(SECTIONS):
            cb = QCheckBox(label)
            cb.setChecked(default)
            cb.toggled.connect(self._update_info)
            grid.addWidget(cb, i, 0)
            self.sec_checks[key] = cb
        l1.addLayout(grid)
        h = QHBoxLayout()
        ball = button("Tümünü seç", variant="ghost")
        ball.clicked.connect(lambda: [c.setChecked(True) for c in self.sec_checks.values()])
        bnone = button("Temizle", variant="ghost")
        bnone.clicked.connect(lambda: [c.setChecked(False) for c in self.sec_checks.values()])
        h.addWidget(ball)
        h.addWidget(bnone)
        h.addStretch(1)
        l1.addLayout(h)

        f = QFormLayout()
        f.setLabelAlignment(Qt.AlignLeft)
        self.list_mode = QComboBox()
        self.list_mode.addItem("Tüm numuneler", "all")
        self.list_mode.addItem("Yalnız uyarı/alarm verenler", "flagged")
        f.addRow("Numune listesi:", self.list_mode)
        self.trend_picker = ParamPicker(state, allow_auto=True, default_auto=True)
        f.addRow("Trend parametreleri:", self.trend_picker)
        self.xaxis = QComboBox()
        self.xaxis.addItems(list(X_OPTIONS))
        f.addRow("Trend X ekseni:", self.xaxis)
        self.trend_mode = QComboBox()
        self.trend_mode.addItem("Tüm motorlar tek grafikte", False)
        self.trend_mode.addItem("Her motor için ayrı grafik", True)
        f.addRow("Trend düzeni:", self.trend_mode)
        l1.addLayout(f)
        l1.addStretch(1)
        row.addWidget(c1, 1)

        # ----------------------------------------------- kapak
        c2 = QFrame()
        c2.setObjectName("Card")
        l2 = QVBoxLayout(c2)
        l2.setContentsMargins(16, 14, 16, 14)
        t = QLabel("3. Kapak sayfası")
        t.setObjectName("SectionTitle")
        l2.addWidget(t)
        f2 = QFormLayout()
        self.e_title = QLineEdit(self.qs.value("report/title", "Motor Yağı Analiz Raporu"))
        self.e_subtitle = QLineEdit()
        self.e_subtitle.setPlaceholderText("ör. 2026 3. çeyrek — C9 platformu")
        self.e_author = QLineEdit(self.qs.value("report/author", ""))
        self.e_author.setPlaceholderText("ör. Bakım Mühendisliği")
        self.e_desc = QPlainTextEdit()
        self.e_desc.setPlaceholderText("Kapakta ve özette yer alacak açıklama (opsiyonel)")
        self.e_desc.setMaximumHeight(110)
        f2.addRow("Rapor başlığı:", self.e_title)
        f2.addRow("Alt başlık:", self.e_subtitle)
        f2.addRow("Hazırlayan:", self.e_author)
        f2.addRow("Açıklama:", self.e_desc)
        l2.addLayout(f2)
        l2.addStretch(1)
        row.addWidget(c2, 1)
        lay.addLayout(row, 1)

        # ------------------------------------------------------ çıktı
        c3 = QFrame()
        c3.setObjectName("Card")
        l3 = QHBoxLayout(c3)
        l3.setContentsMargins(16, 12, 16, 12)
        t = QLabel("4. Dışa aktar")
        t.setObjectName("SectionTitle")
        l3.addWidget(t)
        l3.addSpacing(12)
        self.c_open = QCheckBox("Kaydettikten sonra aç")
        self.c_open.setChecked(True)
        l3.addWidget(self.c_open)
        l3.addStretch(1)
        b_docx = button("Word (DOCX) olarak kaydet", "samples")
        b_docx.clicked.connect(lambda: self.export("docx"))
        b_pdf = button("PDF olarak kaydet", "pdf", "primary")
        b_pdf.clicked.connect(lambda: self.export("pdf"))
        l3.addWidget(b_docx)
        l3.addWidget(b_pdf)
        lay.addWidget(c3)
        state.changed.connect(self.on_state_changed)
        self._update_info()

    def on_state_changed(self):
        self.filters.refresh_options()
        self.trend_picker.reload()
        self._update_info()

    # --------------------------------------------------------------- kapsam
    def scope(self):
        rows = [s for s in self.filters.apply(self.state.samples) if not s.is_fresh]
        if self.c_date.isChecked():
            a = self.d_from.date().toString("yyyy-MM-dd")
            b = self.d_to.date().toString("yyyy-MM-dd")
            rows = [s for s in rows if s.date_taken and a <= s.date_taken <= b]
        return rows

    def scope_desc(self):
        d = self.filters.description()
        if self.c_date.isChecked():
            d += (f"; tarih {format_date(self.d_from.date().toString('yyyy-MM-dd'))} – "
                  f"{format_date(self.d_to.date().toString('yyyy-MM-dd'))}")
        return d

    def _update_info(self, *_):
        if not hasattr(self, "info"):  # kurulum sırasında gelen sinyaller
            return
        rows = self.scope()
        ev = self.state.evaluator
        n_flag = sum(1 for s in rows if (ev.overall(s)[0] or 0) >= 1)
        motors = len({s.motor_no for s in rows if s.motor_no})
        n_sec = sum(1 for c in self.sec_checks.values() if c.isChecked())
        self.info.setText(f"Kapsamda <b>{len(rows)}</b> numune, <b>{motors}</b> motor; "
                          f"<b>{n_flag}</b> numunede uyarı/alarm. Seçili bölüm: <b>{n_sec}</b>.")

    # ---------------------------------------------------------------- çıktı
    def options(self) -> ReportOptions:
        return ReportOptions(
            title=self.e_title.text().strip() or "Motor Yağı Analiz Raporu",
            subtitle=self.e_subtitle.text().strip(),
            author=self.e_author.text().strip(),
            description=self.e_desc.toPlainText().strip(),
            sections=[k for k, c in self.sec_checks.items() if c.isChecked()],
            scope_desc=self.scope_desc(),
            sample_list_mode=self.list_mode.currentData(),
            trend_keys=None if self.trend_picker.auto else list(self.trend_picker.keys),
            trend_xkey=X_OPTIONS[self.xaxis.currentText()],
            trend_per_motor=bool(self.trend_mode.currentData()),
        )

    def export(self, fmt: str):
        opts = self.options()
        if not opts.sections:
            QMessageBox.warning(self, "Rapor", "En az bir bölüm seçin.")
            return
        rows = self.scope()
        if not rows:
            QMessageBox.warning(self, "Rapor", "Kapsamda numune yok. Filtreleri kontrol edin.")
            return
        ext = {"pdf": "PDF (*.pdf)", "docx": "Word (*.docx)"}[fmt]
        start_dir = self.qs.value("report/dir", "")
        name = opts.title.replace("/", "-") + "." + fmt
        path, _ = QFileDialog.getSaveFileName(self, "Raporu kaydet", os.path.join(start_dir, name), ext)
        if not path:
            return
        if not path.lower().endswith("." + fmt):
            path += "." + fmt
        self.qs.setValue("report/dir", os.path.dirname(path))
        self.qs.setValue("report/title", opts.title)
        self.qs.setValue("report/author", opts.author)
        st = self.state
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            rep = build_report(rows, st.params, st.settings, st.evaluator, st.db.part_sources(), opts)
            if fmt == "pdf":
                from ..report.pdf_writer import write_pdf
                write_pdf(rep, path)
            else:
                from ..report.docx_writer import write_docx
                write_docx(rep, path)
        except PermissionError:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Rapor", "Dosya yazılamadı. Dosya başka bir programda açık olabilir.")
            return
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Rapor", f"Rapor oluşturulamadı: {exc}\n\n{traceback.format_exc(limit=4)}")
            return
        QApplication.restoreOverrideCursor()
        if self.c_open.isChecked():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.information(self, "Rapor", f"Rapor kaydedildi:\n{path}")
