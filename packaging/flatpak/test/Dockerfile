# A machine that has never seen ScreenRec, a Flatpak remote or a runtime.
# Ubuntu rather than Fedora on purpose: "another distribution" is what the
# Flatpak exists for, and the host it is built on is Fedora.
FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
        flatpak ca-certificates dbus \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m tester
USER tester
WORKDIR /home/tester
