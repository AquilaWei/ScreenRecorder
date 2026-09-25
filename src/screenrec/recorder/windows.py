"""Windows recording backend: ddagrab (Desktop Duplication) screen capture through
ffmpeg, with system audio (WASAPI loopback) fed to ffmpeg over a loopback TCP
connection.

ffmpeg is stopped gracefully by writing "q" to its stdin. Audio deliberately
doesn't use stdin: it used to, which forced stopping via CTRL_BREAK_EVENT - and
that only works when this process has a console, which the packaged windowed
app doesn't.
"""

from __future__ import annotations

import queue
import re
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable

from screenrec import power
from screenrec.presets import get_encoding_params
from screenrec.recorder.audio_sync import (
    AUDIO_CHANNELS,
    AUDIO_SAMPLE_RATE,
    AudioSocketSink,
    SilencePadder,
)
from screenrec.recorder.controller import Event
from screenrec.recorder.encoders import choose_encoder
from screenrec.recorder.ffmpeg_common import encoding_args, wait_for_output
from screenrec.recorder.ffmpeg_exe import NO_WINDOW, find_ffmpeg
from screenrec.recorder.spec import AudioSource, CaptureMode, RecordingSpec, validate

STARTUP_TIMEOUT_SEC = 30

# Clock for every audio/video alignment timestamp - all of them must come from
# this one clock. Not time.monotonic(): before Python 3.13 on Windows that's
# GetTickCount64 with 15.6ms resolution, coarse enough to misplace whole audio
# chunks relative to the first video frame (found in CI on Python 3.12).
audio_clock = time.perf_counter


def build_ffmpeg_args(spec: RecordingSpec, video_encoder: str, audio_url: str | None) -> list[str]:
    """Assemble the ffmpeg CLI args for `spec`. Pure - no subprocess, no I/O."""
    validate(spec)
    target = spec.target
    if target.mode is not CaptureMode.FULL_SCREEN:
        raise NotImplementedError(f"{target.mode.value} capture lands in M2, not yet supported")

    params = get_encoding_params(spec.quality, spec.codec)

    # -nostats: stderr is parsed line by line (see FfmpegLogReader), and the
    # CR-terminated progress updates would glue themselves onto real log lines.
    args = ["-y", "-hide_banner", "-nostats"]

    # NOTE: "," separates filters in an lavfi chain; ":" separates options within
    # one filter. ddagrab's own options (output_idx, framerate) must use ":".
    # showinfo logs each captured frame; the first one tells us when the video
    # timeline's t=0 was actually captured, so audio can be aligned to it.
    video_filter = (
        f"ddagrab=output_idx={target.monitor_index}:framerate={params.fps},"
        "hwdownload,format=bgra,showinfo=checksum=0"
    )
    if params.scale_height is not None:
        video_filter += f",scale=-2:{params.scale_height}"
    args += ["-f", "lavfi", "-i", video_filter]

    if audio_url is not None:
        args += [
            "-f",
            "s16le",
            "-ar",
            str(AUDIO_SAMPLE_RATE),
            "-ac",
            str(AUDIO_CHANNELS),
            "-i",
            audio_url,
        ]

    args += encoding_args(params, video_encoder, audio_url is not None, spec.output_path)
    return args


FIRST_FRAME_TIMEOUT_SEC = 5

_FIRST_FRAME_LINE = re.compile(rb"Parsed_showinfo.*\sn:\s*0\s")


def is_first_frame_line(line: bytes) -> bool:
    """True for showinfo's log line about the first captured video frame."""
    return _FIRST_FRAME_LINE.search(line) is not None


class FfmpegLogReader:
    """Drains ffmpeg's stderr (ffmpeg would block once the pipe fills), notes
    when the first video frame was captured, and keeps the last few log lines
    for error messages. Other lines are echoed to our own stderr for debugging.
    """

    def __init__(self, stream) -> None:
        self._stream = stream
        self._first_frame = threading.Event()
        self.first_frame_at: float | None = None
        self.tail: deque[str] = deque(maxlen=10)
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def wait_first_frame(self, timeout: float) -> float | None:
        self._first_frame.wait(timeout)
        return self.first_frame_at

    def _run(self) -> None:
        for line in self._stream:
            if b"Parsed_showinfo" in line:
                if self.first_frame_at is None and is_first_frame_line(line):
                    self.first_frame_at = audio_clock()
                    self._first_frame.set()
                continue
            text = line.decode("utf-8", errors="replace").rstrip()
            self.tail.append(text)
            if sys.stderr is not None:
                print(text, file=sys.stderr)


class WasapiLoopbackCapture:
    """Captures the default output device's loopback stream and writes raw PCM
    frames to `sink` (anything with `write(bytes)` - an AudioSocketSink).

    Capture and writing are decoupled: PortAudio's callback only queues audio,
    and a separate thread writes the queue to `sink`. Reading and writing on one
    thread lost audio whenever the write blocked (ffmpeg not reading its audio
    input yet, e.g. during startup): the device buffer overflowed and samples were
    silently dropped - found live as audio drifting ~250ms ahead of video within
    the first few seconds of a recording.

    Opening the device happens synchronously in `start()`: if there's no
    accessible default output device, the caller finds out immediately (and can
    abort/clean up ffmpeg) instead of ffmpeg sitting forever waiting for audio.
    """

    def __init__(self, sink, timeline_start: Callable[[], float]) -> None:
        """`timeline_start` blocks until the video timeline's t=0 is known and
        returns it (`audio_clock` time)."""
        self._sink = sink
        self._timeline_start = timeline_start
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._queue: queue.Queue[tuple[float, bytes]] = queue.Queue()
        self._audio = None
        self._stream = None

    def start(self) -> None:
        import pyaudiowpatch as pyaudio

        chunk_frames = AUDIO_SAMPLE_RATE // 20
        self._audio = pyaudio.PyAudio()
        try:
            default_speakers = self._audio.get_default_wasapi_loopback()
            self._stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=AUDIO_CHANNELS,
                rate=AUDIO_SAMPLE_RATE,
                frames_per_buffer=chunk_frames,
                input=True,
                input_device_index=default_speakers["index"],
                stream_callback=self.on_audio,
            )
        except Exception:
            self._audio.terminate()
            self._audio = None
            raise

        self._thread = threading.Thread(target=self._run, args=(chunk_frames,), daemon=True)
        self._thread.start()

    def on_audio(self, in_data, frame_count, time_info, status):
        """PortAudio callback - must return quickly, so it only queues."""
        self._queue.put((audio_clock(), in_data))
        return (None, 0)  # 0 == paContinue

    def stop(self) -> bool:
        """Flush queued audio, then stop. Returns False if the writer thread
        didn't exit (blocked writing to a sink nobody is reading)."""
        if self._stream is not None:
            self._stream.stop_stream()
        self._stop_event.set()
        exited = True
        if self._thread is not None:
            self._thread.join(timeout=5)
            exited = not self._thread.is_alive()
        if self._stream is not None:
            self._stream.close()
        if self._audio is not None:
            self._audio.terminate()
        return exited

    def _run(self, chunk_frames: int) -> None:
        poll_interval = chunk_frames / AUDIO_SAMPLE_RATE / 4
        padder = SilencePadder(timeline_start=self._timeline_start())
        while True:
            try:
                arrived_at, data = self._queue.get(timeout=poll_interval)
                data = padder.on_data(arrived_at, data)
            except queue.Empty:
                if self._stop_event.is_set():
                    return  # queue fully flushed
                data = padder.on_idle(audio_clock())
                if data is None:
                    continue
            if not data:
                continue
            try:
                self._sink.write(data)
            except (BrokenPipeError, OSError):
                return  # ffmpeg already exited


class WindowsBackend:
    def __init__(self, ffmpeg_path: str | None = None) -> None:
        """`ffmpeg_path` defaults to `find_ffmpeg()`, resolved on first start()
        so a missing ffmpeg is reported as a start error, not a crash."""
        self._ffmpeg_path = ffmpeg_path
        self._process: subprocess.Popen | None = None
        self._audio_capture: WasapiLoopbackCapture | None = None
        self._audio_sink: AudioSocketSink | None = None
        self.start_warnings: list[str] = []  # none so far on Windows

    def start(self, spec: RecordingSpec, on_event: Callable[[Event], None]) -> None:
        validate(spec)
        if spec.audio not in (AudioSource.NONE, AudioSource.SYSTEM):
            raise NotImplementedError("microphone mixing lands in M2, not yet supported")

        if self._ffmpeg_path is None:
            self._ffmpeg_path = find_ffmpeg()
        power.prevent_sleep()
        try:
            encoder = choose_encoder(spec, self._ffmpeg_path)
            if spec.audio is AudioSource.SYSTEM:
                self._audio_sink = AudioSocketSink()
            args = build_ffmpeg_args(
                spec, encoder, audio_url=self._audio_sink.url if self._audio_sink else None
            )
            self._process = subprocess.Popen(
                [self._ffmpeg_path, *args],
                stdin=subprocess.PIPE,  # for the "q" stop command
                stderr=subprocess.PIPE,
                creationflags=NO_WINDOW,
            )
            log = FfmpegLogReader(self._process.stderr)
            log.start()
            if self._audio_sink is not None:
                self._audio_capture = WasapiLoopbackCapture(
                    self._audio_sink,
                    timeline_start=lambda: (
                        log.wait_first_frame(FIRST_FRAME_TIMEOUT_SEC) or audio_clock()
                    ),
                )
                self._audio_capture.start()
            if not wait_for_output(
                spec.output_path, lambda: self._process.poll() is None, STARTUP_TIMEOUT_SEC
            ):
                details = "\n".join(list(log.tail)[-5:])
                raise RuntimeError(
                    "ffmpeg 未能開始錄製（沒有產生輸出檔），請確認螢幕沒有鎖定或休眠\n" + details
                )
        except Exception:
            # ffmpeg may already be running (e.g. it started fine but the audio
            # device failed to open) - without this it'd sit forever waiting for
            # audio that will never arrive.
            if self._process is not None and self._process.poll() is None:
                self._process.kill()
                self._process.wait(timeout=5)
            if self._audio_sink is not None:
                self._audio_sink.close()
                self._audio_sink = None
            if self._audio_capture is not None:
                self._audio_capture.stop()
                self._audio_capture = None
            power.allow_sleep()
            on_event(Event.BACKEND_FAILED)
            raise
        else:
            on_event(Event.BACKEND_STARTED)

    @property
    def ffmpeg_path(self) -> str:
        if self._ffmpeg_path is None:
            self._ffmpeg_path = find_ffmpeg()
        return self._ffmpeg_path

    def stop(self) -> None:
        if self._process is None:
            return
        power.allow_sleep()
        if self._audio_capture is not None:
            self._audio_capture.stop()  # flushes queued audio first
        if self._audio_sink is not None:
            self._audio_sink.close()  # audio EOF for ffmpeg
        try:
            self._process.stdin.write(b"q")
            self._process.stdin.flush()
            self._process.stdin.close()
        except OSError:
            pass  # ffmpeg already exited
        try:
            self._process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=5)
