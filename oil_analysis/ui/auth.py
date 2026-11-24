"""Düzenleme şifresi: silme / değiştirme işlemlerinden önce sorulur.

Sıkı bir güvenlik önlemi değildir; yanlışlıkla yapılan değişiklikleri önlemek içindir.
Şifrenin özeti (SHA-256) veritabanı dosyasında saklanır (bkz. ``Database.check_password``).
Doğru şifre girildikten sonra kısa bir süre (UNLOCK_SECONDS, her yetkili işlemde yenilenir)
tekrar sorulmaz; böylece art arda yapılan düzenlemelerde her seferinde şifre girilmez.
"""
from __future__ import annotations

import time

from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox

UNLOCK_SECONDS = 5 * 60
_unlocked_until = 0.0


def is_unlocked() -> bool:
    return time.monotonic() < _unlocked_until


def unlock(seconds: float = UNLOCK_SECONDS):
    global _unlocked_until
    _unlocked_until = time.monotonic() + seconds


def lock():
    global _unlocked_until
    _unlocked_until = 0.0


def require_password(parent, db, action: str = "Bu işlem") -> bool:
    """Şifre doğrulanırsa True döner. İptal / hatalı girişte False."""
    if is_unlocked():
        unlock()  # süreyi yenile
        return True
    msg = f"{action} için düzenleme şifresini girin:"
    while True:
        pw, ok = QInputDialog.getText(parent, "Şifre gerekli", msg, QLineEdit.Password)
        if not ok:
            return False
        if db.check_password(pw):
            unlock()
            return True
        QMessageBox.warning(parent, "Şifre", "Şifre hatalı.")
        msg = f"Şifre hatalı. {action} için tekrar deneyin:"
