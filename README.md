# ScreenRec

Cross-platform screen recorder with system audio, long recordings, and a choice of
video quality, save location, and capture range (full screen, a window, or a custom
region). A translucent red circle marks that recording is active — the circle itself
is excluded from the recording.

**Status: early development — Windows, plus a Linux test version.** See
[`CHANGELOG.md`](CHANGELOG.md) for what works today.

## What it does

**Works now (Windows):**

- Records the **full screen** with **system audio** (WASAPI loopback), kept in
  sync with the video — including across silent gaps
- **Quality presets** balance file size against clarity (H.264; hardware encoder
  preferred, falls back to software)
- Records to **MKV** so a crash or power loss doesn't corrupt the file, then
  losslessly remuxes to **MP4** when you stop
- **Installer** with Start menu / desktop shortcuts — FFmpeg bundled
- A **red dot in the system tray** while recording — unlike the on-screen circle
  it also shows through remote desktop (AnyDesk, Chrome Remote Desktop), which
  hides capture-excluded windows. Windows 10 puts new tray icons in the hidden
  `^` overflow: drag it onto the taskbar once and Windows remembers

**Works now (Linux, test version - not yet accepted on real hardware):**

- Records the **full screen** with **system audio** (tested on KDE Plasma, Wayland), through
  the desktop's screen-sharing portal (xdg-desktop-portal + PipeWire). The first
  recording after launching the app asks **which screen to share** in the
  desktop's own dialog; later ones reuse that choice
- Video and audio are captured by **one GStreamer pipeline**, so they share a clock
  and stay in sync; ffmpeg encodes, with the same presets and MKV → MP4 flow
- Encodes on the **graphics card** (NVIDIA, Intel Quick Sync, or VAAPI on Intel
  and AMD); falls back to x264, or **OpenH264** when ffmpeg has no x264
  (e.g. Fedora's own ffmpeg)
- A **Flatpak** that runs the same on any distribution — see below
- Keeps the machine from sleeping or blanking the screen while recording
- **Tray dot only**: Linux can't keep a window out of a screen capture, so the
  on-screen red circle isn't shown (it would be recorded)

**Planned:** a specific window or a custom region, microphone mixing, choosing
the monitor on Windows, and macOS.

## Requirements

**Windows**

- Windows 10 2004+
- [FFmpeg](https://www.gyan.dev/ffmpeg/builds/) 8.0+ on `PATH` (needed for `ddagrab`
  full-screen capture)
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)

**Linux (Flatpak — recommended)**

- A desktop with xdg-desktop-portal screen casting (KDE Plasma, GNOME, …) and
  PipeWire — the default on current Fedora and Ubuntu
- [Flatpak](https://flathub.org/setup) with the Flathub remote. Nothing else:
  FFmpeg (with x264), GStreamer and Qt come with the Flatpak

Download `ScreenRec-<version>.flatpak` from
[Releases](https://github.com/AquilaWei/ScreenRecorder/releases), then:

```bash
flatpak install --user ./ScreenRec-<version>.flatpak
flatpak run io.github.AquilaWei.ScreenRecorder
```

After that it's in your application menu as **ScreenRec**. Recordings are saved
to `~/Videos` by default.

**Updating:** download the newer `.flatpak` from Releases and run the same
`flatpak install` command — it replaces the installed version. `flatpak update`
and software centres won't offer new versions, since ScreenRec is published
here rather than on Flathub.

**Linux (from source)**

- A desktop with xdg-desktop-portal screen casting (KDE Plasma, GNOME, …) and
  PipeWire — the default on current Fedora and Ubuntu
- FFmpeg with an H.264 encoder (x264, OpenH264, or a working NVENC/QSV), plus
  GStreamer with its PipeWire and PulseAudio plugins:

  ```bash
  # Fedora
  sudo dnf install ffmpeg gstreamer1-plugins-good pipewire-gstreamer
  # Debian / Ubuntu
  sudo apt install ffmpeg gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-pipewire gstreamer1.0-pulseaudio
  ```

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)

## Running it

```bash
uv sync
uv run screenrec
```

## Building the Windows installer

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Produces `dist\ScreenRec\ScreenRec.exe` (PyInstaller one-folder build with the
FFmpeg found on `PATH` bundled under `ffmpeg\`) and, if
[Inno Setup 6](https://jrsoftware.org/isinfo.php) is installed,
`dist\ScreenRec-Setup-<version>.exe` — a per-user installer (no admin rights)
with Start menu / optional desktop shortcuts and an uninstaller. Pass
`-FfmpegPath` to bundle a specific `ffmpeg.exe`. The bundled FFmpeg is
GPL-licensed; its license is shipped next to it.

## Building the Linux Flatpak

```bash
flatpak install --user flathub org.flatpak.Builder
packaging/flatpak/build.sh
```

Builds, installs it for your user, and writes `build/flatpak/ScreenRec.flatpak`.
The runtime, SDK and PySide base app it needs are fetched from Flathub on the
first run.

## Development

```bash
uv run ruff check
uv run ruff format --check
uv run pytest
```

Unit tests run with no external dependencies. Integration tests that invoke a real
`ffmpeg` are skipped automatically if `ffmpeg` isn't on `PATH`.

## Contributing

Windows comes first (milestones M1–M4), then Linux (M5, full-screen recording
already in testing) and macOS (M6). Each milestone lands as a `0.0.x` test release until it's
been verified on real hardware, then becomes a `0.x.0` release — see `CHANGELOG.md`.

## License

**Apache-2.0** (see `LICENSE`). FFmpeg, GStreamer, Qt for Python and the other
programs ScreenRecorder runs on keep their own licences; `NOTICE` lists them.
