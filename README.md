# ScreenRec

Cross-platform screen recorder with system audio, long recordings, and a choice of
video quality, save location, and capture range (full screen, a window, or a custom
region). A translucent red circle marks that recording is active — the circle itself
is excluded from the recording.

**Status: early development — Windows, Linux and macOS (full-screen recording).** See
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

**Works now (Linux):**

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

**Works now (macOS):**

- Records the **full screen** with **system audio** through Apple's
  **ScreenCaptureKit** (macOS 13+) — no extra audio driver needed; audio is
  aligned to the video by the timestamps both share
- The **red circle** is shown and, like on Windows, kept **out of the
  recording** — so is ScreenRec's own window
- Encodes on the Mac's **hardware encoder** (VideoToolbox), falling back to x264
- Same presets and crash-safe MKV → MP4 flow; keeps the Mac awake while
  recording; a **red dot in the menu bar**
- A **.dmg** with FFmpeg bundled — Apple Silicon only

**Planned:** a specific window or a custom region, microphone mixing, and
choosing the monitor.

## Requirements

**Windows (installer — recommended)**

- Windows 10 2004+ (64-bit)
- Nothing else: FFmpeg comes with the installer

Download `ScreenRec-Setup-<version>.exe` from
[Releases](https://github.com/AquilaWei/ScreenRecorder/releases) and run it —
it installs for your user only, no admin rights needed. The installer isn't
code-signed yet, so SmartScreen may warn: click **More info → Run anyway**.

After that it's in the Start menu as **ScreenRec**. Recordings are saved to
your **Videos** folder by default.

**Updating:** download the newer installer and run it — it replaces the
installed version.

**Windows (from source)**

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

**macOS**

- macOS 13 Ventura or later on an **Apple Silicon** Mac (M1 or newer)
- Nothing else: FFmpeg comes with the app

Download `ScreenRec-<version>.dmg` from
[Releases](https://github.com/AquilaWei/ScreenRecorder/releases), open it and
drag **ScreenRec** into **Applications**. Then:

1. **First launch:** the app isn't signed with an Apple Developer ID, so
   **right-click → Open** it in Applications and confirm once. (On macOS 15, if
   there's no Open button: **System Settings → Privacy & Security → Open
   Anyway**.)
2. **Screen Recording permission:** the first recording asks for it. Turn
   ScreenRec on in **System Settings → Privacy & Security → Screen Recording**
   (**Screen & System Audio Recording** on macOS 15), then **quit and reopen**
   ScreenRec — macOS only applies it after a restart.

Recordings are saved to `~/Movies` by default.

**Updating:** download the newer `.dmg` and drag ScreenRec into Applications
again, replacing the old one. macOS may ask for the Screen Recording permission
again after an update: if recording fails, switch ScreenRec off and on in that
same settings page and reopen it.

**macOS (from source)**

- macOS 13+ on Apple Silicon
- FFmpeg on `PATH`, e.g. `brew install ffmpeg`
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- The Screen Recording permission for the terminal app you run it from

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

Releases bundle the pinned FFmpeg build that `packaging\fetch_ffmpeg.ps1`
downloads (checked against its SHA256); to build exactly that locally:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\fetch_ffmpeg.ps1 build\ffmpeg
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -FfmpegPath build\ffmpeg\bin\ffmpeg.exe
```

## Building the Linux Flatpak

```bash
flatpak install --user flathub org.flatpak.Builder
packaging/flatpak/build.sh
```

Builds, installs it for your user, and writes `build/flatpak/ScreenRec.flatpak`.
The runtime, SDK and PySide base app it needs are fetched from Flathub on the
first run.

## Building the macOS app

```bash
packaging/macos/build.sh
```

On an Apple Silicon Mac, produces `dist/ScreenRec.app` (PyInstaller, signed ad
hoc) and `dist/ScreenRec-<version>.dmg`. It bundles a pinned static FFmpeg
build from [martin-riedl.de](https://ffmpeg.martin-riedl.de) (checked against
its SHA256), which is GPL-licensed; its licence is shipped in the app's
`Contents/Resources`.

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
already released) and macOS (M6, full-screen recording already released). Each milestone lands as a `0.0.x` test release until it's
been verified on real hardware, then becomes a `0.x.0` release — see `CHANGELOG.md`.

## License

**Apache-2.0** (see `LICENSE`). FFmpeg, GStreamer, Qt for Python and the other
programs ScreenRecorder runs on keep their own licences; `NOTICE` lists them.
