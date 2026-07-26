# Development environment for the TLMC ETL pipeline.
#
# The pipeline shells out to ffmpeg/ffprobe and loads a .NET assembly through
# pythonnet, none of which live in the NixOS system profile. Entering this shell
# puts them on PATH so every stage in Docs/STEPS.md can run:
#
#     nix-shell            # then run the pipeline steps as documented
#
# Python itself is NOT provided here: the repo uses a uv-managed .venv (which
# carries mslex, pythonnet, xxhash and the rest). Use ./.venv/bin/python, or the
# `py` alias defined below.
#
# NOTE ON libfdk_aac: Docs/STEPS.md asks for an ffmpeg built with libfdk-aac for
# the HLS transcode stage. nixpkgs ships ffmpeg-full WITHOUT it, because fdk-aac
# is unfree and cannot be redistributed in binary form. This shell therefore
# provides a stock ffmpeg, which is enough for every preprocessing stage
# (normalization, cue splitting) since those only decode and re-encode FLAC.
# For HLS you must either set withFdkAac (see ffmpegFdk below, requires
# allowUnfree and a local build) or fall back to ffmpeg's native `aac` encoder.

{ pkgs ? import <nixpkgs> { } }:

let
  # Opt-in: an ffmpeg with libfdk_aac for the HLS stage. Building this compiles
  # ffmpeg from source and requires NIXPKGS_ALLOW_UNFREE=1, so it is not part of
  # the default buildInputs.
  ffmpegFdk = pkgs.ffmpeg-full.override { withFdkAac = true; };
in
pkgs.mkShell {
  name = "tlmc-etl";

  buildInputs = with pkgs; [
    ffmpeg # ffmpeg + ffprobe: normalizer, cue splitter, HLS transcode
    dotnet-sdk_8 # builds and hosts CueSplitInfoProvider via pythonnet
    p7zip # 7z: archive extraction
    icu # .NET globalization support
    openssl
    zlib
  ];

  shellHook = ''
    # STEPS.md: the repo root must be importable for `python -m Preprocessor...`
    export PYTHONPATH="$PWD:$PYTHONPATH"

    # pythonnet locates the runtime through DOTNET_ROOT
    export DOTNET_ROOT="${pkgs.dotnet-sdk_8}/share/dotnet"
    export DOTNET_CLI_TELEMETRY_OPTOUT=1
    export DOTNET_NOLOGO=1

    alias py='./.venv/bin/python'

    echo "tlmc-etl dev shell"
    echo "  ffmpeg  $(ffmpeg  -version 2>/dev/null | head -1 | cut -d' ' -f3)"
    echo "  ffprobe $(ffprobe -version 2>/dev/null | head -1 | cut -d' ' -f3)"
    echo "  dotnet  $(dotnet --version 2>/dev/null)"
    echo "  7z      $(7z 2>/dev/null | sed -n 2p | cut -d' ' -f1-3)"
    echo "  python  ./.venv/bin/python (alias: py)"
    echo
    echo "Library root for every stage that prompts: /mnt/tlmc"
  '';
}
