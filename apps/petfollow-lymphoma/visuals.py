"""Vector artwork and native window appearance for the PET follow-up workstation."""

import sys
from functools import lru_cache

from PySide6.QtCore import QByteArray, QEvent, QObject, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QDialog


# Each action shares a 24-unit grid, round terminals and a clear 2-unit perimeter.
_STROKES = {
    "folder": "M3 17.5V6a1.5 1.5 0 0 1 1.5-1.5h5L12 7h6.5A1.5 1.5 0 0 1 20 8.5V10 "
              "M3 17.5l2.4-7.1A1.3 1.3 0 0 1 6.6 9.5H21l-2.6 8.3a2 2 0 0 1-1.9 1.4H5a2 2 0 0 1-2-1.7Z",
    "layers": "M3 8l9-4.7L21 8l-9 4.7L3 8Z M3 12.2l9 4.7 9-4.7 M3 16.4l9 4.7 9-4.7",
    "link": "M9.7 6.8l1.9-1.9a4.8 4.8 0 0 1 6.8 6.8l-2 2 "
            "M14.3 17.2l-1.9 1.9a4.8 4.8 0 0 1-6.8-6.8l2-2 M8.8 15.2l6.4-6.4",
    "checklist": "M4 6.7l1.5 1.5 3-3.4 M12 7h8 M4 12.8l1.5 1.5 3-3.4 M12 13h8 M5 19h2 M12 19h8",
    "report": "M6 3.5h8l4.5 4.8v12.2H6V3.5Z M13.5 3.5v5h5 M9 12h6.5 M9 15.6h5",
    "history": "M3.3 5v4.5h4.5 M3.7 9a8.6 8.6 0 1 1 .7 7.6 M12 7v5l3.4 2",
    "add": "M12 4.8v14.4 M4.8 12h14.4",
    "seed": "M4 9V5a1 1 0 0 1 1-1h4 M15 4h4a1 1 0 0 1 1 1v4 M20 15v4a1 1 0 0 1-1 1h-4 "
            "M9 20H5a1 1 0 0 1-1-1v-4 M15.2 12a3.2 3.2 0 1 1-6.4 0 3.2 3.2 0 0 1 6.4 0Z",
    "paint": "M10.7 12.6l6.7-8a1.9 1.9 0 0 1 2.9 2.4l-6.6 8.2Z "
             "M10.9 13c-2.5-.7-4.4.6-4.6 2.8-.2 1.8-1.1 2.6-2.9 3 3.8 2 8.7 1.1 9.4-3.5",
    "eraser": "M4.4 13.5l8.7-9a1.5 1.5 0 0 1 2.1 0l4.5 4.4a1.5 1.5 0 0 1 0 2.1l-7.8 8H8.3l-3.9-3.5a1.4 1.4 0 0 1 0-2Z "
              "M8.2 9.6l6.6 6.4 M11.9 19h8.6",
    "save": "M4 4.5h12l4 4V20H4V4.5Z M8 4.5v5h7v-5 M8 20v-6.7h8V20",
    "warning": "M10.7 4.7a1.5 1.5 0 0 1 2.6 0l7.3 13a1.4 1.4 0 0 1-1.2 2.1H4.6a1.4 1.4 0 0 1-1.2-2.1Z "
               "M12 9v4.8 M12 17v.1",
    "switch": "M4 8h15 M16 4l4 4-4 4 M20 16H5 M8 12l-4 4 4 4",
    "chevron": "M9 5.5l6.5 6.5L9 18.5",
    "crosshair": "M18.5 12a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0Z M12 2v5 M12 17v5 M2 12h5 M17 12h5",
}

# An axial chest section with a single bright focus, on a rounded navy tile.
_BRAND = """
<rect x=".5" y=".5" width="23" height="23" rx="5.7" fill="#103442"/>
<path d="M2.8 12.5C2.8 8.8 6.1 5.5 10 5.1c1.6-.2 2.4-.2 4 0 3.9.4 7.2 3.7 7.2 7.4 0 4.1-3.9 6.7-9.2 6.7s-9.2-2.6-9.2-6.7Z"
      fill="#157d84" stroke="#5ae0d7" stroke-width="1.45"/>
<path d="M10.3 7.9c-2.1-.5-5 2.6-4.8 5.1.2 2 1.8 2.9 3.6 2.4 1.4-.5 1.9-1.8 1.7-3.8l-.5-3.7Z
         M13.7 7.9c2.1-.5 5 2.6 4.8 5.1-.2 2-1.8 2.9-3.6 2.4-1.4-.5-1.9-1.8-1.7-3.8l.5-3.7Z" fill="#103442"/>
<circle cx="16" cy="11.5" r="1.6" fill="#ddfffa"/>
"""


@lru_cache(maxsize=128)
def icon(name: str, color: str = "#b7c8d6", size: int = 20) -> QIcon:
    """Render native toolbar and title-bar icons, including high-DPI pixmaps."""
    if name == "brand":
        artwork = _BRAND
        sizes = {size, 16, 24, 32, 48, 64, 128, 256}
    else:
        stroke = QColor(color).name()
        artwork = (f'<path d="{_STROKES[name]}" fill="none" stroke="{stroke}" stroke-width="1.7" '
                   'stroke-linecap="round" stroke-linejoin="round"/>')
        sizes = {size, round(size * 1.5), size * 2, size * 3}
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{artwork}</svg>'
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    result = QIcon()
    for side in sorted(sizes):
        pixmap = QPixmap(side, side)
        pixmap.fill(Qt.GlobalColor.transparent)
        with QPainter(pixmap) as painter:
            renderer.render(painter)
        result.addPixmap(pixmap)
    return result


def apply_window_chrome(widget):
    """Style a native Windows caption while retaining its system controls."""
    if sys.platform != "win32" or QGuiApplication.platformName() != "windows":
        return

    import ctypes
    from ctypes import wintypes

    try:
        set_attribute = ctypes.WinDLL("dwmapi").DwmSetWindowAttribute
        set_attribute.argtypes = (wintypes.HWND, wintypes.DWORD, wintypes.LPCVOID, wintypes.DWORD)
        set_attribute.restype = ctypes.c_long
        hwnd = int(widget.winId())
        # DWM ignores unsupported attributes. COLORREF values are packed as BGR.
        attributes = ((20, 1), (35, 0x241B13), (36, 0xEDE7DA))
        for attribute, value in attributes:
            data = wintypes.DWORD(value)
            set_attribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))
    except (AttributeError, OSError):
        pass  # Windows without DWM uses its standard caption.


class _DialogChrome(QObject):
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show and isinstance(watched, QDialog):
            apply_window_chrome(watched)
        return False


def configure_application(app):
    """Keep native popups and dialog captions consistent with the workstation."""
    app.setStyle("Fusion")
    font = QFont("Microsoft YaHei UI", 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, "#141d29"),
        (QPalette.ColorRole.WindowText, "#e2ebf2"),
        (QPalette.ColorRole.Base, "#101923"),
        (QPalette.ColorRole.AlternateBase, "#172330"),
        (QPalette.ColorRole.Text, "#e2ebf2"),
        (QPalette.ColorRole.Button, "#223140"),
        (QPalette.ColorRole.ButtonText, "#dbe7ef"),
        (QPalette.ColorRole.Highlight, "#34645f"),
        (QPalette.ColorRole.HighlightedText, "#ecfff9"),
        (QPalette.ColorRole.ToolTipBase, "#263644"),
        (QPalette.ColorRole.ToolTipText, "#f0f5f8"),
        (QPalette.ColorRole.Link, "#8ae0d0"),
    ):
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#748493"))
    app.setPalette(palette)
    chrome = _DialogChrome(app)
    app.installEventFilter(chrome)
    app._workstation_chrome = chrome
