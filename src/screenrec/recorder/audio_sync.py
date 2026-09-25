"""Feeding captured system audio to ffmpeg in sync with the video: silence
padding against a shared clock, and the loopback socket ffmpeg reads it from.

Used by backends whose audio arrives separately from the video (Windows'
WASAPI loopback, macOS' ScreenCaptureKit). Linux doesn't need it: GStreamer
captures both in one pipeline.
"""

from __future__ import annotations

import socket

AUDIO_SAMPLE_RATE = 48_000
AUDIO_CHANNELS = 2
BYTES_PER_FRAME = AUDIO_CHANNELS * 2  # 16-bit samples; macOS passes its own (32-bit float)
STARTUP_TIMEOUT_SEC = 30


def silence_chunk(chunk_frames: int, bytes_per_frame: int = BYTES_PER_FRAME) -> bytes:
    """`chunk_frames` frames of digital silence. All-zero bytes are silence in
    both 16-bit integer and 32-bit float PCM."""
    return b"\x00" * (chunk_frames * bytes_per_frame)


class SilencePadder:
    """Keeps a loopback audio stream paced with wall-clock time.

    WASAPI loopback delivers no frames at all while nothing is rendering (e.g. a
    quiet gap between sentences in a lecture), so the gap has to be filled with
    silence or the audio track falls behind the video. Two things make that
    subtle, both found live:

    - Delivery jitter: frames normally arrive every ~50ms but sometimes 53ms
      apart. Padding on "no data for one period" inserted silence *between real
      chunks*, stretching audio ~3% (drifting ~0.9s late over 30s). So padding
      only starts after `grace` of true silence.
    - Silence-to-sound transitions: the padding must end exactly where the
      resumed real audio begins, or every pause shifts audio a little further
      out of sync. `on_data` tops up or trims to make them line up.

    The same mechanism aligns the start: the audio timeline begins at
    `timeline_start` (when the first video frame was captured), treated as the
    start of a silent gap - audio captured earlier is trimmed, and a late audio
    start is preceded by silence. Without this, audio played ~100ms late,
    because capture starts before ffmpeg grabs its first frame (measured live:
    the offset moved 1:1 with an artificial audio start delay).

    All times passed in must come from the same clock as `timeline_start`.
    """

    def __init__(
        self,
        timeline_start: float,
        grace: float = 0.2,
        min_pad: float = 0.05,
        bytes_per_frame: int = BYTES_PER_FRAME,
    ) -> None:
        self._grace = grace
        self._min_pad_frames = int(min_pad * AUDIO_SAMPLE_RATE)
        self._bytes_per_frame = bytes_per_frame
        self._last_real = timeline_start
        # "covered up to" time while in a silent gap; None while audio flows
        self._padded_until: float | None = timeline_start

    def on_data(self, arrived_at: float, data: bytes) -> bytes:
        """Real audio ending at `arrived_at` arrived; returns what to write
        (possibly adjusted)."""
        if self._padded_until is not None:
            starts_at = arrived_at - len(data) / self._bytes_per_frame / AUDIO_SAMPLE_RATE
            gap_frames = round((starts_at - self._padded_until) * AUDIO_SAMPLE_RATE)
            if gap_frames > 0:
                data = silence_chunk(gap_frames, self._bytes_per_frame) + data
            elif gap_frames < 0:
                if -gap_frames * self._bytes_per_frame >= len(data):
                    return b""  # entirely before what's already covered
                data = data[-gap_frames * self._bytes_per_frame :]
            self._padded_until = None
        self._last_real = arrived_at
        return data

    def on_idle(self, now: float) -> bytes | None:
        """No real audio right now; returns silence to write, if due."""
        if self._padded_until is None:
            if now - self._last_real < self._grace:
                return None
            self._padded_until = self._last_real
        frames = int((now - self._padded_until) * AUDIO_SAMPLE_RATE)
        if frames < self._min_pad_frames:
            return None
        self._padded_until += frames / AUDIO_SAMPLE_RATE
        return silence_chunk(frames, self._bytes_per_frame)


class AudioSocketSink:
    """A loopback TCP server ffmpeg connects to for its raw audio input.

    Behaves like a writable file for the audio writer thread: the first write
    waits for ffmpeg to connect. Closing it gives ffmpeg audio EOF, and also
    unblocks a write stuck on an ffmpeg that stopped reading.
    """

    def __init__(self, accept_timeout: float = STARTUP_TIMEOUT_SEC) -> None:
        self._server = socket.create_server(("127.0.0.1", 0))
        self._server.settimeout(accept_timeout)
        self._conn: socket.socket | None = None
        self._closed = False
        port = self._server.getsockname()[1]
        self.url = f"tcp://127.0.0.1:{port}"

    def write(self, data: bytes) -> None:
        if self._conn is None:
            if self._closed:
                raise OSError("audio sink closed")
            conn, _ = self._server.accept()
            conn.settimeout(None)
            self._conn = conn
        self._conn.sendall(data)

    def close(self) -> None:
        self._closed = True
        if self._conn is not None:
            try:
                self._conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # ffmpeg already gone
            self._conn.close()
        self._server.close()
