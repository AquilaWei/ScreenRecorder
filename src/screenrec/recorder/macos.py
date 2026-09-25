"""macOS recording backend: ScreenCaptureKit hands over screen frames and system
audio, and ffmpeg encodes them.

    SCStream --NV12 frames--> FramePacer --stdin (rawvideo)--> ffmpeg -> .mkv
             --float audio--> SilencePadder --loopback TCP----/

Why this shape: ScreenCaptureKit is the only macOS API that captures system
audio without a virtual audio driver, and it is what Apple wants screen
recorders to use (macOS 15 keeps re-asking permission for the older APIs).
Video and audio buffers carry timestamps from the same host clock, so audio is
aligned to the first video frame by timestamp rather than by arrival time as
on Windows.

ScreenCaptureKit only sends a frame when the screen changes, while ffmpeg
derives rawvideo timestamps from the frame count; FramePacer re-sends the
latest frame so the count keeps up with the clock.

Stopping: the capture is stopped, then ffmpeg's video (stdin) and audio (socket)
inputs are closed; ffmpeg sees EOF on both and finalizes the file.
"""

from __future__ import annotations

import math
import os
import queue
import subprocess
import threading
from array import array
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from screenrec.presets import get_encoding_params
from screenrec.recorder.audio_sync import (
    AUDIO_CHANNELS,
    AUDIO_SAMPLE_RATE,
    AudioSocketSink,
    SilencePadder,
)
from screenrec.recorder.controller import Event
from screenrec.recorder.encoders import choose_encoder
from screenrec.recorder.ffmpeg_common import StderrTail, encoding_args, wait_for_output
from screenrec.recorder.ffmpeg_exe import find_ffmpeg
from screenrec.recorder.spec import AudioSource, CaptureMode, RecordingSpec, validate

if TYPE_CHECKING:  # screencapture needs pyobjc, which only macOS installs
    from screenrec.recorder.screencapture import ScreenCapture

STARTUP_TIMEOUT_SEC = 30
STOP_TIMEOUT_SEC = 15
FIRST_FRAME_TIMEOUT_SEC = 5

# ScreenCaptureKit delivers 32-bit float samples; passing them on as-is avoids
# converting every sample in Python.
AUDIO_BYTES_PER_FRAME = AUDIO_CHANNELS * 4

OWN_WINDOWS_NOT_EXCLUDED_WARNING = "無法把本程式的視窗排除在錄影之外，紅色圓點和主視窗會被錄進去"


@dataclass(frozen=True)
class FrameLayout:
    """Geometry of the NV12 frames ScreenCaptureKit delivers. `stride` is the
    padded row length in pixels (== bytes per luma row), which can exceed
    `width`; ffmpeg reads whole padded rows and crops the padding off."""

    width: int
    height: int
    stride: int


def output_size(native_width: int, native_height: int, scale_height: int | None) -> tuple[int, int]:
    """Frame size to ask ScreenCaptureKit for: the display's pixel size, scaled
    down to the preset's height (never up), keeping the aspect ratio. Both
    even, as 4:2:0 video requires."""
    height = native_height if scale_height is None else min(scale_height, native_height)
    width = round(native_width * height / native_height)
    return width - width % 2, height - height % 2


def frame_layout(
    width: int, height: int, luma_row_bytes: int, chroma_row_bytes: int
) -> FrameLayout:
    """Layout of an NV12 frame from its plane geometry. Raises ValueError for
    planes ffmpeg's rawvideo input couldn't read as one padded frame."""
    if chroma_row_bytes != luma_row_bytes:
        raise ValueError(
            f"NV12 planes with different row lengths ({luma_row_bytes}, {chroma_row_bytes})"
        )
    return FrameLayout(width=width, height=height, stride=luma_row_bytes)


def interleave_f32(left: bytes, right: bytes) -> bytes:
    """Interleave two planar 32-bit float channels into L R L R ... order,
    which is what ffmpeg's f32le input expects."""
    left_samples = array("f", left)
    stereo = array("f", bytes(len(left) * 2))
    stereo[0::2] = left_samples
    stereo[1::2] = array("f", right)
    return stereo.tobytes()


def caffeinate_args(pid: int) -> list[str]:
    """Keep the display and the system awake until process `pid` exits - so a
    crash can't leave the Mac unable to sleep."""
    return ["caffeinate", "-d", "-i", "-w", str(pid)]


def build_ffmpeg_args(
    spec: RecordingSpec, video_encoder: str, layout: FrameLayout, audio_url: str | None
) -> list[str]:
    """ffmpeg args that encode NV12 frames arriving on stdin (and float audio
    from `audio_url`) to `spec.output_path`. Pure - no subprocess, no I/O."""
    validate(spec)
    if spec.target.mode is not CaptureMode.FULL_SCREEN:
        raise NotImplementedError(
            f"{spec.target.mode.value} capture lands in M2, not yet supported"
        )
    params = get_encoding_params(spec.quality, spec.codec)
    args = ["-y", "-hide_banner", "-nostats"]
    args += [
        "-f",
        "rawvideo",
        "-pix_fmt",
        "nv12",
        "-video_size",
        f"{layout.stride}x{layout.height}",
        "-framerate",
        str(params.fps),
        "-i",
        "pipe:0",
    ]
    if audio_url is not None:
        args += [
            "-f",
            "f32le",
            "-ar",
            str(AUDIO_SAMPLE_RATE),
            "-ac",
            str(AUDIO_CHANNELS),
            "-i",
            audio_url,
        ]
    filters = []
    if layout.stride != layout.width:
        filters.append(f"crop={layout.width}:{layout.height}:0:0")
    # The capture is configured for BT.709 in video range; rawvideo carries no
    # colour tags, so state them or players may guess BT.601 and shift colours.
    filters.append("setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709")
    args += ["-vf", ",".join(filters)]
    args += encoding_args(params, video_encoder, audio_url is not None, spec.output_path)
    return args


class FramePacer:
    """Decides how many copies of the latest frame to send so that the frame
    count keeps pace with the clock: frame n covers `first_frame_at + n/fps`.

    All times must come from the capture's clock.
    """

    def __init__(self, fps: int, first_frame_at: float) -> None:
        self._fps = fps
        self._first_frame_at = first_frame_at
        self._sent = 0

    def frames_due(self, now: float) -> int:
        """Frames to send now; counts them as sent."""
        covered = math.floor((now - self._first_frame_at) * self._fps) + 1
        due = max(0, covered - self._sent)
        self._sent += due
        return due

    def next_frame_at(self) -> float:
        return self._first_frame_at + self._sent / self._fps


class LatestFrame:
    """The most recent screen frame, handed from the capture callback to the
    video writer thread.

    A slot instead of a queue: the writer only ever wants the newest frame, and
    a queue would pile up stale ones whenever ffmpeg reads slowly.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._first = threading.Event()
        self._data: bytes | None = None
        self.first_frame_at: float | None = None
        self.layout: FrameLayout | None = None

    def put(self, presented_at: float, layout: FrameLayout, data: bytes) -> None:
        with self._lock:
            self._data = data
        if self.first_frame_at is None:
            self.layout = layout
            self.first_frame_at = presented_at
            self._first.set()

    def get(self) -> bytes:
        with self._lock:
            return self._data

    def wait_first(self, timeout: float) -> bool:
        return self._first.wait(timeout)


class VideoWriter:
    """Writes paced frames to ffmpeg's stdin on its own thread until stopped
    or ffmpeg stops reading."""

    def __init__(self, frames: LatestFrame, fps: int, clock: Callable[[], float], stdin) -> None:
        self._frames = frames
        self._pacer = FramePacer(fps, frames.first_frame_at)
        self._clock = clock
        self._stdin = stdin
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=STOP_TIMEOUT_SEC)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            data = self._frames.get()
            try:
                for _ in range(self._pacer.frames_due(self._clock())):
                    self._stdin.write(data)  # blocks while ffmpeg is busy encoding
            except (BrokenPipeError, OSError):
                return  # ffmpeg already exited
            self._stop_event.wait(max(0.0, self._pacer.next_frame_at() - self._clock()))


class AudioWriter:
    """Writes captured audio to `sink`, aligned to the first video frame and
    with silent gaps filled, on its own thread. The capture callback only
    queues (see `on_audio`), so a slow sink never stalls the capture."""

    def __init__(self, sink, clock: Callable[[], float]) -> None:
        self._sink = sink
        self._clock = clock
        self._queue: queue.Queue[tuple[float, bytes]] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def on_audio(self, presented_at: float, data: bytes) -> None:
        """Interleaved float samples starting at `presented_at`. Called on the
        capture's thread - must return quickly, so it only queues."""
        ends_at = presented_at + len(data) / AUDIO_BYTES_PER_FRAME / AUDIO_SAMPLE_RATE
        self._queue.put((ends_at, data))

    def start(self, timeline_start: float) -> None:
        self._thread = threading.Thread(target=self._run, args=(timeline_start,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Flush queued audio, then stop."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self, timeline_start: float) -> None:
        padder = SilencePadder(timeline_start, bytes_per_frame=AUDIO_BYTES_PER_FRAME)
        while True:
            try:
                ends_at, data = self._queue.get(timeout=0.02)
                data = padder.on_data(ends_at, data)
            except queue.Empty:
                if self._stop_event.is_set():
                    return  # queue fully flushed
                data = padder.on_idle(self._clock())
                if data is None:
                    continue
            if not data:
                continue
            try:
                self._sink.write(data)
            except OSError:
                return  # ffmpeg already exited


class MacBackend:
    """Full-screen recording on macOS 13+ - see the module docstring.

    Needs the Screen Recording permission (System Settings > Privacy &
    Security); without it `start()` asks macOS to prompt for it and raises.
    """

    def __init__(self, ffmpeg_path: str | None = None) -> None:
        """`ffmpeg_path` defaults to `find_ffmpeg()`, resolved on first start()
        so a missing ffmpeg is reported as a start error, not a crash."""
        self._ffmpeg_path = ffmpeg_path
        self._capture: ScreenCapture | None = None
        self._ffmpeg: subprocess.Popen | None = None
        self._ffmpeg_log: StderrTail | None = None
        self._caffeinate: subprocess.Popen | None = None
        self._video_writer: VideoWriter | None = None
        self._audio_writer: AudioWriter | None = None
        self._audio_sink: AudioSocketSink | None = None
        self.start_warnings: list[str] = []

    @property
    def ffmpeg_path(self) -> str:
        if self._ffmpeg_path is None:
            self._ffmpeg_path = find_ffmpeg()
        return self._ffmpeg_path

    def start(self, spec: RecordingSpec, on_event: Callable[[Event], None]) -> None:
        """Blocks until ffmpeg is writing the file. Raises on any failure."""
        validate(spec)
        if spec.audio not in (AudioSource.NONE, AudioSource.SYSTEM):
            raise NotImplementedError("microphone mixing lands in M2, not yet supported")
        self.start_warnings = []
        try:
            self._start(spec)
        except Exception:
            self._kill()
            on_event(Event.BACKEND_FAILED)
            raise
        on_event(Event.BACKEND_STARTED)

    def stop(self) -> None:
        """End the recording and wait (up to STOP_TIMEOUT_SEC) for ffmpeg to
        finish the file; past that it's killed, which still leaves a readable
        MKV. Does nothing if not recording."""
        if self._ffmpeg is None:
            return
        self._capture.stop()
        self._video_writer.stop()
        self._ffmpeg.stdin.close()  # video EOF
        if self._audio_writer is not None:
            self._audio_writer.stop()
            self._audio_sink.close()  # audio EOF
        try:
            self._ffmpeg.wait(timeout=STOP_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            pass  # _kill() below finishes the job; the MKV stays readable
        self._kill()

    def _start(self, spec: RecordingSpec) -> None:
        from screenrec.recorder.screencapture import ScreenCapture, host_clock

        params = get_encoding_params(spec.quality, spec.codec)
        encoder = choose_encoder(spec, self.ffmpeg_path)
        self._caffeinate = subprocess.Popen(caffeinate_args(os.getpid()))

        frames = LatestFrame()
        with_audio = spec.audio is AudioSource.SYSTEM
        if with_audio:
            self._audio_sink = AudioSocketSink()
            self._audio_writer = AudioWriter(self._audio_sink, host_clock)
        self._capture = ScreenCapture(
            on_video=frames.put,
            on_audio=self._audio_writer.on_audio if with_audio else None,
        )
        own_windows_excluded = self._capture.start(
            display_index=spec.target.monitor_index,
            scale_height=params.scale_height,
            fps=params.fps,
        )
        if not own_windows_excluded:
            self.start_warnings.append(OWN_WINDOWS_NOT_EXCLUDED_WARNING)
        if not frames.wait_first(FIRST_FRAME_TIMEOUT_SEC):
            raise RuntimeError("螢幕沒有送出畫面，請確認螢幕沒有鎖定或休眠")

        args = build_ffmpeg_args(
            spec,
            encoder,
            frames.layout,
            audio_url=self._audio_sink.url if self._audio_sink else None,
        )
        self._ffmpeg = subprocess.Popen(
            [self.ffmpeg_path, *args], stdin=subprocess.PIPE, stderr=subprocess.PIPE
        )
        self._ffmpeg_log = StderrTail(self._ffmpeg.stderr, "ffmpeg")
        # ffmpeg reads some video before it opens the audio input, so frames
        # have to flow before it can start.
        self._video_writer = VideoWriter(frames, params.fps, host_clock, self._ffmpeg.stdin)
        self._video_writer.start()
        if self._audio_writer is not None:
            self._audio_writer.start(timeline_start=frames.first_frame_at)

        if not wait_for_output(
            spec.output_path, lambda: self._ffmpeg.poll() is None, STARTUP_TIMEOUT_SEC
        ):
            details = "\n".join(list(self._ffmpeg_log.lines)[-8:])
            raise RuntimeError("ffmpeg 未能開始錄製（沒有產生輸出檔）\n" + details)

    def _kill(self) -> None:
        """Stop whatever is still running."""
        if self._capture is not None:
            self._capture.stop()
        if self._video_writer is not None:
            self._video_writer.stop()
        if self._audio_writer is not None:
            self._audio_writer.stop()
        if self._audio_sink is not None:
            self._audio_sink.close()
        for process in (self._ffmpeg, self._caffeinate):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)
        self._capture = None
        self._ffmpeg = None
        self._caffeinate = None
        self._video_writer = None
        self._audio_writer = None
        self._audio_sink = None
