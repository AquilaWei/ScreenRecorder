"""Integration tests for the recording tray icon. Needs a real Qt GUI, so Windows only."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="needs the Windows desktop")


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path: Path):
    from screenrec.ui.main_window import MainWindow

    window = MainWindow()
    window._output_dir_edit.setText(str(tmp_path))
    # Don't run the real backend: tests drive the start/stop callbacks directly.
    window._run_async = lambda _fn, _on_done: None
    yield window
    window._indicator.close()
    window._tray_icon.hide()
    window.close()


def test_recording_dot_is_red_in_the_middle(app):
    from PySide6.QtGui import QColor

    from screenrec.ui.tray import render_recording_dot

    assert render_recording_dot(16).toImage().pixelColor(8, 8) == QColor("#e53935")


def test_recording_dot_has_transparent_corners(app):
    from screenrec.ui.tray import render_recording_dot

    assert render_recording_dot(16).toImage().pixelColor(0, 0).alpha() == 0


def test_tray_icon_is_hidden_before_recording(window):
    assert not window._tray_icon.isVisible()


def test_tray_icon_is_shown_once_recording_starts(window):
    window._start_recording()
    window._on_start_finished(None, "")
    assert window._tray_icon.isVisible()


def test_tray_icon_is_hidden_once_recording_stops(window):
    window._start_recording()
    window._on_start_finished(None, "")
    window._stop_recording()
    assert not window._tray_icon.isVisible()
