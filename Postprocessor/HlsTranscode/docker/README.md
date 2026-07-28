# ffmpeg with libfdk_aac (containerized)

`hls_assignment.py` hardcodes `-c:a libfdk_aac`, but no distro package or public
binary build ships it. fdk-aac's license is GPL-incompatible, so
`--enable-libfdk-aac` forces `--enable-nonfree` and the result cannot be
redistributed — which is why nixpkgs omits it (`shell.nix`), and why the
gyan.dev and BtbN Windows builds omit it too. This image builds it from source.

Without it the HLS stage does not merely run slower — every ffmpeg call exits
non-zero with `Encoder not found`.

## Build

```sh
docker build -t tlmc-ffmpeg:runner Postprocessor/HlsTranscode/docker            # default target
docker build --target ffmpeg -t tlmc-ffmpeg:latest Postprocessor/HlsTranscode/docker
```

| target | size | contents |
|---|---|---|
| `ffmpeg` | 201 MB | ffmpeg + ffprobe only. Ad-hoc use, and the other stages that shell out to ffmpeg (normalizer, cue splitter). |
| `runner` *(default)* | 295 MB | adds Python + `mslex` so `hls_runner.py` runs inside the container. |

The build self-tests: if a base image or version bump ever drops libfdk_aac, the
build fails rather than a transcode run failing three days in. Pin overrides with
`--build-arg FFMPEG_VERSION=8.1.2 --build-arg FDK_AAC_VERSION=2.0.3`.

## Running the batch — use one long-lived container

`docker run` costs **~236 ms** measured. `hls_runner` issues one ffmpeg call per
track per rung: 162k × 4 = **648k invocations**, so wrapping each individual call
would burn **~12 h of pure container startup** — comparable to the entire encode.
Run the whole stage inside one container:

```sh
docker run --rm -it \
  --user "$(id -u):$(id -g)" \
  -v "$PWD:/repo" \
  -v "/mnt/tlmc:/mnt/tlmc" \
  tlmc-ffmpeg:runner
```

The library **must** be mounted at the same absolute path it has on the host
(`/mnt/tlmc:/mnt/tlmc`), because `hls_assignment.py` bakes absolute paths into
the worklist. Mounting the parent is enough — the tree itself lives at
`/mnt/tlmc/TLMC v6/`. `/repo` is bind-mounted read-write so journals and the
completed list land back on the host, and so code edits need no rebuild.

## Splitting the encode across machines

Set both variables on each node. `TLMC_SHARD_INDEX` is 0-based:

```sh
docker run --rm -it \
  --user "$(id -u):$(id -g)" \
  -e TLMC_SHARD_COUNT=3 -e TLMC_SHARD_INDEX=0 \
  -v "$PWD:/repo" \
  -v "/mnt/tlmc:/mnt/tlmc" \
  tlmc-ffmpeg:runner
```

Every node reads the same worklist and keeps only the tracks its shard owns, so
no node touches another's work. There is no queue, no lock and no coordinator —
ownership is a pure function of the track id, so the nodes need not agree on
anything but the count.

Ownership uses blake2b rather than `hash()`: Python salts string hashing per
process unless `PYTHONHASHSEED` is pinned, so `hash()` would place the same
track in different shards on different nodes, encoding some tracks three times
and others never. Measured over 100k ids the split is even to within 0.6%.

Each shard writes its own journal and completed list
(`hls_transcode.completed.output.shard0of3.txt`), so nodes on shared storage
never interleave writes into one file. On startup a node reads **every** shard's
completed list, so the shard count can change between runs, or results be
gathered from other machines, without re-encoding what is already done.

Leaving both variables unset is a single node over the whole worklist, which is
what earlier runs did.

### A node whose library is a network mount must stage locally

`TLMC_STAGE_DIR` points at scratch on the node's **own** disk. Rungs are encoded
there and the finished track is copied to its real destination in one pass.
Leave it unset when the library is local — direct writes are then strictly
better.

```sh
docker run -d --name tlmc-hls \
  --user "$(id -u):$(id -g)" \
  -e TLMC_SHARD_COUNT=2 -e TLMC_SHARD_INDEX=1 \
  -e TLMC_STAGE_DIR=/stage \
  -v "$PWD:/repo" \
  -v "/mnt/tlmc:/mnt/tlmc" \
  -v "$HOME/hls-stage:/stage" \
  tlmc-ffmpeg:runner
```

Measured on the SMB node, same track, same load:

| | |
|---|---|
| ladder written straight to SMB | 69.97 s |
| ladder written to local disk | 8.22 s |
| bulk copy of the result to SMB | 1.15 s |
| **staged total** | **9.38 s — 7.5× faster** |

The win is not bandwidth. At the time of measurement the link carried 12 MB/s of
a measured 83, the server's disk was 41% busy and the `smbd` serving that client
used 3.6% CPU — yet the node's 32 workers sat at load 36 on 454% CPU of 3200,
nearly all of them in uninterruptible I/O wait. The cost is round trips: with
`-hls_list_size 0` ffmpeg rewrites `playlist.m3u8` after **every** segment and
appends each segment as it is produced, so one rung is hundreds of small
dependent writes that each pay CIFS latency. Staging collapses a whole track
into one 22 MB streaming copy.

This is what the "keep scratch inside the Linux filesystem" caution under
[Windows workers](#windows-workers) is about, and `TLMC_STAGE_DIR` is the
supported way to honour it. A track is published only after all four rungs
render, media file before playlist, and its scratch directory is removed either
way — so a failure leaves nothing behind at the destination and nothing in
scratch.

### Measured on the real run

Two nodes, 164,287 tracks, shard count 2. Each row adds one change:

| | local | SMB node | total |
|---|---|---|---|
| single node, no sharding | 0.98 | — | **0.98** |
| + second node, direct SMB writes | 0.73 | 0.26 | **0.98** |
| + `TLMC_STAGE_DIR` on the SMB node | 0.58 | 0.43 | **1.01** |
| + `TLMC_STAGE_DIR` on both | 0.87 | 0.50 | **1.37** |
| + all cores back to the local container | 1.00 | 0.37 | **1.37** |
| + one-process ladder (both nodes) | **1.17** | **0.61** | **1.78** |

tracks/s. Projected wall clock: **45 h → 25 h.**

Two things are worth reading off this. Adding a 32-thread machine bought
*nothing* until staging existed — the second row is the first row exactly. And
cutting the SMB node from 32 workers to 12 (fifth row) moved throughput between
the nodes without creating any: the disk, not the worker count, was setting the
pace.

The local node now runs at 0.1% idle and 0.0% iowait, so it is out of headroom
until it has more cores. The SMB node is still latency-bound on reads from the
same spinning disk, which is where any further gain would come from — its own
CPU sits mostly idle.

### What each node needs

| | |
|---|---|
| the image | build locally — it is non-redistributable, see Licensing |
| the library | at the identical absolute path, read-write (HLS output is written beside each track) |
| `/repo` | the worklist, and somewhere to put its journal |

The worklist must be generated **once**, on one machine, and shared. Generating
it per node would mint different track ids and the shards would not agree.

## Ad-hoc use

`ffmpeg-docker` makes the container transparent for one-off commands. Symlink it
under the name you want to invoke:

```sh
ln -s "$PWD/Postprocessor/HlsTranscode/docker/ffmpeg-docker" ~/.local/bin/ffmpeg
ln -s "$PWD/Postprocessor/HlsTranscode/docker/ffmpeg-docker" ~/.local/bin/ffprobe
```

Override `TLMC_LIBRARY_ROOT` (default `/mnt/tlmc`) and `TLMC_FFMPEG_IMAGE`
(default `tlmc-ffmpeg:latest`) as needed. Not for the batch — see above.

## Measured: libfdk_aac vs the native encoder

4-min 44.1 kHz stereo FLAC, `-threads 1`, best of 3, on a 13900H. Two synthetic
sources bracketing real material (tonal / noisy):

| rung | native `aac` | libfdk_aac | speedup |
|---|---|---|---|
| 128k | 2.67 s / 3.07 s | 1.21 s / 1.63 s | 2.2× / 1.9× |
| 192k | 4.21 s / 3.44 s | 1.15 s / 1.74 s | 3.7× / 2.0× |
| 256k | 8.18 s / 3.42 s | 1.17 s / 1.74 s | 7.0× / 2.0× |
| 320k | 20.28 s / 17.10 s | 1.18 s / 1.75 s | **17.2× / 9.8×** |
| **full ladder** | **35.3 s / 27.0 s** | **4.7 s / 6.9 s** | **7.5× / 3.9×** |

Catalog projection (162k tracks, 5.0 min mean per `V6-MIGRATION-HANDOFF.md`
§4.2, 20 cores): **~76–99 h → ~13–19 h.**

### Keep the 320k rung

Earlier analysis of the native encoder showed 320k costing 57% of ladder CPU on
its own, and recommended dropping it. **That no longer applies.** libfdk's cost
is essentially flat across bitrate (1.15–1.75 s at every rung) — the cliff was a
degenerate rate-distortion search in ffmpeg's native encoder, not anything
inherent to AAC. With libfdk the top rung is nearly free, so there is no
throughput reason to drop it.

### Note on bit depth

ffmpeg's libfdk_aac wrapper declares `AV_SAMPLE_FMT_S16` only, so 24-bit FLAC
sources are converted to 16-bit by an auto-inserted `aresample` before encoding.
The native `aac` encoder takes `fltp` and keeps float precision through the MDCT.
This is inherent to the wrapper, not to this image.

## Windows workers

Docker Desktop (WSL2 backend) runs this image unchanged. Two caveats:

- **Keep scratch inside the Linux filesystem.** Bind-mounting a Windows path and
  writing across the 9P boundary hits a well-known performance cliff. Transcode
  to a container-local path, then move results. The same caution applies to a
  network mount on any node: the output is small-file writes, not one stream.
  (This used to say ~109 files per track, from the era of loose segments.
  `HLS_SINGLE_FILE` makes it 9 -- a playlist and one byte-range media file per
  rung, plus the master -- so 1.48 M files catalogue-wide rather than 18 M.)
- **Paths differ.** The worklist's absolute POSIX paths will not resolve against
  a Windows host mount, and `Shared/utils.py:oslex_quote` produces `mslex`
  quoting on Windows and `shlex` on POSIX — a worklist generated on one will
  produce malformed commands on the other. Generate the worklist on the same
  platform that consumes it, or stop baking pre-joined shell strings into it.

## Licensing

**The built image is non-redistributable.** Build it on each machine that needs
it, or push only to a private registry. Do not publish it or share the layers.
