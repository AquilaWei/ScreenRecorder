"""Render the app icon to a .icns for the macOS app bundle, via macOS' own
iconutil.

QT_QPA_PLATFORM=offscreen python make_icns.py <out.icns>
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtGui import QGuiApplication

from screenrec.ui.app_icon import render_icon

# The sizes an .iconset holds, each also at twice the resolution (@2x).
_ICONSET_SIZES = (16, 32, 128, 256, 512)


def write_icns(path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "ScreenRec.iconset"
        iconset.mkdir()
        for size in _ICONSET_SIZES:
            for scale, suffix in ((1, ""), (2, "@2x")):
                png = iconset / f"icon_{size}x{size}{suffix}.png"
                if not render_icon(size * scale).save(str(png), "PNG"):
                    sys.exit(f"could not write {png}")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(path)], check=True)


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)  # QPixmap needs one
    out = Path(sys.argv[1])
    write_icns(out)
    print(f"wrote {out}")
