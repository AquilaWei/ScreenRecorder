"""Render the app icon to a multi-size .ico for the exe and installer."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication, QImage

from screenrec.ui.app_icon import ICON_SIZES, render_icon


def _png_bytes(size: int) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    render_icon(size).save(buffer, "PNG")
    return bytes(buffer.data())


def _dib_bytes(size: int) -> bytes:
    """Classic 32-bit BGRA DIB entry. Some consumers (e.g. .NET's Icon) can't
    read PNG entries, so only the 256px image is stored as PNG."""
    image = render_icon(size).toImage().convertToFormat(QImage.Format.Format_ARGB32)
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    rows = [bytes(image.constScanLine(y))[: size * 4] for y in range(size)]
    pixels = b"".join(reversed(rows))  # DIBs are stored bottom-up
    and_mask = b"\x00" * (((size + 31) // 32) * 4 * size)  # alpha channel is used instead
    return header + pixels + and_mask


def write_ico(path: Path) -> None:
    images = [(size, _png_bytes(size) if size >= 256 else _dib_bytes(size)) for size in ICON_SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b""
    for size, data in images:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    path.write_bytes(header + entries + b"".join(data for _, data in images))


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("screenrec.ico")
    write_ico(out)
    print(f"wrote {out}")
