"""Linux recording backend: the desktop's screen-cast portal hands over a PipeWire
stream, GStreamer captures it together with system audio, and ffmpeg encodes.

    gst-launch-1.0 (pipewiresrc + pulsesrc -> raw Matroska) --pipe--> ffmpeg -> .mkv

Why this split: Wayland only offers the screen as a PipeWire stream, which
GStreamer reads natively but distribution ffmpeg builds can't. Capturing video
and audio in one GStreamer pipeline also keeps them in sync by construction -
both are timestamped by the same pipeline clock - so none of the Windows
backend's manual alignment (SilencePadder etc.) is needed; a PulseAudio monitor
source keeps delivering (silent) audio even while nothing plays. ffmpeg keeps
doing the encoding, so presets and encoder fallback work as on Windows.

Stopping: SIGINT makes gst-launch (run with -e) send end-of-stream, which
finishes the Matroska stream; ffmpeg then sees EOF and finalizes the file.
"""

from __future__ import annotations

import shutil
import signal
import subprocess
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

from screenrec.presets import get_encoding_params
from screenrec.recorder.controller import Event
from screenrec.recorder.encoders import choose_encoder
from screenrec.recorder.ffmpeg_common import (
    StderrTail,
    encoding_args,
    hardware_device_args,
    upload_filter,
    wait_for_output,
)
from screenrec.recorder.ffmpeg_exe import find_ffmpeg
from screenrec.recorder.spec import AudioSource, CaptureMode, RecordingSpec, validate

if TYPE_CHECKING:  # portal needs jeepney, which only Linux installs
    from screenrec.recorder.portal import ScreenCastPortal, ScreenStream

AUDIO_SAMPLE_RATE = 48_000
AUDIO_CHANNELS = 2
STARTUP_TIMEOUT_SEC = 30
STOP_TIMEOUT_SEC = 15

SLEEP_NOT_INHIBITED_WARNING = "桌面不允許暫停休眠，長時間錄影前請先關閉自動休眠與螢幕關閉"

# PulseAudio's (and pipewire-pulse's) alias for "the monitor of whatever the
# default output is right now" - no need to look the sink up ourselves.
DEFAULT_MONITOR = "@DEFAULT_MONITOR@"

# The video queue absorbs short encoder hiccups. Raw frames are big (~8MB at
# 2880x1800), so the default 10MB byte limit would hold about one frame; limit
# by time instead.
_VIDEO_QUEUE_SEC = 1


def find_gst_launch() -> str:
    """Path of gst-launch-1.0. Raises FileNotFoundError (with install hints for
    the user) if GStreamer's command-line tool isn't installed."""
    path = shutil.which("gst-launch-1.0")
    if path is None:
        raise FileNotFoundError(
            "找不到 gst-launch-1.0，請安裝 GStreamer 與它的 PipeWire、PulseAudio 外掛"
            "（各發行版的套件名稱見 README 的 Requirements）"
        )
    return path


def build_gst_args(pipewire_fd: int, node_id: int, fps: int, with_audio: bool) -> list[str]:
    """gst-launch-1.0 args that write raw video (+ audio) as Matroska to stdout.
    Pure - no subprocess, no I/O."""
    audio = _audio_branch() if with_audio else []
    mux = ["matroskamux", "name=mux", "streamable=true", "!", "fdsink", "fd=1"]
    # -e: turn SIGINT into end-of-stream so the Matroska stream is finished properly.
    return ["-e", "-q", *_video_branch(pipewire_fd, node_id, fps), *audio, *mux]


def _video_branch(pipewire_fd: int, node_id: int, fps: int) -> list[str]:
    return [
        "pipewiresrc",
        f"fd={pipewire_fd}",
        # `path` is deprecated in favour of `target-object`, but that one takes
        # an object serial, and the portal hands out node ids.
        f"path={node_id}",
        "do-timestamp=true",
        # The desktop only sends a frame when the screen changes; resending the
        # last one keeps a still screen from stalling the timeline.
        f"keepalive-time={1000 // fps}",
        # Copy out of PipeWire's buffers so the pipeline never holds the
        # compositor's (possibly GPU) memory while ffmpeg is slow to read.
        "always-copy=true",
        "!",
        "videoconvert",
        "!",
        "videorate",
        "!",
        # I420 is both something matroskamux accepts raw and what the encoder
        # wants anyway (yuv420p).
        f"video/x-raw,format=I420,framerate={fps}/1",
        "!",
        "queue",
        "max-size-buffers=0",
        "max-size-bytes=0",
        f"max-size-time={_VIDEO_QUEUE_SEC * 1_000_000_000}",
        "!",
        "mux.",
    ]


def _audio_branch() -> list[str]:
    return [
        "pulsesrc",
        f"device={DEFAULT_MONITOR}",
        "!",
        f"audio/x-raw,format=S16LE,rate={AUDIO_SAMPLE_RATE},channels={AUDIO_CHANNELS}",
        "!",
        "queue",
        "!",
        "mux.",
    ]


def build_ffmpeg_args(spec: RecordingSpec, video_encoder: str) -> list[str]:
    """ffmpeg args that encode the Matroska stream arriving on stdin to
    `spec.output_path`. Pure - no subprocess, no I/O."""
    validate(spec)
    if spec.target.mode is not CaptureMode.FULL_SCREEN:
        raise NotImplementedError(
            f"{spec.target.mode.value} capture lands in M2, not yet supported"
        )
    params = get_encoding_params(spec.quality, spec.codec)
    args = ["-y", "-hide_banner", "-nostats", *hardware_device_args(video_encoder)]
    args += ["-f", "matroska", "-i", "pipe:0"]
    filters = []
    if params.scale_height is not None:
        filters.append(f"scale=-2:{params.scale_height}")
    upload = upload_filter(video_encoder)
    if upload is not None:  # last: every filter before it works on system memory
        filters.append(upload)
    if filters:
        args += ["-vf", ",".join(filters)]
    has_audio = spec.audio is AudioSource.SYSTEM
    args += encoding_args(params, video_encoder, has_audio, spec.output_path)
    return args


class LinuxBackend:
    """Full-screen recording on Linux (Wayland or X11) - see the module docstring.

    Needs a desktop with xdg-desktop-portal screen casting, PipeWire, and
    gst-launch-1.0 with the pipewiresrc/pulsesrc/matroskamux elements; any of
    them missing surfaces as an exception from `start()`.
    """

    def __init__(self, ffmpeg_path: str | None = None) -> None:
        """`ffmpeg_path` defaults to `find_ffmpeg()`, resolved on first start()
        so a missing ffmpeg is reported as a start error, not a crash."""
        self._ffmpeg_path = ffmpeg_path
        self._gst: subprocess.Popen | None = None
        self._ffmpeg: subprocess.Popen | None = None
        self._gst_log: StderrTail | None = None
        self._ffmpeg_log: StderrTail | None = None
        # Kept across recordings so the desktop can skip its "which screen?"
        # dialog after the first one - see ScreenCastPortal.
        self._portal: ScreenCastPortal | None = None
        self.start_warnings: list[str] = []

    @property
    def ffmpeg_path(self) -> str:
        if self._ffmpeg_path is None:
            self._ffmpeg_path = find_ffmpeg()
        return self._ffmpeg_path

    def start(self, spec: RecordingSpec, on_event: Callable[[Event], None]) -> None:
        """Blocks until recording has started - including while the desktop's
        screen-sharing dialog waits for the user. Raises on any failure."""
        validate(spec)
        if spec.audio not in (AudioSource.NONE, AudioSource.SYSTEM):
            raise NotImplementedError("microphone mixing lands in M2, not yet supported")
        self.start_warnings = []
        try:
            gst_path = find_gst_launch()
            encoder = choose_encoder(spec, self.ffmpeg_path)
            ffmpeg_args = build_ffmpeg_args(spec, encoder)
            stream = self._open_screen()
            gst_args = build_gst_args(
                stream.fd,
                stream.node_id,
                get_encoding_params(spec.quality, spec.codec).fps,
                with_audio=spec.audio is AudioSource.SYSTEM,
            )
            self._launch(gst_path, gst_args, ffmpeg_args, pipewire_fd=stream.fd)
            self._wait_until_writing(spec)
        except Exception:
            self._kill()
            on_event(Event.BACKEND_FAILED)
            raise
        on_event(Event.BACKEND_STARTED)

    def stop(self) -> None:
        """End the recording and wait (up to STOP_TIMEOUT_SEC per process) for
        the file to be finished; past that the processes are killed, which
        still leaves a readable MKV. Does nothing if not recording."""
        if self._gst is None:
            return
        try:
            self._gst.send_signal(signal.SIGINT)  # end-of-stream, see module docstring
            self._gst.wait(timeout=STOP_TIMEOUT_SEC)
            self._ffmpeg.wait(timeout=STOP_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            pass  # _kill() below finishes the job; the MKV stays readable
        self._kill()

    def _open_screen(self) -> ScreenStream:
        from screenrec.recorder.portal import PortalCancelledError, ScreenCastPortal

        if self._portal is None:
            self._portal = ScreenCastPortal()
        try:
            stream = self._portal.start_cast()
        except PortalCancelledError:
            raise
        except Exception as exc:
            raise RuntimeError(f"無法透過 xdg-desktop-portal 取得螢幕畫面：{exc}") from exc
        try:
            self._portal.inhibit_sleep("ScreenRec 錄製中")
        except Exception as exc:  # noqa: BLE001 - recording works without it
            self.start_warnings.append(SLEEP_NOT_INHIBITED_WARNING)
            if sys.stderr is not None:
                print(f"could not inhibit sleep: {exc}", file=sys.stderr)
        return stream

    def _launch(
        self, gst_path: str, gst_args: list[str], ffmpeg_args: list[str], pipewire_fd: int
    ) -> None:
        self._gst = subprocess.Popen(
            [gst_path, *gst_args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(pipewire_fd,),  # referenced as fd=N in the pipeline
        )
        self._ffmpeg = subprocess.Popen(
            [self.ffmpeg_path, *ffmpeg_args],
            stdin=self._gst.stdout,
            stderr=subprocess.PIPE,
        )
        # ffmpeg holds the read end now; keeping ours would stop gst from
        # getting SIGPIPE if ffmpeg dies.
        self._gst.stdout.close()
        self._gst_log = StderrTail(self._gst.stderr, "gst")
        self._ffmpeg_log = StderrTail(self._ffmpeg.stderr, "ffmpeg")

    def _wait_until_writing(self, spec: RecordingSpec) -> None:
        def both_running() -> bool:
            return self._gst.poll() is None and self._ffmpeg.poll() is None

        if not wait_for_output(spec.output_path, both_running, STARTUP_TIMEOUT_SEC):
            details = "\n".join([*self._gst_log.lines, *self._ffmpeg_log.lines][-8:])
            raise RuntimeError("錄製程序未能開始寫入檔案\n" + details)

    def _kill(self) -> None:
        """Stop whatever is still running and end the screen cast."""
        for process in (self._gst, self._ffmpeg):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)
        self._gst = None
        self._ffmpeg = None
        if self._portal is not None:
            self._portal.end_cast()
