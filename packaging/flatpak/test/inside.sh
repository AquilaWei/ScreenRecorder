#!/usr/bin/env bash
# Runs inside the container: install the bundle and check what can be checked
# without a desktop. Not covered here (no display server, PipeWire or GPU):
# the screen-sharing portal, recording itself, audio and VAAPI.
set -uo pipefail
ID=io.github.AquilaWei.ScreenRecorder
BUNDLE="$1"
say() { printf '\n=== %s ===\n' "$*"; }
fail() { echo "FAIL: $*"; exit 1; }

say "1. Starting point"
echo "distribution: $(. /etc/os-release; echo "$PRETTY_NAME")"
echo "user remotes: $(flatpak --user remotes | wc -l), runtimes: $(flatpak --user list --runtime | wc -l)"

say "2. flatpak install --user $(basename "$BUNDLE")"
flatpak install --user -y --noninteractive "$BUNDLE" || fail "install"
flatpak --user list --app --columns=application,version

say "3. Encoder the app picks (no GPU here, so software)"
encoder=$(flatpak run --command=python3 $ID -c "
from pathlib import Path
from screenrec.recorder.encoders import choose_encoder
from screenrec.recorder.spec import *
print(choose_encoder(RecordingSpec(CaptureTarget(CaptureMode.FULL_SCREEN, 0),
      QualityPreset.STANDARD, VideoCodec.H264, AudioSource.SYSTEM, Path('x.mkv'))))")
echo "encoder: $encoder"
[ "$encoder" = libx264 ] || fail "expected libx264, got '$encoder'"

say "4. GStreamer elements the recorder needs"
for element in pipewiresrc pulsesrc matroskamux videorate; do
    flatpak run --command=gst-inspect-1.0 $ID $element > /dev/null || fail "$element missing"
    echo "$element: ok"
done
version=$(flatpak run --command=gst-inspect-1.0 $ID pipewiresrc | awk '/^ +Version/ {print $2}')
echo "pipewiresrc version: $version"
[ "$version" = 1.6.9 ] || fail "expected the bundled pipewiresrc 1.6.9"

say "5. The GUI starts (offscreen) and keeps running"
QT_QPA_PLATFORM=offscreen timeout 5 flatpak run --env=QT_QPA_PLATFORM=offscreen $ID
rc=$?
[ $rc -eq 124 ] || fail "app exited with $rc before the timeout"
echo "still running after 5 s: ok"

say "PASS"
