# MERT inference (containerized)

Embedding generation for the catalogue, on the RTX 5090 node. Unlike
`tlmc-ffmpeg`, **this image is redistributable** — inference only decodes audio,
so the distro ffmpeg suffices and no non-free encoder is linked in.

```sh
docker build -t tlmc-mert:runner Experimental/docker
```

## Why a container here

The inference node has **no ffmpeg, no uv and no torch on the host**, so
something gets installed either way. Given that, the image also pins the
torch/CUDA pair against the driver and sandboxes `trust_remote_code=True` —
MERT's model definition is code fetched from HuggingFace and executed at load.

GPU passthrough is already working on that node; verified with the existing
image:

```
$ docker run --rm --runtime=nvidia --gpus all tlmc-ffmpeg:runner nvidia-smi
NVIDIA GeForce RTX 5090, 32607 MiB, 610.74
```

## Running

```sh
docker run --rm -it \
  --runtime=nvidia --gpus all \
  --shm-size=8g --memory=24g \
  --user "$(id -u):$(id -g)" \
  -v "$PWD:/repo" \
  -v "/mnt/tlmc:/mnt/tlmc" \
  -v "$HOME/.cache/huggingface:/hf" -e HF_HOME=/hf \
  -e MERT_TARGET_CSV=/repo/Experimental/data_transfer/all_targets.csv \
  -e MERT_EMBEDDING_DIR=/repo/Experimental/embeddings/chunked_6s \
  tlmc-mert:runner
```

The library must be mounted at its host absolute path — the target CSV holds
absolute `PlaylistPath` values, same constraint as the transcode worklist.

### `--shm-size` is not optional

`DataLoader(num_workers=8)` passes tensors between processes through `/dev/shm`.
Docker's default is **64 MB**, and the failure mode is a bare `Bus error` partway
into the run with no useful traceback. 8 GB is comfortable at `batch_size=64`,
which reserves ~2.4 GB of chunk buffers across the prefetch queue. `--memory` is
there so a runaway kills the container rather than WSL.

## Measured throughput, and why batch size matters so much

RTX 5090 (32 GB), 6 s chunks, `output_hidden_states=True`, fp16 autocast,
synthetic audio so nothing is I/O-bound:

| batch | s/batch | chunks/s | peak VRAM | tracks/s | ETA for 164k |
|---|---|---|---|---|---|
| 8 | 0.029 | 275 | 2.5 GB | 3.67 | 12.4 h |
| 16 | 0.050 | 320 | 3.7 GB | 4.26 | 10.7 h |
| **32** | 0.092 | **347** | 6.0 GB | 4.62 | 9.9 h |
| **64** | 0.187 | **342** | 10.8 GB | 4.56 | 10.0 h |
| 96 | 0.271 | 354 | 15.5 GB | 4.72 | 9.7 h |
| 128 | 0.362 | 353 | 20.3 GB | 4.71 | 9.7 h |
| 224 | 9.00 | **25** | **34.6 GB** | 0.33 | **137.6 h** |

Throughput is flat from 32 upward — the GPU is saturated well before the card
is. The last row is the trap: 224 asks for **34.6 GB on a 32 GB card**, so the
allocator spills into host memory across PCIe and the run goes **14× slower**
than any batch that fits. It does not OOM, it just quietly crawls, which is the
worst way for this to fail.

`batch_size=64` is what the script now uses: on the plateau, with headroom for
real-audio length variance and `torch.compile`'s workspace.

These are GPU-only numbers. Real throughput will be lower — see below.

### Feed from the 128k rung

At ~4.6 tracks/s the input side stops being free:

| rung read | MB/track | MB/s at 4.6 tracks/s |
|---|---|---|
| 128k | ~4.8 | 22 |
| 320k | ~12 | 56 |

The mount tops out around 76 MB/s, so pulling the 320k rung spends most of the
link on data that cannot survive the resample — MERT works at 24 kHz mono, a
12 kHz ceiling, far below where 128k AAC degrades. `make_archive.py` selects
`hp."Bitrate" = 320`; the target CSV for inference should select 128 instead.
Worth A/B-ing embeddings on a few hundred tracks before committing.

## The cu124 trap

`Experimental/pyproject.toml` pins `torch==2.6.0+cu124`. **That cannot run on this
GPU.** The 5090 is Blackwell (`sm_120`); cu124 wheels carry kernels for sm_50–sm_90
only, and the CUDA 12.4 runtime cannot JIT forward to an architecture that
postdates it. It fails at the first kernel launch — *after* the model loads,
which makes it look like a model problem.

The image therefore builds against **cu128 / torch 2.7.1**, and self-tests at
build time so a bad wheel fails the build rather than the run — the same
principle as the libfdk_aac check in the HLS image.

The check has to read the compiled kernel list *without* a GPU, since
`docker build` has no device attached. The obvious call is a trap:

| call | without a GPU |
|---|---|
| `torch.cuda.get_arch_list()` | `[]` — short-circuits on `is_available()` |
| `torch._C._cuda_getArchFlags()` | `sm_75 sm_80 sm_86 sm_90 sm_100 sm_120 compute_120` |

`get_arch_list()` returns empty rather than raising, so a check built on it
fails every image including correct ones. The private call reads the value baked
in at wheel-build time and is what the Dockerfile uses.

## Resume and journalling

`utils/journal.py` gives the run the same crash-safety the transcode stage ended
up with:

| | |
|---|---|
| completed list | append-only text file, read once at start — not an `os.walk` over 164k `.pt` files on every restart |
| ordering | a track is journalled **after** its `.pt` is durably renamed into place, never at submit time |
| failures | logged to `mert_chunked_6s.failed.txt` with the reason, instead of a `print` that scrolls away |

Adopting the journal is non-destructive: on first run it seeds itself from a
directory scan, so embeddings from earlier runs are imported rather than
recomputed.

`save_tensor` is atomic (`torch.save` to a sibling temp, then `os.replace`).
Saving straight to the final name leaves a truncated `.pt` if the process dies
mid-write, and since resume treats any `.pt` as proof of completion, that track
would be skipped forever with a corrupt embedding.

Tests: `python3 Experimental/tests/test_journal.py` and
`Experimental/tests/test_atomic_save.py` — no GPU or torch required.

## Sequencing

Inference reads the HLS ladder, so it cannot start until the transcode
finishes — and it wants the same node currently serving shard 1. Naturally
serialized. Pull the image **after** the transcode lands: it is 8–10 GB and
shares the 1 GbE link the SMB mount is saturating.
