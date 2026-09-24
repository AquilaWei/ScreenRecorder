"""Shared interface every platform recording backend implements."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from screenrec.recorder.spec import RecordingSpec


class Backend(Protocol):
    # Problems that didn't keep the last start() from recording but the user
    # should hear about (e.g. the machine may fall asleep). Reset by each start().
    start_warnings: list[str]

    def start(self, spec: RecordingSpec, on_event: Callable[[object], None]) -> None:
        """Launch the recording subprocess for `spec`.

        Non-blocking; reports progress and terminal outcomes by calling `on_event`
        with a `controller` event (BACKEND_STARTED / BACKEND_FAILED / BACKEND_STOPPED).
        """

    def stop(self) -> None:
        """Ask the running subprocess to end gracefully and finish writing the output file."""
