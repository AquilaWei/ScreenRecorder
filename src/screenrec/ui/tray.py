"""System-tray icon shown while recording, as a second recording indicator."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QSystemTrayIcon

RECORDING_RED = QColor("#e53935")
RECORDING_TOOLTIP = "ScreenRec：錄製中"


def render_recording_dot(size: int) -> QPixmap:
    """A plain red dot filling the icon, readable at 16px tray size."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(RECORDING_RED)
    margin = size * 0.1
    painter.drawEllipse(QRectF(margin, margin, size - 2 * margin, size - 2 * margin))
    painter.end()
    return pixmap


class RecordingTrayIcon(QSystemTrayIcon):
    """A red dot in the system tray while recording.

    The on-screen RecordingIndicator is excluded from screen capture, so it is
    also invisible through remote-desktop viewers (AnyDesk, Chrome Remote
    Desktop), which are screen captures too - found live when the user,
    working remotely, saw no indicator at all. This icon is NOT excluded, so
    it shows remotely; the price is that it appears in the recorded taskbar.

    If the desktop has no system tray, show() silently does nothing.
    """

    def __init__(self) -> None:
        icon = QIcon()
        for size in (16, 20, 24, 32, 48):
            icon.addPixmap(render_recording_dot(size))
        super().__init__(icon)
        self.setToolTip(RECORDING_TOOLTIP)
