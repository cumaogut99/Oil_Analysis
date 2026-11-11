"""Tema yöneticisi: harici tasarım dosyalarını (assets/) yükler ve uygular.

assets/
  style.qss          QSS şablonu ({{token}} alanları)
  themes/*.json      renk/yazı tipi token'ları (light, dark, ...)
  icons/*.svg        çizgi ikonlar (stroke="currentColor" -> temadan renklendirilir)
  mpl/*.mplstyle     grafik stilleri (tema adıyla aynı)

Yeni bir tema için themes/ klasörüne json, mpl/ klasörüne aynı adlı mplstyle
eklemeniz yeterlidir; menüde otomatik görünür.
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
_current: dict = {}
_icon_cache: dict = {}


def available_themes() -> dict[str, str]:
    out = {}
    for f in sorted((ASSETS / "themes").glob("*.json")):
        try:
            out[f.stem] = json.loads(f.read_text(encoding="utf-8")).get("name", f.stem)
        except (OSError, json.JSONDecodeError):
            continue
    return out


def tokens() -> dict:
    return _current


def token(key: str, default=None):
    return _current.get(key, default)


def _resolve_font(families: str) -> str:
    from PySide6.QtGui import QFontDatabase
    installed = set(QFontDatabase.families())
    for fam in (f.strip() for f in families.split(",")):
        if fam in installed:
            return fam
    return QFontDatabase.systemFont(QFontDatabase.GeneralFont).family()


def _write_colored_icons(theme_name: str, color: str, suffix: str) -> str:
    """QSS'te url() ile kullanılacak renklendirilmiş ikon kopyaları."""
    out = Path(tempfile.gettempdir()) / "yag_analizi_theme" / f"{theme_name}_{suffix}"
    out.mkdir(parents=True, exist_ok=True)
    for svg in (ASSETS / "icons").glob("*.svg"):
        (out / svg.name).write_text(svg.read_text(encoding="utf-8").replace("currentColor", color),
                                    encoding="utf-8")
    return out.as_posix()


def apply(app, name: str = "light") -> dict:
    """Temayı uygulamaya yükler (QSS + yazı tipi + matplotlib stili)."""
    global _current
    path = ASSETS / "themes" / f"{name}.json"
    if not path.exists():
        name, path = "light", ASSETS / "themes" / "light.json"
    t = json.loads(path.read_text(encoding="utf-8"))
    t["theme_id"] = name
    t["font_family"] = _resolve_font(t.get("font_family", "Segoe UI"))
    t["icons"] = _write_colored_icons(name, t["text_muted"], "muted")
    t["icons_inverse"] = _write_colored_icons(name, t["text_inverse"], "inverse")
    _current = t
    _icon_cache.clear()

    qss = (ASSETS / "style.qss").read_text(encoding="utf-8")
    qss = re.sub(r"\{\{(\w+)\}\}", lambda m: str(t.get(m.group(1), m.group(0))), qss)
    from PySide6.QtGui import QFont
    font = QFont(t["font_family"])
    size = float(str(t.get("font_size", "10pt")).replace("pt", ""))
    font.setPointSizeF(size)
    app.setFont(font)
    app.setStyleSheet(qss)

    import matplotlib
    import matplotlib.style
    matplotlib.rcdefaults()
    mpl = ASSETS / "mpl" / f"{name}.mplstyle"
    if mpl.exists():
        matplotlib.style.use(str(mpl))
    return t


def icon(name: str, color: str | None = None, size: int = 20):
    """SVG ikonu tema rengiyle QIcon olarak döndürür."""
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer

    color = color or token("text_muted", "#64748b")
    key = (name, color, size)
    if key in _icon_cache:
        return _icon_cache[key]
    f = ASSETS / "icons" / f"{name}.svg"
    if not f.exists():
        return QIcon()
    data = f.read_text(encoding="utf-8").replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(data.encode("utf-8")))
    ic = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        renderer.render(p)
        p.end()
        pm.setDevicePixelRatio(scale)
        ic.addPixmap(pm)
    _icon_cache[key] = ic
    return ic


# --------------------------------------------------------- durum renkleri
def status_bg(status):
    from PySide6.QtGui import QColor
    k = {0: "status_ok", 1: "status_warn", 2: "status_alarm"}.get(status)
    return QColor(token(k)) if k and token(k) else None


def status_fg(status):
    from PySide6.QtGui import QColor
    k = {0: "status_ok_fg", 1: "status_warn_fg", 2: "status_alarm_fg"}.get(status)
    return QColor(token(k)) if k and token(k) else None


def chart_status(status) -> str:
    return token({0: "chart_ok", 1: "chart_warn", 2: "chart_alarm"}.get(status, "chart_na"), "#9e9e9e")
