"""Ana pencere."""
from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, QStandardPaths, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)

from ..db import Database
from ..excel_importer import read_workbook
from ..export import export_workbook
from ..parameters import LabelMatcher
from ..pdf_parser import ParseError, parse_pdf
from . import theme
from .common import AppState, button
from .corr_tab import CorrelationTab
from .import_dialogs import ExcelImportDialog, PdfImportDialog
from .parts_tab import PartsTab
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
<h3>İstatistikten hariç tutma</h3>
<p>Absürt / hatalı değerler <b>İstatistik &amp; Limitler</b> sayfasındaki değer inceleme panelinden
(tek tek veya önerilen uç değerler olarak) ya da numune detayındaki <i>İst. hariç</i> sütunundan
istatistik dışı bırakılabilir; numunenin tamamı da hariç tutulabilir. Hariç değerler ortalama, min/max,
limit, artış hızı ve korelasyon hesaplarına katılmaz; ancak silinmez, numunenin kendi değerlendirmesi
yapılmaya devam eder ve kararlar veritabanında nedenleriyle saklanır.</p>
<h3>Parça tahmini</h3>
<p><b>Malzeme Kaynakları</b> sayfasında her malzeme için olası kaynak parçalar tanımlanır. Numune
detayındaki <i>Parça Tahmini</i> sekmesi, önceki numuneye göre anlamlı artan (varsayılan ≥ %50 ve
≥ 2 ppm) veya uyarı/alarm veren malzemeleri listeler ve kaynak parçaları puanlar (alarm 3, uyarı 2,
artış 1). Birden çok malzemenin işaret ettiği parça üst sıraya çıkar (ör. Fe + Cr → segman).</p>
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


PAGES = [SamplesTab, TrendTab, StatsTab, CorrelationTab, PartsTab]


class MainWindow(QMainWindow):
    def __init__(self, db_path: str | None = None, qsettings: QSettings | None = None):
        super().__init__()
        self.qs = qsettings or QSettings("YagAnalizi", "MotorYagiAnaliz")
        path = db_path or self.qs.value("db_path") or default_db_path()
        self.state = AppState(Database(path))
        self.qs.setValue("db_path", path)
        self.resize(1440, 900)
        self.setMinimumSize(1100, 700)
        self.setAcceptDrops(True)
        self._build_ui()
        self._menus()
        self.state.changed.connect(self._update_title)
        self._update_title()

    # ------------------------------------------------------------ arayüz
    def _build_ui(self, page_index: int = 0):
        root = QWidget()
        root.setObjectName("Content")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # kenar menü
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(232)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 18, 14, 14)
        sl.setSpacing(6)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(theme.icon("drop", theme.token("sidebar_accent"), 28).pixmap(28, 28))
        brand.addWidget(logo)
        tl = QVBoxLayout()
        tl.setSpacing(0)
        t1 = QLabel("Yağ Analiz")
        t1.setObjectName("AppTitle")
        t2 = QLabel("Motor yağı izleme")
        t2.setObjectName("AppSubtitle")
        tl.addWidget(t1)
        tl.addWidget(t2)
        brand.addLayout(tl, 1)
        sl.addLayout(brand)

        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setCursor(Qt.PointingHandCursor)
        self.stack = QStackedWidget()
        self.pages = []
        for cls in PAGES:
            page = cls(self.state)
            self.pages.append(page)
            self.stack.addWidget(page)
            it = QListWidgetItem(theme.icon(cls.icon, theme.token("sidebar_text"), 18), cls.title)
            self.nav.addItem(it)
        self.nav.currentRowChanged.connect(self._go)
        sl.addWidget(self.nav, 1)

        dark = theme.token("dark", False)
        b_theme = button("Açık tema" if dark else "Koyu tema", "sun" if dark else "moon")
        b_theme.setObjectName("SidebarButton")
        b_theme.setIcon(theme.icon("sun" if dark else "moon", theme.token("sidebar_text")))
        b_theme.clicked.connect(self.toggle_theme)
        b_set = button("Ayarlar", "settings")
        b_set.setObjectName("SidebarButton")
        b_set.setIcon(theme.icon("settings", theme.token("sidebar_text")))
        b_set.clicked.connect(self.open_settings)
        b_help = button("Yöntemler", "help")
        b_help.setObjectName("SidebarButton")
        b_help.setIcon(theme.icon("help", theme.token("sidebar_text")))
        b_help.clicked.connect(self.show_methods)
        for b in (b_set, b_help, b_theme):
            sl.addWidget(b)
        self.db_label = QLabel()
        self.db_label.setObjectName("DbLabel")
        self.db_label.setWordWrap(True)
        sl.addSpacing(6)
        sl.addWidget(self.db_label)
        h.addWidget(side)

        # içerik
        right = QWidget()
        right.setObjectName("Content")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        header = QFrame()
        header.setObjectName("Header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(24, 14, 24, 14)
        tbox = QVBoxLayout()
        tbox.setSpacing(2)
        self.page_title = QLabel()
        self.page_title.setObjectName("PageTitle")
        self.page_sub = QLabel()
        self.page_sub.setObjectName("PageSubtitle")
        tbox.addWidget(self.page_title)
        tbox.addWidget(self.page_sub)
        hl.addLayout(tbox, 1)
        b_exp = button("Dışa aktar", "export", tooltip="Tüm veriyi renklendirilmiş Excel'e aktar")
        b_exp.clicked.connect(self.export_excel)
        b_xls = button("Excel içe aktar", "excel", tooltip="Geçmiş analiz Excel'ini içe aktar")
        b_xls.clicked.connect(self.import_excel)
        b_pdf = button("PDF rapor yükle", "pdf", "primary", tooltip="SGS PDF raporlarını yükle (Ctrl+O)")
        b_pdf.clicked.connect(self.import_pdfs)
        for b in (b_exp, b_xls, b_pdf):
            hl.addWidget(b)
        rl.addWidget(header)
        rl.addWidget(self.stack, 1)
        h.addWidget(right, 1)

        old = self.centralWidget()
        self.setCentralWidget(root)
        if old is not None:
            old.deleteLater()
        self.nav.setCurrentRow(page_index)
        self._go(page_index)

    def _go(self, i):
        if i < 0:
            return
        self.stack.setCurrentIndex(i)
        page = self.pages[i]
        self.page_title.setText(page.title)
        self.page_sub.setText(page.subtitle)

    def toggle_theme(self):
        name = "light" if theme.token("dark", False) else "dark"
        self.set_theme(name)

    def set_theme(self, name):
        theme.apply(QApplication.instance(), name)
        self.qs.setValue("theme", name)
        self._build_ui(self.stack.currentIndex())
        self._update_title()

    def _update_title(self):
        n = len(self.state.samples)
        self.setWindowTitle(f"{APP_NAME} — {n} numune")
        self.db_label.setText(f"Veritabanı:\n{Path(self.state.db.path).name}")
        self.db_label.setToolTip(self.state.db.path)
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
        m = mb.addMenu("&Görünüm")
        for tid, tname in theme.available_themes().items():
            self._act(m, f"Tema: {tname}", lambda _c=False, t=tid: self.set_theme(t))
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
