#!/usr/bin/env bash
# Install the bundle on a clean Ubuntu container and check it runs there.
#
#   packaging/flatpak/test.sh          # needs build/flatpak/ScreenRec.flatpak
#   packaging/flatpak/test.sh --clean  # remove the image and the cached runtime
#
# The runtime (~1 GB) is kept in a Docker volume between runs; --clean drops it.
# See test/inside.sh for what this does and doesn't cover.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIR="$REPO/packaging/flatpak/test"
BUNDLE="${BUNDLE:-$REPO/build/flatpak/ScreenRec.flatpak}"
IMAGE=screenrec-flatpak-test
VOLUME=screenrec-flatpak-cache

if [ "${1:-}" = "--clean" ]; then
    docker rmi -f "$IMAGE" >/dev/null 2>&1
    docker volume rm "$VOLUME" >/dev/null 2>&1
    exit 0
fi
[ -f "$BUNDLE" ] || { echo "no $BUNDLE - run packaging/flatpak/build.sh first" >&2; exit 1; }

docker build -q -t "$IMAGE" "$DIR" >/dev/null
docker volume create "$VOLUME" >/dev/null

# --privileged: bubblewrap needs it inside a container. /dev/fuse: ostree's
# checkout does. The container itself is thrown away (--rm).
docker run --rm --privileged \
    --security-opt seccomp=unconfined \
    --device /dev/fuse \
    -v "$VOLUME:/home/tester/.local/share/flatpak" \
    -v "$BUNDLE:/home/tester/ScreenRec.flatpak:ro" \
    -v "$DIR/inside.sh:/home/tester/run.sh:ro" \
    -v "$DIR/entry.sh:/entry.sh:ro" \
    --user root "$IMAGE" bash /entry.sh /home/tester/ScreenRec.flatpak
