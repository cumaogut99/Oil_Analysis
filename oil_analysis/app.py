"""Uygulama giriş noktası."""
from __future__ import annotations

import os
import sys
import traceback


def _selftest(out_path: str) -> int:
    """Paketlenmiş exe'nin eksiksiz çalıştığını doğrular (build_exe.py kullanır).

    Pencere göstermeden (offscreen) tema dosyalarını, ana pencereyi, PDF/Excel
    kütüphanelerini ve veritabanını dener; sonucu out_path dosyasına yazar.
    """
    import tempfile
    lines = []
    ok = True

    def step(name, fn):
        nonlocal ok
        try:
            res = fn()
            lines.append(f"OK    {name}" + (f": {res}" if res else ""))
        except Exception:  # noqa: BLE001
            ok = False
            lines.append(f"HATA  {name}\n{traceback.format_exc()}")

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication([sys.argv[0]])
    tmp = tempfile.mkdtemp(prefix="yag_selftest_")

    def t_theme():
        from .ui import theme
        t = theme.apply(app, "light")
        missing = [p for p in ("style.qss", "themes/light.json", "themes/dark.json", "icons/drop.svg",
                               "mpl/light.mplstyle") if not (theme.ASSETS / p).exists()]
        if missing:
            raise FileNotFoundError(f"Tasarım dosyaları eksik: {missing}")
        if theme.icon("drop").isNull():
            raise RuntimeError("SVG ikon yüklenemedi (QtSvg eklentisi eksik)")
        return f"tema={t['name']}"

    def t_libs():
        import matplotlib
        import numpy
        import openpyxl
        import pdfplumber
        import pypdfium2  # noqa: F401
        wb = openpyxl.Workbook()
        wb.active["A1"] = 1
        wb.save(os.path.join(tmp, "t.xlsx"))
        return (f"matplotlib {matplotlib.__version__}, numpy {numpy.__version__}, "
                f"pdfplumber {pdfplumber.__version__}")

    def t_window():
        from PySide6.QtCore import QSettings

        from .ui.main_window import MainWindow
        # kullanıcının kayıtlı ayarlarına dokunmamak için geçici ayar dosyası
        qs = QSettings(os.path.join(tmp, "ayarlar.ini"), QSettings.IniFormat)
        w = MainWindow(os.path.join(tmp, "t.db"), qs)
        w.show()
        for i in range(len(w.pages)):
            w.nav.setCurrentRow(i)
            app.processEvents()
        w.set_theme("dark")
        app.processEvents()
        w.close()
        return f"{len(w.pages)} sayfa"

    def t_pdf():
        from .pdf_parser import parse_pdf
        path = os.path.join(tmp, "test.pdf")
        _write_test_pdf(path)
        rep = parse_pdf(path, allow_ocr=False)
        s = rep.samples.get("ELD00001")
        if s is None or s.values.get("fe") != "12" or s.values.get("ca") != "2500":
            raise RuntimeError(f"PDF değerleri yanlış okundu: {s and s.values}")
        return f"{len(s.values)} parametre okundu"

    step("Tema ve tasarım dosyaları", t_theme)
    step("PDF okuma (pdfminer)", t_pdf)
    step("PDF / Excel / grafik kütüphaneleri", t_libs)
    step("Ana pencere ve sayfalar", t_window)
    lines.append("SONUÇ: " + ("BAŞARILI" if ok else "HATALI"))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return 0 if ok else 1


def _write_test_pdf(path: str):
    """Self-test için SGS tablo düzeninde küçük bir PDF yazar (harici kütüphane gerektirmez)."""
    rows = [("Sample Number", "ELD00001"), ("Equipment life (h)", "100,5"), ("Lubricant life (h)", "50")]
    rows += [(f"{el} mg/kg", v) for el, v in (("Ba", "0"), ("Ca", "2500"), ("Mg", "10"), ("Mo", "1"),
                                              ("P", "800"), ("Zn", "900"), ("B", "60"), ("Si", "5"),
                                              ("Na", "2"), ("Al", "3"), ("Cr", "1"), ("Cu", "4"),
                                              ("Fe", "12"), ("Pb", "2"))]
    ops, y = [], 760
    for label, val in rows:
        ops.append(f"BT /F1 8 Tf 40 {y} Td ({label}) Tj ET")
        ops.append(f"BT /F1 8 Tf 400 {y} Td ({val}) Tj ET")
        y -= 12
    stream = "\n".join(ops).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >>"
            b" /Contents 4 0 R >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    with open(path, "wb") as f:
        f.write(bytes(out))


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    os.environ.setdefault("QT_API", "pyside6")
    if len(argv) > 2 and argv[1] == "--selftest":
        return _selftest(argv[2])

    from PySide6.QtWidgets import QApplication

    from .ui.main_window import MainWindow

    app = QApplication(argv)
    app.setApplicationName("Motor Yağı Analiz")
    app.setStyle("Fusion")
    # Qt'nin standart metinleri (Evet/Hayır, dosya penceresi…) için Türkçe çeviri
    from PySide6.QtCore import QLibraryInfo, QLocale, QSettings, QTranslator
    tr = QTranslator(app)
    if tr.load(QLocale("tr_TR"), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(tr)

    from .ui import theme
    theme.apply(app, QSettings("YagAnalizi", "MotorYagiAnaliz").value("theme", "light"))
    app.setWindowIcon(theme.icon("drop", "#2563eb", 64))
    db_path = argv[1] if len(argv) > 1 and argv[1].endswith((".db", ".sqlite")) else None
    win = MainWindow(db_path)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
