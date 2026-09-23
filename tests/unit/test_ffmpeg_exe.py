import sys

import pytest

from screenrec.recorder import ffmpeg_exe


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("SCREENREC_FFMPEG", r"C:\custom\ffmpeg.exe")
    assert ffmpeg_exe.find_ffmpeg() == r"C:\custom\ffmpeg.exe"


def test_bundled_copy_next_to_the_frozen_exe_is_preferred_over_path(monkeypatch, tmp_path):
    bundled = tmp_path / "ffmpeg" / ffmpeg_exe._EXE_NAME
    bundled.parent.mkdir()
    bundled.write_bytes(b"")
    monkeypatch.delenv("SCREENREC_FFMPEG", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ScreenRec.exe"))
    monkeypatch.setattr(ffmpeg_exe.shutil, "which", lambda _name: r"C:\on\path\ffmpeg.exe")
    assert ffmpeg_exe.find_ffmpeg() == str(bundled)


def test_falls_back_to_path_when_not_frozen(monkeypatch):
    monkeypatch.delenv("SCREENREC_FFMPEG", raising=False)
    monkeypatch.setattr(ffmpeg_exe.shutil, "which", lambda _name: r"C:\on\path\ffmpeg.exe")
    assert ffmpeg_exe.find_ffmpeg() == r"C:\on\path\ffmpeg.exe"


def test_missing_ffmpeg_raises_a_readable_error(monkeypatch):
    monkeypatch.delenv("SCREENREC_FFMPEG", raising=False)
    monkeypatch.setattr(ffmpeg_exe.shutil, "which", lambda _name: None)
    with pytest.raises(FileNotFoundError):
        ffmpeg_exe.find_ffmpeg()
