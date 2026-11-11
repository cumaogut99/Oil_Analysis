"""Ana pencere."""
from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QMainWindow, QMessageBox,
                               QTabWidget, QTextBrowser, QVBoxLayout)

from ..db import Database
from ..excel_importer import read_workbook
from ..export import export_workbook
from ..parameters import LabelMatcher
from ..pdf_parser import ParseError, parse_pdf
from .common import AppState
from .corr_tab import CorrelationTab
from .import_dialogs import ExcelImportDialog, PdfImportDialog
from .samples_tab import SamplesTab
from .settings_dialog import SettingsDialog
from .stats_tab import StatsTab
from .trend_tab import TrendTab

APP_NAME = "Motor Yağı Analiz"

METHODS_HTML = """
<h2>Değerlendirme yöntemleri</h2>
<p>Her ölçüm aşağıdaki kurallarla değerlendirilir; <b>en kötü sonuç</b> geçerlidir
(Normal / Uyarı / Alarm). SGS teşhisi yalnızca bilgi amaçlı gösterilir, değerlendirmeye katılmaz.</p>
<ol>
<li><b>Sabit limitler</b> — Ayarlar &gt; Sabit Limitler. Kesin limiti bilinen parametreler için
(ör. glikol &gt; 0 uyarı).</li>
<li><b>Viskozite sınıf aralığı</b> — 100°C viskozite yağ sınıfı aralığı dışında ise alarm
(0W40: 12.5–16.3, 5W30: 9.3–12.5 cSt; SAE J300).</li>
<li><b>Taze (sıfır) yağa göre değişim</b> — Aynı yağ tipindeki en güncel "Sıfır Yağ" numunesine göre:
  <ul><li>Katkı elementleri (Ca, P, Zn, Mg, B, Mo, Ba): %25 düşüş uyarı, %40 alarm</li>
  <li>Viskozite 40/100°C: ±%10 uyarı, ±%20 alarm (yaygın endüstri pratiği)</li>
  <li>TBN: taze değerin %60'ı altı uyarı, %50'si altı alarm; TBN ≤ TAN alarm</li></ul></li>
<li><b>İstatistiksel limitler</b> (ASTM D7720 yaklaşımı) — Referans popülasyonu (varsayılan: aynı yağ
tipi + aynı numune tipi; yetersizse kriterler gevşetilir) üzerinden:
  <ul><li><i>Normal</i>: uyarı μ+2σ, alarm μ+3σ (düşük-kötü parametrelerde μ−kσ)</li>
  <li><i>Log-normal</i>: sağa çarpık aşınma verileri için log(1+x) uzayında μ+kσ</li>
  <li><i>Yüzdelik</i>: dağılım varsayımı olmadan P95 / P99</li></ul>
  Hesaptan önce uç değerler ayıklanır (medyan/MAD dayanıklı z-skoru &gt; 3.5, ardından tekrarlı 3σ);
  böylece arızalı motor verisi limitleri şişirmez.</li>
<li><b>Artış hızı</b> (JOAP yaklaşımı) — Aşınma/kirletici elementler ve FTIR parametreleri için
ppm / 100 saat yağ çalışması. Aynı yağ dönemindeki (motor saati ve yağ saati farkı tutarlı) bir önceki
numuneye göre; yoksa sıfır yağa göre hesaplanır. Bu, farklı yağ saatlerindeki numuneleri
karşılaştırılabilir kılar (13 saatlik rodaj ile 500 saatlik saha numunesi). Hızın da istatistiksel
uyarı/alarm limitleri hesaplanır.</li>
</ol>
<h3>Rapor okuma algoritması</h3>
<p>PDF'teki kelimeler konumlarıyla okunur; numune sütunları "Sample Number" satırındaki analiz
numaralarından bulunur. Etiketler normalize edilir (Türkçe karakter, birim, noktalama temizlenir),
ardından sırasıyla: öğrenilmiş eşleştirmeler → kurallar → element ad/sembol tablosu (Ca = Kalsiyum)
→ bulanık eşleştirme ile tanınır. Değerler etiket satırlarına sıra korumalı dinamik programlama ile
hizalanır ve sayfadaki sistematik kayma doğrusal modelle düzeltilir. Tanınmayan satırlar size sorulur
ve verdiğiniz eşleştirme bir sonraki raporlar için hatırlanır. Taranmış PDF'lerde (Tesseract kuruluysa)
OCR ile aynı algoritma çalışır.</p>
"""


def default_db_path() -> str:
    docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or str(Path.home())
    return str(Path(docs) / "YagAnalizi" / "yag_analizi.db")


class MainWindow(QMainWindow):
    def __init__(self, db_path: str | None = None):
        super().__init__()
        self.qs = QSettings("YagAnalizi", "MotorYagiAnaliz")
        path = db_path or self.qs.value("db_path") or default_db_path()
        self.state = AppState(Database(path))
        self.qs.setValue("db_path", path)
        self.resize(1400, 860)
        self.setAcceptDrops(True)

        self.tabs = QTabWidget()
        self.tabs.addTab(SamplesTab(self.state), "Numuneler")
        self.tabs.addTab(TrendTab(self.state), "Trend")
        self.tabs.addTab(StatsTab(self.state), "İstatistik && Limitler")
        self.tabs.addTab(CorrelationTab(self.state), "İlişkiler (Korelasyon)")
        self.setCentralWidget(self.tabs)
        self._menus()
        self.state.changed.connect(self._update_title)
        self._update_title()

    def _update_title(self):
        n = len(self.state.samples)
        self.setWindowTitle(f"{APP_NAME} — {self.state.db.path}  ({n} numune)")
        self.statusBar().showMessage(
            "PDF raporlarını pencereye sürükleyip bırakabilirsiniz.  Veritabanı: " + self.state.db.path)

    def _menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&Dosya")
        self._act(m, "PDF rapor yükle…", self.import_pdfs, QKeySequence("Ctrl+O"))
        self._act(m, "Geçmiş Excel'i içe aktar…", self.import_excel)
        m.addSeparator()
        self._act(m, "Excel'e dışa aktar…", self.export_excel, QKeySequence("Ctrl+E"))
        m.addSeparator()
        self._act(m, "Yeni veritabanı…", self.new_db)
        self._act(m, "Veritabanı aç…", self.open_db)
        self._act(m, "Veritabanını yedekle…", self.backup_db)
        m.addSeparator()
        self._act(m, "Çıkış", self.close, QKeySequence("Ctrl+Q"))
        m = mb.addMenu("&Ayarlar")
        self._act(m, "Ayarlar…", self.open_settings)
        m = mb.addMenu("&Yardım")
        self._act(m, "Değerlendirme yöntemleri", self.show_methods)

    def _act(self, menu, text, fn, shortcut=None):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(shortcut)
        a.triggered.connect(fn)
        menu.addAction(a)
        return a

    # ------------------------------------------------------------- içe aktarma
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls()]
        pdfs = [f for f in files if f.lower().endswith(".pdf")]
        xls = [f for f in files if f.lower().endswith((".xlsx", ".xlsm"))]
        if pdfs:
            self._import_pdf_files(pdfs)
        for x in xls:
            self._import_excel_file(x)

    def import_pdfs(self):
        files, _ = QFileDialog.getOpenFileNames(self, "PDF raporları seçin", self.qs.value("last_dir", ""),
                                                "PDF (*.pdf)")
        if files:
            self.qs.setValue("last_dir", str(Path(files[0]).parent))
            self._import_pdf_files(files)

    def _matcher(self):
        return LabelMatcher(self.state.db.aliases(), self.state.db.custom_parameters())

    def _import_pdf_files(self, files):
        total = {"inserted": 0, "updated": 0, "skipped": 0}
        errors = []
        for f in files:
            try:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    report = parse_pdf(f, self._matcher())
                finally:
                    QApplication.restoreOverrideCursor()
            except ParseError as exc:
                errors.append(f"{Path(f).name}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{Path(f).name}: beklenmeyen hata: {exc}\n{traceback.format_exc(limit=3)}")
                continue
            if not report.samples:
                errors.append(f"{Path(f).name}: sonuç tablosu bulunamadı.")
                continue
            dlg = PdfImportDialog(self.state, report, self)
            if dlg.exec() == QDialog.Accepted and dlg.result_counts:
                for k, v in dlg.result_counts.items():
                    total[k] += v
        self.state.reload()
        msg = (f"Eklenen: {total['inserted']}   Güncellenen: {total['updated']}   "
               f"Zaten kayıtlı (atlanan): {total['skipped']}")
        if errors:
            QMessageBox.warning(self, "İçe aktarma", msg + "\n\nHatalar:\n" + "\n".join(errors))
        else:
            self.statusBar().showMessage(msg, 10000)

    def import_excel(self):
        f, _ = QFileDialog.getOpenFileName(self, "Excel dosyası seçin", self.qs.value("last_dir", ""),
                                           "Excel (*.xlsx *.xlsm)")
        if f:
            self._import_excel_file(f)

    def _import_excel_file(self, f):
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                sheets = read_workbook(f, self._matcher())
            finally:
                QApplication.restoreOverrideCursor()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Excel", f"Excel okunamadı: {exc}")
            return
        dlg = ExcelImportDialog(self.state, f, sheets, self)
        if dlg.exec() == QDialog.Accepted and dlg.result_counts:
            self.state.reload()
            c = dlg.result_counts
            QMessageBox.information(self, "Excel", f"Eklenen: {c['inserted']}\nGüncellenen: {c['updated']}"
                                                   f"\nAtlanan (kayıtlı): {c['skipped']}")

    # ------------------------------------------------------------- diğer
    def export_excel(self):
        path, _ = QFileDialog.getSaveFileName(self, "Excel'e aktar", "yag_analizleri.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        st = self.state
        try:
            export_workbook(path, st.samples, st.params, st.evaluator, st.platforms)
        except OSError as exc:
            QMessageBox.critical(self, "Hata", str(exc))
            return
        self.statusBar().showMessage(f"Kaydedildi: {path}", 8000)

    def new_db(self):
        path, _ = QFileDialog.getSaveFileName(self, "Yeni veritabanı", default_db_path(), "SQLite (*.db)")
        if path:
            self._switch_db(path)

    def open_db(self):
        path, _ = QFileDialog.getOpenFileName(self, "Veritabanı aç", str(Path(self.state.db.path).parent),
                                              "SQLite (*.db *.sqlite)")
        if path:
            self._switch_db(path)

    def _switch_db(self, path):
        try:
            db = Database(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Veritabanı", str(exc))
            return
        self.state.set_db(db)
        self.qs.setValue("db_path", path)

    def backup_db(self):
        path, _ = QFileDialog.getSaveFileName(self, "Yedek kaydet", "yag_analizi_yedek.db", "SQLite (*.db)")
        if not path:
            return
        import sqlite3
        dst = sqlite3.connect(path)
        with dst:
            self.state.db.conn.backup(dst)
        dst.close()
        self.statusBar().showMessage(f"Yedek alındı: {path}", 8000)

    def open_settings(self):
        SettingsDialog(self.state, self).exec()

    def show_methods(self):
        d = QDialog(self)
        d.setWindowTitle("Değerlendirme yöntemleri")
        d.resize(760, 640)
        lay = QVBoxLayout(d)
        tb = QTextBrowser()
        tb.setHtml(METHODS_HTML)
        lay.addWidget(tb)
        d.exec()
