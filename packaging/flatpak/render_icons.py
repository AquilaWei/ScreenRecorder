"""Write the app icon as hicolor PNGs for the Flatpak's launcher entry.

QT_QPA_PLATFORM=offscreen python3 render_icons.py <hicolor dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication

from screenrec.ui.app_icon import ICON_SIZES, render_icon

APP_ID = "io.github.AquilaWei.ScreenRecorder"

if __name__ == "__main__":
    app = QGuiApplication(sys.argv)  # QPixmap needs one
    hicolor = Path(sys.argv[1])
    for size in ICON_SIZES:
        path = hicolor / f"{size}x{size}" / "apps" / f"{APP_ID}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not render_icon(size).save(str(path), "PNG"):
            sys.exit(f"could not write {path}")
