"""On-screen recording indicator: a translucent, click-through red circle that is
excluded from the recording itself.
"""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QRegion
from PySide6.QtWidgets import QWidget

WDA_EXCLUDEFROMCAPTURE = 0x11

# Windows lets a window opt out of screen capture, and the macOS backend leaves
# this app's windows out of its capture. On Linux the circle would end up in
# the recording, so it isn't shown at all (the tray dot stays).
CAN_EXCLUDE_FROM_CAPTURE = sys.platform in ("win32", "darwin")

_BLINK_DIM_FACTOR = 0.35


class RecordingIndicator(QWidget):
    """A small translucent red circle, click-through and always on top.

    On Windows 10 2004+ it asks the OS to exclude it from any screen capture
    (SetWindowDisplayAffinity), so it never appears in the recording. If that
    fails (older Windows, other platforms), `excluded_from_capture` stays False
    and the caller should warn that the circle will be recorded. On macOS the
    recording backend leaves it out instead (and warns itself if it can't).

    NOTE: the round shape comes from a window mask and the translucency from
    whole-window opacity - deliberately not WA_TranslucentBackground. That
    makes a per-pixel-alpha layered window (UpdateLayeredWindow), for which
    SetWindowDisplayAffinity fails (ERROR_NOT_ENOUGH_MEMORY) - found live when
    the circle showed up in real recordings.
    """

    def __init__(self, diameter: int = 24, opacity: float = 0.6) -> None:
        super().__init__()
        self._opacity = opacity
        self._blink_on = True
        self.excluded_from_capture = False

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )
        self.resize(diameter, diameter)
        self.setMask(QRegion(0, 0, diameter, diameter, QRegion.Ellipse))
        self.setWindowOpacity(opacity)
        # macOS hides tool windows whenever another app is active - which is
        # all the time while recording something else.
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)

        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._toggle_blink)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.excluded_from_capture = self._exclude_from_capture()
        self._blink_timer.start(900)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._blink_timer.stop()

    def paintEvent(self, event) -> None:
        QPainter(self).fillRect(self.rect(), QColor(220, 30, 30))

    def _toggle_blink(self) -> None:
        self._blink_on = not self._blink_on
        dim = 1.0 if self._blink_on else _BLINK_DIM_FACTOR
        self.setWindowOpacity(self._opacity * dim)

    def _exclude_from_capture(self) -> bool:
        if sys.platform == "darwin":
            return True  # the capture filter excludes the whole app, see MacBackend
        if sys.platform != "win32":
            return False
        hwnd = int(self.winId())
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))
