#!/usr/bin/env bash
# Builds dist/ScreenRec.app (PyInstaller, FFmpeg bundled) and
# dist/ScreenRec-<version>.dmg. Apple Silicon only.
#
#   packaging/macos/build.sh
#
# The app is signed ad hoc, not with a Developer ID: macOS asks for confirmation
# the first time it's opened, and may ask for the Screen Recording permission
# again after each update (see the README).
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
version=$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -1)
app=dist/ScreenRec.app
echo "ScreenRec $version"

uv sync --group build
QT_QPA_PLATFORM=offscreen uv run --no-sync python packaging/macos/make_icns.py packaging/screenrec.icns
uv run --no-sync pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/screenrec.spec

# Next to the executable, where bundled_ffmpeg_dir() looks. Its licence goes to
# Resources: codesign rejects non-code files among the executables.
packaging/macos/fetch_ffmpeg.sh build/ffmpeg
mkdir -p "$app/Contents/MacOS/ffmpeg"
cp build/ffmpeg/ffmpeg "$app/Contents/MacOS/ffmpeg/ffmpeg"
cp build/ffmpeg/LICENSE.txt "$app/Contents/Resources/FFmpeg-LICENSE.txt"

codesign --force --deep --sign - "$app"
codesign --verify --deep --strict "$app"

dmg="dist/ScreenRec-$version.dmg"
staging=build/dmg
rm -rf "$staging" "$dmg"
mkdir -p "$staging"
cp -R "$app" "$staging/"
ln -s /Applications "$staging/Applications"  # drag-to-install target
hdiutil create -volname "ScreenRec $version" -srcfolder "$staging" -format UDZO "$dmg"
echo "wrote $dmg"
