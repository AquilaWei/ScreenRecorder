# PyInstaller spec - build with packaging/build.ps1, not directly.
# One-folder (not one-file) build: starts faster, and ffmpeg sits next to it.

from pathlib import Path

HERE = Path(SPECPATH)
ROOT = HERE.parent

a = Analysis(
    [str(HERE / "launcher.py")],
    pathex=[str(ROOT / "src")],
    hiddenimports=["pyaudiowpatch"],
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
    icon=str(HERE / "screenrec.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="ScreenRec")
