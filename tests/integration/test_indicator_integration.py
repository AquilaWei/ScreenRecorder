"""Integration test against the real Windows window manager. Skipped elsewhere."""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="needs the Windows DWM")


def test_indicator_is_excluded_from_screen_capture():
    # Regression test: built with WA_TranslucentBackground, the indicator was a
    # per-pixel-alpha layered window, SetWindowDisplayAffinity failed on it
    # (ERROR_NOT_ENOUGH_MEMORY), and the circle showed up in real recordings.
    from PySide6.QtWidgets import QApplication

    from screenrec.ui.indicator import RecordingIndicator

    app = QApplication.instance() or QApplication([])
    indicator = RecordingIndicator()
    indicator.show()
    app.processEvents()
    excluded = indicator.excluded_from_capture
    indicator.close()
    assert excluded
