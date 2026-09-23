"""Prevent the system from sleeping / turning off the display while recording.

Needed even for the M1 minimum, not just M3 long-recording robustness: live
testing showed the Desktop Duplication API used for screen capture (`ddagrab`)
hangs indefinitely - no error, no timeout - if the display is already asleep
when capture starts.
"""

from __future__ import annotations

import ctypes
import sys

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


def prevent_sleep() -> None:
    if sys.platform != "win32":
        return
    ctypes.windll.kernel32.SetThreadExecutionState(
        _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED
    )


def allow_sleep() -> None:
    if sys.platform != "win32":
        return
    ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
