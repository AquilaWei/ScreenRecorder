# ScreenRec

Cross-platform screen recorder with system audio, long recordings, and a choice of
video quality, save location, and capture range (full screen, a window, or a custom
region). A translucent red circle marks that recording is active — the circle itself
is excluded from the recording.

**Status: early development (Windows first).** See [`notes/`](notes/) for the full
feasibility study and milestone plan.

## What it does

- Records system audio (WASAPI loopback on Windows) and, optionally, the microphone
- Captures the full screen (pick which monitor), a specific window, or a custom
  rectangle
- Quality presets balance file size against clarity (H.264/HEVC, hardware encoder
  preferred, falls back to software)
- Records to MKV so a crash or power loss doesn't corrupt the file, then losslessly
  remuxes to MP4 when you stop

## Requirements

- Windows 10 2004+ (Linux/macOS backends are planned, not yet implemented)
- [FFmpeg](https://www.gyan.dev/ffmpeg/builds/) 8.0+ on `PATH` (needed for `ddagrab`
  full-screen capture)
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

## Development

```bash
uv run ruff check
uv run ruff format --check
uv run pytest
```

Unit tests run with no external dependencies. Integration tests that invoke a real
`ffmpeg` are skipped automatically if `ffmpeg` isn't on `PATH`.

## Contributing

This project follows the milestone plan in `notes/`: Windows first (M1–M4), then
Linux (M5) and macOS (M6). Each milestone lands as a `0.0.x` test release until it's
been verified on real hardware, then becomes a `0.x.0` release — see `CHANGELOG.md`.
