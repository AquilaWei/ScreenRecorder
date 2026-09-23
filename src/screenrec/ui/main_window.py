"""M1 minimal GUI: start/stop, quality preset, save location, red-circle indicator."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from screenrec.recorder.controller import Event, RecordingController, State
from screenrec.recorder.finalize import remux_to_mp4
from screenrec.recorder.spec import (
    AudioSource,
    CaptureMode,
    CaptureTarget,
    QualityPreset,
    RecordingSpec,
    VideoCodec,
)
from screenrec.recorder.windows import WindowsBackend
from screenrec.storage import default_filename
from screenrec.ui.indicator import RecordingIndicator


class _CallableWorker(QObject):
    """Runs `fn` on a background thread and reports its outcome back via a
    queued signal (thread-safe by Qt's design: `finished` is connected to a
    slot on the main-thread object, so Qt marshals the call there).

    Needed because backend.start()/stop() and the post-stop MP4 remux all do
    blocking subprocess I/O - calling them directly from a button handler
    freezes the whole window for as long as ffmpeg takes to respond (found
    live: stopping a recording could leave "停止錄製" apparently unresponsive
    for several seconds).
    """

    finished = Signal(object, str)  # (result, error_message); error_message == "" on success

    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 - reported to the caller, not swallowed
            self.finished.emit(None, str(exc))
        else:
            self.finished.emit(result, "")


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ScreenRec")

        self._backend = WindowsBackend()
        self._controller = RecordingController()
        self._indicator = RecordingIndicator()
        self._pending_spec: RecordingSpec | None = None
        self._active_thread: QThread | None = None
        self._active_worker: _CallableWorker | None = None

        self._quality_combo = QComboBox()
        for preset in QualityPreset:
            self._quality_combo.addItem(preset.value, preset)
        self._quality_combo.setCurrentIndex(list(QualityPreset).index(QualityPreset.STANDARD))

        self._output_dir_edit = QLineEdit(str(Path.home() / "Videos"))
        browse_button = QPushButton("瀏覽…")
        browse_button.clicked.connect(self._browse_output_dir)

        self._system_audio_checkbox = QCheckBox("錄製系統聲音")
        self._system_audio_checkbox.setChecked(True)

        self._start_stop_button = QPushButton("開始錄製")
        self._start_stop_button.clicked.connect(self._on_start_stop_clicked)

        self._status_label = QLabel("待機")

        output_row = QHBoxLayout()
        output_row.addWidget(self._output_dir_edit)
        output_row.addWidget(browse_button)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("品質預設"))
        layout.addWidget(self._quality_combo)
        layout.addWidget(QLabel("儲存位置"))
        layout.addLayout(output_row)
        layout.addWidget(self._system_audio_checkbox)
        layout.addWidget(self._start_stop_button)
        layout.addWidget(self._status_label)
        self.setLayout(layout)

    def _browse_output_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "選擇儲存位置", self._output_dir_edit.text()
        )
        if chosen:
            self._output_dir_edit.setText(chosen)

    def _on_start_stop_clicked(self) -> None:
        if self._controller.state is State.IDLE:
            self._start_recording()
        elif self._controller.state is State.RECORDING:
            self._stop_recording()

    def _build_spec(self) -> RecordingSpec:
        output_dir = Path(self._output_dir_edit.text())
        output_dir.mkdir(parents=True, exist_ok=True)
        return RecordingSpec(
            target=CaptureTarget(mode=CaptureMode.FULL_SCREEN, monitor_index=0),
            quality=self._quality_combo.currentData(),
            codec=VideoCodec.H264,
            audio=AudioSource.SYSTEM
            if self._system_audio_checkbox.isChecked()
            else AudioSource.NONE,
            output_path=output_dir / default_filename(),
        )

    def _run_async(self, fn: Callable[[], Any], on_done: Callable[[Any, str], None]) -> None:
        thread = QThread(self)
        worker = _CallableWorker(fn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(on_done)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        # Keep references alive until the thread finishes - nothing else holds them.
        self._active_thread = thread
        self._active_worker = worker
        thread.start()

    def _start_recording(self) -> None:
        spec = self._build_spec()
        self._pending_spec = spec
        self._controller.handle(Event.START_REQUESTED)
        self._start_stop_button.setEnabled(False)
        self._status_label.setText("啟動中…")

        backend = self._backend
        self._run_async(lambda: backend.start(spec, lambda _event: None), self._on_start_finished)

    def _on_start_finished(self, _result: object, error_message: str) -> None:
        self._start_stop_button.setEnabled(True)
        if error_message:
            # backend.start() already moved the controller STARTING -> ERROR
            # via its own on_event callback before raising; here it's a no-op
            # callback, so drive that transition explicitly instead.
            self._controller.handle(Event.BACKEND_FAILED)
            self._controller.handle(Event.RESET)
            self._status_label.setText("待機")
            QMessageBox.critical(self, "無法開始錄製", error_message)
            return
        self._controller.handle(Event.BACKEND_STARTED)

        primary_screen = QGuiApplication.primaryScreen()
        if primary_screen is not None:
            geometry = primary_screen.geometry()
            self._indicator.move(geometry.right() - 40, geometry.top() + 16)
        self._indicator.show()

        self._start_stop_button.setText("停止錄製")
        self._status_label.setText(f"錄製中：{self._pending_spec.output_path.name}")

    def _stop_recording(self) -> None:
        self._controller.handle(Event.STOP_REQUESTED)
        self._start_stop_button.setEnabled(False)
        self._status_label.setText("停止中…")
        self._indicator.hide()

        self._run_async(self._stop_and_finalize, self._on_stop_finished)

    def _stop_and_finalize(self) -> tuple[str, str]:
        """Runs on the background thread: stop ffmpeg, then remux to MP4.

        Returns (final_path, warning) - `warning` is set (not raised) when the
        remux fails, since that's recoverable (the MKV is kept) and shouldn't
        be reported the same way as stop() itself failing.
        """
        self._backend.stop()
        spec = self._pending_spec
        if spec.keep_mkv:
            return str(spec.output_path), ""
        try:
            mp4_path = remux_to_mp4(spec.output_path, self._backend.ffmpeg_path)
        except Exception as exc:  # noqa: BLE001 - reported to the user, MKV is kept
            return str(spec.output_path), f"轉封裝失敗，已保留 MKV：{exc}"
        spec.output_path.unlink(missing_ok=True)
        return str(mp4_path), ""

    def _on_stop_finished(self, result: object, error_message: str) -> None:
        self._controller.handle(Event.BACKEND_STOPPED)
        self._controller.handle(Event.FINALIZE_DONE)
        self._start_stop_button.setEnabled(True)
        self._start_stop_button.setText("開始錄製")

        if error_message:
            self._status_label.setText("待機")
            QMessageBox.critical(self, "停止錄製失敗", error_message)
            return
        final_path, warning = result
        if warning:
            QMessageBox.warning(self, "轉封裝失敗，已保留 MKV", warning)
        self._status_label.setText(f"已儲存：{Path(final_path).name}")
