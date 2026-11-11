"""Uygulama giriş noktası."""
from __future__ import annotations

import sys


def main(argv=None):
    from PySide6.QtWidgets import QApplication

    from .ui.main_window import MainWindow

    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName("Motor Yağı Analiz")
    app.setStyle("Fusion")
    # Qt'nin standart metinleri (Evet/Hayır, dosya penceresi…) için Türkçe çeviri
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    tr = QTranslator(app)
    if tr.load(QLocale("tr_TR"), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(tr)
    db_path = argv[1] if len(argv) > 1 and argv[1].endswith((".db", ".sqlite")) else None
    win = MainWindow(db_path)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
