#!/usr/bin/env bash
# Build the Flatpak, install it for this user, and write a bundle to share.
#
#   packaging/flatpak/build.sh              # build, install --user, bundle
#   packaging/flatpak/build.sh --no-bundle  # build and install only
#
# Output: build/flatpak/ScreenRec.flatpak. Needs flatpak-builder - installed
# natively (as in CI's Flathub container) or as a Flatpak (flatpak install
# flathub org.flatpak.Builder). The runtime, SDK and base app named in the
# manifest are pulled in by --install-deps-from.
#
# Everything lands under build/, which the manifest's `dir` source skips -
# a build directory anywhere else in the tree would copy itself.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ID="io.github.AquilaWei.ScreenRecorder"
MANIFEST="$REPO/packaging/flatpak/$ID.yml"
OUT="$REPO/build/flatpak"

bundle=1
if [ "${1:-}" = "--no-bundle" ]; then bundle=0; shift; fi

if command -v flatpak-builder >/dev/null; then
    builder=(flatpak-builder)
else
    builder=(flatpak run org.flatpak.Builder)
fi

mkdir -p "$OUT"
"${builder[@]}" \
    --force-clean --user --install \
    --install-deps-from=flathub \
    --state-dir "$OUT/state" \
    --repo "$OUT/repo" \
    "$@" \
    "$OUT/build" "$MANIFEST"

if [ "$bundle" -eq 1 ]; then
    # --runtime-repo lets `flatpak install ./ScreenRec.flatpak` on a machine
    # that has never seen the KDE runtime fetch it from Flathub by itself.
    flatpak build-bundle \
        --runtime-repo=https://flathub.org/repo/flathub.flatpakrepo \
        "$OUT/repo" "$OUT/ScreenRec.flatpak" "$ID"
    ls -lh "$OUT/ScreenRec.flatpak"
fi
