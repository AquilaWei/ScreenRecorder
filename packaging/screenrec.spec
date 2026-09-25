# PyInstaller spec - build with packaging/build.ps1 (Windows) or
# packaging/macos/build.sh (macOS), not directly.
# One-folder (not one-file) build: starts faster, and ffmpeg sits next to it.

import sys
import tomllib
from pathlib import Path

HERE = Path(SPECPATH)
ROOT = HERE.parent
MACOS = sys.platform == "darwin"

a = Analysis(
    [str(HERE / "launcher.py")],
    pathex=[str(ROOT / "src")],
    # Imported only inside functions, so the analysis can't see them.
    hiddenimports=["screenrec.recorder.screencapture"] if MACOS else ["pyaudiowpatch"],
    excludes=["tkinter", "unittest", "pytest"],
    noarchive=False,
)

# Qt pieces a plain widgets app never loads (~40MB): software OpenGL fallback,
# PDF, QML/Quick, virtual keyboard, and non-Chinese translations.
_UNUSED_PREFIXES = (
    "opengl32sw",
    "Qt6Pdf",
    "qpdf",
    "Qt6Quick",
    "Qt6Qml",
    "Qt6VirtualKeyboard",
    "qtvirtualkeyboard",
)


def _needed(entry):
    path = entry[0].replace("\\", "/")
    name = path.rsplit("/", 1)[-1]
    if name.startswith(_UNUSED_PREFIXES):
        return False
    if "/translations/" in path and "zh_TW" not in name:
        return False
    return True


a.binaries = [entry for entry in a.binaries if _needed(entry)]
a.datas = [entry for entry in a.datas if _needed(entry)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ScreenRec",
    console=False,
    icon=str(HERE / ("screenrec.icns" if MACOS else "screenrec.ico")),
)
coll = COLLECT(exe, a.binaries, a.datas, name="ScreenRec")

if MACOS:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    app = BUNDLE(
        coll,
        name="ScreenRec.app",
        icon=str(HERE / "screenrec.icns"),
        bundle_identifier="io.github.AquilaWei.ScreenRecorder",
        info_plist={
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            # ScreenCaptureKit with system audio needs macOS 13.
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.video",
        },
    )
