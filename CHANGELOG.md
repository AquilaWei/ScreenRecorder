# Changelog

## Unreleased

- **New**: Linux records with the graphics card's own encoder (VAAPI) on Intel
  and AMD GPUs, instead of falling back to the much slower software encoding.
  Quick Sync and NVIDIA are still preferred where they work
- **New (test version)**: a Flatpak for Linux. It carries its own FFmpeg (with
  x264), GStreamer and Qt, so it installs the same way on any distribution
  instead of needing each one's packages
- **Licence**: ScreenRec is now open source under Apache-2.0. `NOTICE` lists
  the licences of FFmpeg, GStreamer, Qt and the other parts it runs on

## 0.1.1 - 2026-09-24

- **New (test version)**: Linux. Records the full screen with system audio through
  the desktop's screen-sharing dialog (xdg-desktop-portal + PipeWire), so it works
  on Wayland. The first recording after starting the app asks which screen to
  share; later ones reuse the choice. Audio stays in sync with the video. Needs
  GStreamer's PipeWire plugin - see the README. Only the tray dot shows while
  recording: Linux can't keep the on-screen circle out of the video
- **New**: when ffmpeg has no x264 (e.g. Fedora's own ffmpeg), H.264 falls back
  to OpenH264 instead of failing to start
- **Fix**: with Intel Quick Sync (QSV) the quality preset's size limit was
  ignored - fast-changing content (e.g. a full-screen video) could make the file
  grow 10x or more. QSV recordings now stay within the preset's bitrate

## 0.1.0 - 2026-09-24

- **M1 done** and accepted on a real Windows 10 machine: full-screen recording
  with system audio kept in sync, quality presets, crash-safe MKV recording
  saved as MP4, a Windows installer with FFmpeg bundled, and recording
  indicators (an on-screen red circle kept out of the video, plus a tray dot).
  No code changes since 0.0.3

## 0.0.3 - 2026-09-24

- **New**: a red dot in the system tray while recording. The on-screen circle is
  hidden from all screen captures, so it is also invisible when you watch the PC
  through remote desktop (AnyDesk, Chrome Remote Desktop); the tray dot is not,
  so it shows there - at the cost of appearing in the recorded taskbar. On
  Windows 10 it starts in the hidden `^` overflow: drag it onto the taskbar once

## 0.0.2 - 2026-09-24

- **Fix**: the red recording indicator no longer shows up in recordings. It was
  drawn with a per-pixel translucent background, which made Windows reject the
  "exclude from capture" request - it now uses a round window with whole-window
  opacity. If exclusion ever fails, the status line now says so instead of
  failing silently

## 0.0.1 - 2026-09-24

- Project scaffolding: `pyproject.toml` (uv, ruff, pytest), package layout under
  `src/screenrec/`
- Core pure-function modules: `config`, `presets`, `storage`, `recorder.spec`,
  `recorder.controller`, `recorder.encoders`, `recorder.finalize`
- Windows backend: `ddagrab` full-screen capture + WASAPI loopback system audio,
  MKV recording with post-stop remux to MP4
- Minimal GUI: start/stop, quality preset, save location, system-audio toggle,
  red-circle recording indicator excluded from capture
- `power.prevent_sleep`/`allow_sleep`: keeps the display awake during recording -
  required even for M1, not just long-recording robustness. Live testing found
  `ddagrab` hangs indefinitely (no error) if the display is already asleep
- Encoder selection now probes a real one-frame encode, not just ffmpeg's
  compiled-in encoder list - catches encoders that are compiled in but rejected
  at runtime (found live: `h264_nvenc` on this machine, GPU driver too old for
  ffmpeg 9's NVENC SDK requirement)
- WASAPI loopback pads silence when nothing is actively rendering audio (e.g. a
  quiet gap between sentences in a lecture, not just "no app playing anything at
  all"): the device stops delivering frames entirely during such gaps, and
  without padding, the audio track ends up shorter than the video by the length
  of every gap and drifts out of sync. Verified live across a real tone / true
  silence / tone sequence - audio duration tracked wall-clock time through the
  gap instead of falling behind
- Verified live on this machine: full-screen capture at native resolution,
  graceful stop via CTRL_BREAK_EVENT producing a valid playable MKV, and system
  audio capture (including across silent gaps) with real non-silent samples
  where expected
- GUI: backend.start()/stop() and the post-stop MP4 remux now run on a
  background thread instead of blocking the Qt main thread - stopping a
  recording used to freeze the whole window for as long as ffmpeg took to
  exit gracefully, which read as "the stop button doesn't work". Verified
  live: the stop button's click handler now returns in ~27ms instead of
  blocking, and the recording still finalizes correctly in the background
- **Critical fix**: recordings are forced to standard `yuv420p` output. Without
  this, the encoder kept the capture's full-chroma BGRA source as-is and
  produced High 4:4:4 Predictive H.264 - ffmpeg itself decodes that fine (every
  automated check passed), but almost no real player does, so every actual
  recording "wouldn't play". Found only when the user tried playing a real
  recording, not by any ffmpeg-based check - a reminder that "ffmpeg can decode
  it without error" is not the same as "a normal player can play it"
- Recording smoothness: libx264 uses `-preset veryfast` (default "medium"
  couldn't keep up in real time and dropped frames) and output is forced to
  constant frame rate (`-fps_mode cfr -r <fps>`)
- **A/V sync fixes**, measured live with flash+beep markers at irregular
  intervals (a periodic marker hides whole-second offsets):
  - Audio capture is callback-driven and queued, decoupled from writing to
    ffmpeg. Reading and writing on one thread dropped audio whenever ffmpeg
    wasn't draining stdin yet, so audio ran ~250ms ahead within seconds
  - Silence padding is wall-clock based with a 200ms grace period. The old
    "pad after one silent period" rule fired on normal 53ms delivery jitter,
    stretching audio ~3% (0.9s late after 30s). Now: no drift, and silent
    gaps between sounds reproduced within 10ms
  - Audio start is aligned to the first captured video frame (detected via a
    `showinfo` filter on ffmpeg's stderr): audio captured before it is
    trimmed, a late audio start is padded. Audio used to play ~100ms late
    because capture started before ffmpeg grabbed its first frame - verified
    by delaying audio start 0.5s, which shifted the offset by exactly 0.5s.
    Now ~-40ms (within one 30fps frame) regardless of startup timing
  - ffmpeg's stderr is now read by the app; the last lines are included in
    the "failed to start" error message
  - The short silent-video tail after stop is trimmed at MP4 remux
    (`-shortest`); using `-shortest` while recording made ffmpeg buffer ~10s
    before emitting any video
- `-flush_packets 1`: start() waits for the output file, which took ~7s to
  appear with default buffering; now ~1s
- Stop no longer hangs: if the audio writer is blocked on a stdin ffmpeg isn't
  reading, ffmpeg is killed rather than deadlocking on `stdin.close()`; start()
  fails with an error if ffmpeg produces no output within 30s; signalling an
  already-exited ffmpeg no longer raises errno 22
- **Windows packaging**: `packaging\build.ps1` builds a windowed
  `ScreenRec.exe` (PyInstaller, unused Qt parts trimmed) with FFmpeg bundled,
  and a per-user Inno Setup installer (~79MB). Verified live: the installed
  exe records and stops with no console windows, and uninstall leaves nothing
  behind. App icon drawn in code (`ui/app_icon.py`), with an explicit
  AppUserModelID so the taskbar shows it
  - Audio now reaches ffmpeg over a loopback TCP connection instead of stdin,
    and ffmpeg is stopped by writing `q` to stdin. The old CTRL_BREAK_EVENT
    stop only works from a process with a console, which the windowed exe
    doesn't have
  - ffmpeg is located as `$SCREENREC_FFMPEG`, then the bundled copy, then
    `PATH`; all ffmpeg children run with `CREATE_NO_WINDOW`
- A/V alignment timestamps use a high-resolution clock. On Python 3.11/3.12
  under Windows, `time.monotonic()` only ticks every 15.6ms, which could drop or
  misplace audio at the start of a recording (found in CI)
- Not yet implemented: window/region capture, microphone mixing (M2)
