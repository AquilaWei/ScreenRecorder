"""The app icon, drawn in code so the window icon and the packaged .ico match."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def render_icon(size: int) -> QPixmap:
    """A dark rounded square with a red "record" dot."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)

    painter.setBrush(QColor("#2b2d31"))
    radius = size * 0.22
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

    ring = size * 0.30
    painter.setBrush(QColor("#ffffff"))
    painter.drawEllipse(QRectF(size / 2 - ring, size / 2 - ring, ring * 2, ring * 2))

    dot = size * 0.22
    painter.setBrush(QColor("#e53935"))
    painter.drawEllipse(QRectF(size / 2 - dot, size / 2 - dot, dot * 2, dot * 2))

    painter.end()
    return pixmap


def make_app_icon() -> QIcon:
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(render_icon(size))
    return icon
