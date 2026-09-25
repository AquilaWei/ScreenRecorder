#!/usr/bin/env bash
# Download the FFmpeg bundled into the macOS app: a static arm64 build (x264,
# OpenH264 and VideoToolbox included, no Homebrew libraries needed) from
# https://ffmpeg.martin-riedl.de, pinned and checked against its SHA256, plus
# the GPLv3 text it is licensed under.
#
#   packaging/macos/fetch_ffmpeg.sh <out dir>   -> <out dir>/ffmpeg, <out dir>/LICENSE.txt
set -euo pipefail

FFMPEG_VERSION=9.0.2
FFMPEG_URL="https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_${FFMPEG_VERSION}/ffmpeg.zip"
FFMPEG_SHA256=c8ed4c4e6978a03c485edbfe4e0a5dc2380f8a30bba5150531b31b094492d924
LICENSE_URL="https://raw.githubusercontent.com/FFmpeg/FFmpeg/n${FFMPEG_VERSION}/COPYING.GPLv3"
LICENSE_SHA256=8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903

out=${1:?usage: fetch_ffmpeg.sh <out dir>}
mkdir -p "$out"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

curl -fsSL -o "$tmp/ffmpeg.zip" "$FFMPEG_URL"
echo "$FFMPEG_SHA256  $tmp/ffmpeg.zip" | shasum -a 256 -c -
curl -fsSL -o "$tmp/LICENSE.txt" "$LICENSE_URL"
echo "$LICENSE_SHA256  $tmp/LICENSE.txt" | shasum -a 256 -c -

unzip -q -o "$tmp/ffmpeg.zip" ffmpeg -d "$out"
cp "$tmp/LICENSE.txt" "$out/LICENSE.txt"
"$out/ffmpeg" -hide_banner -version | head -1
