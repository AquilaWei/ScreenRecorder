"""On-screen recording indicator: a translucent, click-through red circle that is
excluded from the recording itself.
"""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

WDA_EXCLUDEFROMCAPTURE = 0x11


class RecordingIndicator(QWidget):
    """A small translucent red circle, click-through and always on top.

    On Windows 10 2004+ it asks the OS to exclude it from any screen capture
    (SetWindowDisplayAffinity), so it never appears in the recording. On older
    Windows or other platforms that call is a no-op and callers must instead
    place the indicator outside the captured region (handled by the caller,
    not this widget).
    """

    def __init__(self, diameter: int = 24, opacity: float = 0.6) -> None:
        super().__init__()
        self._diameter = diameter
        self._opacity = opacity
        self._blink_on = True
        self.excluded_from_capture = False

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(diameter, diameter)

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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        alpha = int(255 * self._opacity * (1.0 if self._blink_on else 0.35))
        painter.setBrush(QColor(220, 30, 30, alpha))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, self._diameter, self._diameter)

    def _toggle_blink(self) -> None:
        self._blink_on = not self._blink_on
        self.update()

    def _exclude_from_capture(self) -> bool:
        if sys.platform != "win32":
            return False
        hwnd = int(self.winId())
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))
