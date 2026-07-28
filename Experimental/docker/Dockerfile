# MERT-v1-330M inference, containerized.
#
# Why this image exists: the inference node (the RTX 5090 box) has no ffmpeg, no
# uv and no torch on the host, so *something* gets installed either way. Given
# that, a container also pins the torch/CUDA pair against the driver, and
# sandboxes `trust_remote_code=True` -- MERT's model definition is code fetched
# from HuggingFace and executed at load time.
#
# Unlike tlmc-ffmpeg, THIS IMAGE IS REDISTRIBUTABLE. Inference only *decodes*
# audio, so the distro ffmpeg is enough: no libfdk_aac, no --enable-nonfree.
#
#   docker build -t tlmc-mert:runner Experimental/docker
#
# syntax=docker/dockerfile:1

ARG PYTHON_TAG=3.11-slim-bookworm

# torch 2.6.0+cu124, as pinned in Experimental/pyproject.toml, CANNOT run on this
# GPU. The RTX 5090 is Blackwell (sm_120); cu124 wheels carry kernels for sm_50
# through sm_90 only, and the CUDA 12.4 runtime cannot JIT forward to an
# architecture it predates. It fails at the first kernel launch with
# "no kernel image is available for execution on the device" -- after the model
# has loaded, which makes it look like a model problem rather than a build one.
# sm_120 needs CUDA >= 12.8 and torch >= 2.7.
ARG TORCH_VERSION=2.7.1
ARG TORCHAUDIO_VERSION=2.7.1
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu128

FROM python:${PYTHON_TAG}
ARG TORCH_VERSION
ARG TORCHAUDIO_VERSION
ARG TORCH_INDEX

# ffmpeg: utils/loader.py:load_m3u8 shells out to it to decode the HLS ladder to
#         f32le mono, and pydub calls it too. Verified: the bookworm build reads
#         our fMP4 single_file playlists with no extra flags.
# libsndfile1: soundfile's native dependency, imported by loader.py.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates ffmpeg libsndfile1 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /usr/sbin/nologin --uid 1000 tlmc

# torch first and alone: it comes from a different index than everything else,
# and installing it in the same resolve lets pip pull a PyPI (CPU) torch to
# satisfy a transitive pin, silently undoing the CUDA build.
RUN pip install --no-cache-dir --index-url ${TORCH_INDEX} \
      "torch==${TORCH_VERSION}" "torchaudio==${TORCHAUDIO_VERSION}"

# Runtime deps of scripts/mert_batched_uuid.py and utils/{loader,utils,journal}.py
# only -- not the full Experimental/pyproject.toml, which also carries the
# notebook, visualisation, FAISS and jukebox stacks that inference never touches.
#
# nnAudio is here because MERT's remote modeling code imports it at class-definition
# time when config.feature_extractor_cqt is set; missing, it fails during
# from_pretrained rather than at import.
RUN pip install --no-cache-dir \
      transformers \
      numpy \
      pandas \
      soundfile \
      pydub \
      tqdm \
      nnAudio

# Build-time self-test, in the spirit of the libfdk_aac check in the HLS image:
# fail here, not three hours into a run. This is what catches the cu124/sm_120
# trap described above.
#
# It must read the compiled-in kernel list WITHOUT a GPU, because `docker build`
# has no device. The obvious call does not do that:
#
#   torch.cuda.get_arch_list() -> []      # short-circuits on is_available()
#   torch._C._cuda_getArchFlags() -> "sm_75 sm_80 sm_86 sm_90 sm_100 sm_120 compute_120"
#
# get_arch_list() returns an empty list rather than raising, so a naive check
# reads it as "sm_120 missing" and fails a perfectly good image. The private
# call reads the value baked in at wheel-build time and needs no device.
RUN python -c "\
import torch, sys; \
flags = (torch._C._cuda_getArchFlags() or '').split(); \
print('torch', torch.__version__, 'CUDA', torch.version.cuda); \
print('compiled arch flags:', ' '.join(flags) or '(none)'); \
sys.exit(0 if 'sm_120' in flags else 'FATAL: wheel has no sm_120 kernels -- will not run on an RTX 5090')" \
 && python -c "import torchaudio, transformers, soundfile, pydub, pandas; print('imports OK')" \
 && ffmpeg -hide_banner -decoders 2>/dev/null | grep -qE '^ *A[.A-Z]* +aac ' \
 && echo "OK: $(ffmpeg -hide_banner -version | head -1)"

# HF_HOME is a mount point in practice -- see README. Left inside the image so a
# run without the volume still works, just re-downloading ~1.3 GB of weights.
ENV HF_HOME=/hf \
    PYTHONUNBUFFERED=1

RUN mkdir -p /hf && chown tlmc /hf

USER tlmc
# scripts/ resolve `utils.*` via parents[1] on __file__, so the repo's
# Experimental/ directory is the working directory, not the repo root.
WORKDIR /repo/Experimental

CMD ["python", "scripts/mert_batched_uuid.py"]
