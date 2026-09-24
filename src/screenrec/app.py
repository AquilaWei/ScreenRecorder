"""Application entry point: builds the QApplication and shows the main window."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from screenrec.ui.app_icon import make_app_icon
from screenrec.ui.main_window import MainWindow

APP_ID = "ScreenRec.ScreenRecorder"


def run() -> int:
    if sys.platform == "win32":
        import ctypes

        # Without an explicit AppUserModelID, Windows groups the taskbar button
        # under python.exe and shows its icon instead of ours.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)

    app = QApplication(sys.argv)
    app.setApplicationName("ScreenRec")
    # Wayland matches windows to their launcher entry (and so their taskbar
    # icon) by this name; it is the Flatpak's app id and .desktop file name.
    app.setDesktopFileName("io.github.AquilaWei.ScreenRecorder")
    app.setWindowIcon(make_app_icon())
    window = MainWindow()
    window.show()
    return app.exec()
