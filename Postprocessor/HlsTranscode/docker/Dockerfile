# ffmpeg with libfdk_aac, for the HLS transcode stage.
#
# Why this image exists: `-c:a libfdk_aac` is hardcoded in hls_assignment.py, but
# no distro or public binary build ships it. fdk-aac's license is GPL-incompatible,
# so --enable-libfdk-aac forces --enable-nonfree, and the resulting binary cannot
# be redistributed. nixpkgs omits it for the same reason (see shell.nix).
#
# LICENSING: the image built here is NON-REDISTRIBUTABLE. Build it on each machine
# that needs it, or push only to a private registry. Do not publish it.
#
#   docker build -t tlmc-ffmpeg:latest Postprocessor/HlsTranscode/docker
#
# syntax=docker/dockerfile:1

ARG DEBIAN_TAG=bookworm-slim
ARG FFMPEG_VERSION=8.1.2
ARG FDK_AAC_VERSION=2.0.3

# ---------------------------------------------------------------- builder ----
FROM debian:${DEBIAN_TAG} AS build
ARG FFMPEG_VERSION
ARG FDK_AAC_VERSION

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      autoconf automake libtool pkg-config \
      build-essential ca-certificates curl nasm xz-utils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /src

# Sources are fetched to disk before extracting, never piped into tar: ffmpeg.org
# reset the connection mid-transfer during development, and a truncated pipe
# corrupts the extract with no chance to retry.
#
# fdk-aac from source rather than a distro package: not every base has it, and
# pinning the version keeps worker images byte-comparable across machines.
# Static + PIC so the final image carries no fdk shared object.
RUN curl -fsSL --retry 5 --retry-all-errors -o fdk-aac.tar.gz \
      "https://github.com/mstorsjo/fdk-aac/archive/refs/tags/v${FDK_AAC_VERSION}.tar.gz" \
 && tar xzf fdk-aac.tar.gz \
 && cd "fdk-aac-${FDK_AAC_VERSION}" \
 && ./autogen.sh \
 && ./configure --prefix=/opt/deps --disable-shared --enable-static --with-pic \
 && make -j"$(nproc)" \
 && make install

# nasm above matters: without it ffmpeg silently drops its x86 SIMD paths and
# both the FLAC decoder and the MDCT get materially slower.
RUN curl -fsSL --retry 5 --retry-all-errors -o ffmpeg.tar.xz \
      "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz" \
 && tar xJf ffmpeg.tar.xz \
 && cd "ffmpeg-${FFMPEG_VERSION}" \
 && PKG_CONFIG_PATH=/opt/deps/lib/pkgconfig ./configure \
      --prefix=/opt/ffmpeg \
      --pkg-config-flags=--static \
      --extra-cflags=-I/opt/deps/include \
      --extra-ldflags=-L/opt/deps/lib \
      --enable-gpl \
      --enable-version3 \
      --enable-nonfree \
      --enable-libfdk-aac \
      --disable-doc \
      --disable-ffplay \
      --disable-debug \
 && make -j"$(nproc)" \
 && make install

# ---------------------------------------------------------------- runtime ----
# Target `ffmpeg`: the bare tool, for ad-hoc use and the other pipeline stages
# that shell out to ffmpeg (normalizer, cue splitter).
#   docker build --target ffmpeg -t tlmc-ffmpeg:latest Postprocessor/HlsTranscode/docker
FROM debian:${DEBIAN_TAG} AS ffmpeg

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /usr/sbin/nologin --uid 1000 tlmc

COPY --from=build /opt/ffmpeg/bin/ffmpeg  /usr/local/bin/ffmpeg
COPY --from=build /opt/ffmpeg/bin/ffprobe /usr/local/bin/ffprobe

# Build-time self-test. The whole point of the image is libfdk_aac; if a future
# base image or version bump drops it, fail here rather than three days into a
# transcode run that silently fell back or errored per-track.
RUN ffmpeg -hide_banner -encoders | grep -q ' libfdk_aac ' \
 && ffprobe -hide_banner -version >/dev/null \
 && echo "OK: $(ffmpeg -hide_banner -version | head -1) with libfdk_aac"

USER tlmc
WORKDIR /work

# No ENTRYPOINT: both binaries stay reachable as
#   docker run --rm tlmc-ffmpeg ffmpeg  ...
#   docker run --rm tlmc-ffmpeg ffprobe ...
CMD ["ffmpeg", "-hide_banner", "-version"]

# ----------------------------------------------------------------- runner ----
# Default target. Adds just enough Python to run hls_runner.py *inside* one
# long-lived container.
#
# This exists because `docker run` costs ~236 ms measured. hls_runner issues one
# ffmpeg call per track per rung — 162k x 4 = 648k invocations — so wrapping each
# call in its own container would burn ~12 h of pure startup, comparable to the
# entire encode. Run the batch inside one container instead; see README.md.
#
# Only mslex is installed: hls_runner reaches Shared/utils.py, which imports it
# unconditionally at module top. The repo itself is bind-mounted, not baked in,
# so code edits need no rebuild.
FROM ffmpeg AS runner
USER root

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip mslex \
 && chown -R tlmc /opt/venv

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/repo \
    PYTHONUNBUFFERED=1

USER tlmc
WORKDIR /repo
CMD ["python", "-m", "Postprocessor.HlsTranscode.hls_runner"]
