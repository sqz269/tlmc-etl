# TLMC v6 Migration — Handoff

Findings from an audit of the pipeline against the v6 release, the storage it
runs on, and the embedding/vector-search work. Everything marked **measured**
was taken from this machine and this data; everything marked *estimated* is
extrapolation and is labelled as such.

Status legend: **DONE** shipped · **OPEN** needs work · **DECISION** needs a human call

---

## 1. Summary

| Area | State |
|---|---|
| Extract stage rewritten for v6 | **DONE**, committed on `extract-stage-v6` (`9f28dad`), not merged |
| Extraction run | **OPEN** — never started, all 18,500 archives intact |
| Storage array | **DECISION** — rebuild pending, blocks everything downstream |
| HLS segment layout | **OPEN** — change before re-transcoding or it cannot be retrofitted |
| Embedding generation | **OPEN** — 13 issues, several lose data silently |
| Vector search / serving | **OPEN** — 13 issues, one makes the FAISS index unusable |
| Chamfer reranker + chunk store | **DONE**, `Experimental/vector_search/{chunk_store,rerank}.py` |

Nothing destructive has been run. The source release is untouched and the
torrent is seeding.

---

## 2. Extract stage — DONE

v6 ships `.7z` archives across several parallel roots instead of `.rar` under a
single root, so the stage matched nothing and the `!Misc` merge in `STEPS.md`
described a layout that no longer exists.

Shipped on branch `extract-stage-v6`:

- `Preprocessor/Extract/extract_plan.py` (new) — reads every archive index
  without extracting, resolves the three layouts present in v6 (`flat`,
  `nested`, `bundle`), folds circle-name variants onto one canonical spelling,
  and writes a reviewable plan.
- `Preprocessor/Extract/extract.py` (rewritten) — executes the plan, journals
  per archive so it resumes, refuses to start while two archives claim the same
  album directory.
- `Preprocessor/Extract/extraction_exclusions.json` (new) — every per-release
  decision, version controlled and never regenerated.
- Snapshot scripts accept `.7z`/`.zip`/`.rar`.
- `extracted_snapshot.py` — fixed `generate_rar_list` shadowing its accumulator
  with the `os.walk` loop variable, so it never returned a usable list.
- `Docs/STEPS.md` — preprocessing steps 0–2 rewritten.

Verified end to end on a 4-archive scratch run covering all three layouts plus a
corrupt archive: tracks land at `<circle>/<album>/<track>`, failures are
journaled without aborting, resume skips completed work.

### Plan output (current)

```
archives            : 18284        albums produced : 18350
layout flat         : 18238        nested : 24     bundle : 19
circle aliases      : 16
excluded roots      : 2 (temp, Software)
excluded archives   : 4
collision resolutions: 43          collisions remaining : 0
needs review        : 130          unreachable content  : 39
```

### 2.1 OPEN — before extraction can run

| # | Item | Detail |
|---|---|---|
| E1 | Destination directory | `/mnt/external_storage` is `root:root`; needs `sudo mkdir -p <dest> && sudo chown sqz269:users <dest>`. Passwordless sudo is not available to automation. |
| E2 | Re-plan after array rebuild | The plan bakes absolute paths into all entries. Regenerating is ~90 s; all decisions carry over via the exclusions file. |
| E3 | `DELETE_ARCHIVE_AFTER_EXTRACT` | Currently `False` (deliberately disarmed). Flip when the destination array exists. Destroys the torrent copy. |
| E4 | 130 review items | Mostly confirmations. 46 are archives with **no usable audio**: 7 DVD rips (`.vob`/`.bup`/`.ifo`), 2 `.mkv` (largest is 17 GB), 22 scan-only, plus `1×jpg` stubs. Each would produce an album with zero tracks. Keep-or-drop is a content call. |
| E5 | 39 unreachable items | Loose audio at circle level (77 files) and 6 album directories sitting at circle depth. `info_scanner_ph1.py` only descends two levels, so these are dropped unless moved by hand. |

### 2.2 Known data problems found and excluded

- `various album/Various Artists/2022_10_28_NA_旅行恋恋Art_Book_...rar` — corrupt,
  7z cannot open it.
- `various album/!MP3/As／Hi Soundworks × 梶迫小道具店.7z` — contains one empty
  directory, nothing else.
- `various album/[TTL SOUND]/Singles.7z` — bundle of 11 singles that all exist
  individually under `Other album`; fully redundant.
- `various album/[岸田教団&THE明星ロケッツ]/... Super Pro Max Ti.7z` — contains only
  `Thumbs.db`.
- `various album/!MP3/Engage Blue.7z` — **not excluded**, flagged. Holds 35
  `.ogg` files, a codec no pipeline stage accepts, so all 35 tracks would file as
  assets. Needs a decision.

### 2.3 Reference: v6 shape (measured)

| Root | archives | circles | notes |
|---|---|---|---|
| `TLMC` | 15,673 | 2,752 | normalised; 98.0% of FLAC match `(NN) [Artist] Title.flac`; 15,645/15,673 date-prefixed |
| `various album` | 1,780 | 168 | scene naming, includes `!MP3/` circle bundles |
| `Other album` | 723 | 162 | |
| `non touhou circle` | 110 | 58 | |
| `temp` | 237 | 75 | **excluded** — intake area |
| `Software` | — | — | **excluded** — player binaries |

`temp/` analysis: 137 of 237 are an IOSYS backfill; 118 of 237 duplicate a
catalog number already under `TLMC`; 92 are new. Its IOSYS subdirectory holds
~80 albums found nowhere else — add to `IncludedSubtrees` if wanted.

Other measured facts: 1,956 archives contain `.cue` (cue-splitting still needed
at scale); 417 are multi-disc; 16 circle directories changed name between v5 and
v6; 14,348 of 14,811 v5 album paths carry over unchanged.

---

## 3. Storage — DECISION

### 3.1 The bottleneck is the enclosure, not the layout

Both HDDs sit behind **one Sabrent Dual SATA Bridge** (`174c:55aa`) on a single
link that negotiated **5 Gbps**, using UAS.

**Measured:**

| | alone | concurrent |
|---|---|---|
| `sda` ST6000NM0115 (6 TB) | 214 MB/s | 213 MB/s |
| `sdb` ST12000NT001 (12 TB) | 283 MB/s | 259 MB/s |
| combined | — | **472 MB/s** |

5 Gbps after encoding is ~500 MB/s, so **two drives already fill the link**. A
third and fourth behind that bridge would add zero read throughput. It is also
literally a *Dual* bridge.

The host is not the limit: root hubs at **10000 Mbps** (where the enclosure is
plugged in, negotiating only 5 Gbps) and **20000 Mbps**, plus Thunderbolt
domains present.

### 3.2 Recommended

1. **4-bay USB 3.2 Gen 2 (10 Gbps) or Thunderbolt enclosure.** Buy before the
   extra drive — the drive adds capacity and redundancy, the enclosure adds the
   throughput.
2. **Two mirror vdevs striped**: `mirror(6,6)` + `mirror(12,12)` = 18 TB usable,
   survives one failure per vdev, reads spread across four spindles. Do not put a
   6 and a 12 in one mirror; do not use RAIDZ across mismatched sizes.
3. **L2ARC on `nvme1n1`** (753 GB free, otherwise idle, non-critical).
   - **`l2arc_noprefetch=0`** — defaults to `1`, which *excludes prefetched
     blocks from L2ARC*. With sequential reads that leaves the cache nearly
     empty. This is the trap.
   - `l2arc_write_max` defaults to 8 MB/s; warming 750 GB at that rate takes
     ~26 h. Raise during warmup.
   - `recordsize=1M` on the HLS dataset; also collapses L2ARC header overhead.
4. **Skip bcache/dm-cache** — block-level, and their sequential-detection
   deliberately bypasses the cache for streaming reads.

ZFS on USB is the shaky part (enclosure resets, ASMedia UAS quirks) — the
strongest argument for Thunderbolt over another USB DAS. On NixOS you will also
need `boot.supportedFilesystems = [ "zfs" ]` and `networking.hostId`; none of
zfs/mdadm/btrfs is installed today.

### 3.3 Capacity

Release is 5.4 TB, archives are `Method = Copy` so extraction is ~1:1.
`/mnt/external_storage` has 4.9 TB free. Extraction only fits because `unlink`
frees each archive as it goes, and only if the destination is on the same
volume. No other volume can hold it (`old_os` 753 GB, `/` 747 GB, `scratch`
195 GB).

---

## 4. HLS layout — OPEN, act before re-transcoding

### 4.1 Segments are scattered

**Measured** on one track's 7 segments in the v5 tree — each is a clean extent,
but they are spread across the whole 6 TB filesystem:

```
seg000 @ block 736,804,327     seg002 @ block  15,634,340   ← 2.7 TB away
seg001 @ block 736,804,647     seg003 @ block  17,061,847
seg006 @ block 736,757,635     seg004 @ block  36,460,488
```

`hls_runner.py` transcodes in parallel across a flat worklist, so ext4
interleaved every track's output with every other's. Playing a track is N seeks,
and there is no sequential run for any prefetch or cache layer to exploit.

**Measured** random small-file read on the USB HDD: **55 files/s, 18.3 ms each**.

### 4.2 Fix: single-file HLS

`ffmpeg -hls_flags single_file` writes one `.m4s` per quality plus a byte-range
playlist (`#EXT-X-BYTERANGE`). Then kernel readahead and ZFS `zfetch` prefetch
the whole track for free — no cache logic, no application changes.

```diff
-  seg_path = os.path.join(dst_root, "segment_%03d.m4s")
+  seg_path = os.path.join(dst_root, "stream.m4s")
+  "-hls_flags", "single_file",
```

File count drops from ~20 million segments to ~650k.

**Blast radius:** `Postprocessor/DashRepackage/file-target.py:42` matches
`segment_\d+\.m4s` and builds a `segment_$Number%03d$` template — DASH
repackaging needs reworking to `SegmentBase`/`indexRange`. `hls_verify.py` and
the backend's playlist handling also assume per-segment files. The exact ffmpeg
invocation is **untested** on this build — try one track first.

Lower-blast-radius alternative: group the transcode worklist **by track** so one
worker writes a track's segments consecutively. Fixes locality only.

**Measured** HLS footprint: 26.7 / 34.7 / 51.0 MiB per track across all four
qualities (mean ~33.5), roughly 20/20/30/30 across 128/192/256/320k. *Estimated*
full catalog: ~162,000 tracks, **~5.2 TiB**. Mean segment 272 KiB, 0% under
32 KiB — so ZFS `special_small_blocks` will not catch them; do not bother.

---

## 5. Embedding generation — OPEN

### 5.1 Silently loses data

| # | Location | Issue |
|---|---|---|
| G1 | `Experimental/utils/loader.py:79-83` | Tracks **shorter than 6 s produce zero chunks** and are skipped with a log line. Catalog is full of SEs, jingles, interludes. |
| G2 | `Experimental/utils/loader.py:79-83` | Trailing partial chunk always dropped — up to 6 s per track, 20% of a 30 s track. |
| G3 | `Experimental/scripts/mert_batched_uuid.py:251-272` | Results written only when `total_chunks == len(results[path])`. Anything still buffered when the loader drains is dropped, with no count. |
| G4 | `mert_batched_uuid.py:268` | `executor.submit(save_tensor, ...)` futures never inspected — save failures vanish. |

### 5.2 Wrong input

| # | Location | Issue |
|---|---|---|
| G5 | `mert_batched_uuid.py:281` (`get_m3u8_process_list`) | Embeds from **lossy HLS AAC**, not source FLAC. Also forces embedding to wait on transcoding. |
| G6 | `loader.py:164` | `T.Resample` constructed per file, rebuilding a sinc kernel every time. Moot once input is pre-decoded 24 kHz. |
| G7 | `loader.py:176` | `load_m4a` writes `temp_{uuid}.flac` into CWD from 8 workers; leaks on crash. |

### 5.3 Operational

| # | Location | Issue |
|---|---|---|
| G8 | `mert_batched_uuid.py:281` | Hardcoded `/mnt/j/PROG/tlmc-etl/.../all_targets.csv`; alternative path commented out. |
| G9 | `Experimental/utils/utils.py:72` | `load_tensor` pickles the **entire** tensor dict — ~40 GB in one file at full scale. `make_embeddings.py` calls it corpus-wide. |
| G10 | three files | `TENSOR_DIR` disagrees: producer writes `Experimental/embeddings/chunked_6s`, `faiss_index_builder.py:10` reads `embeddings/chunked_6seconds/chunked_6s`, `colbert_idx_builder.py:9` reads `embeddings/chunked_6s/`. |
| G11 | `mert_batched_uuid.py` | Writes fp32; values come from `autocast(float16)`. fp16 halves transfer and store for no real precision. |
| G12 | `mert_batched_uuid.py:123` | `torch.compile(mode="reduce-overhead")` uses CUDA graphs; the ragged final batch forces recapture. Pad to fixed size. |
| G13 | `mert_batched_uuid.py:301` | `num_workers=8`/`prefetch_factor=8` tuned for Linux `fork`; the GPU box is Windows (`spawn`, far costlier). With pre-decoded input the loader is nearly idle — 4 is plenty. |

---

## 6. Vector search / serving — OPEN

| # | Location | Severity | Issue |
|---|---|---|---|
| V1 | `Experimental/vector_search/faiss_index_builder.py` | **Critical** | `key_map` is **never persisted**. `pickle` imported, `KEY_MAP_FILE` defined and printed, no `dump`. `faiss_index_search.py:15` opens it immediately. The index maps to integer IDs that mean nothing — any already-built index is unrecoverable. `colbert_idx_builder.py:96` does this correctly. |
| V2 | `Finalizer/PushToDb/Model/TrackEmbedding.cs:16` | **High** | `vector(2048)` **cannot be indexed** — pgvector caps hnsw/ivfflat at 2000 dims. Every query over `EmbeddingMeanMax` is a sequential scan. |
| V3 | `Finalizer/` | **High** | No `CREATE INDEX` anywhere, so even the 1024-dim `EmbeddingMean` is unindexed. |
| V4 | `faiss_index_search.py:76` | **High** | Timestamps use `chunk_idx * 6`, but `loader.py:65` sets step = `chunk_size - overlap` = 4 s. Chunk 30 reported at 180 s, actually at 120 s. Error grows with position. |
| V5 | `faiss_index_builder.py:82-101` | Medium | Training set is the **first 650k vectors in `os.walk` order** — ~1,000 alphabetically-early tracks. OPQ rotation and 16384 IVF centroids fit to a non-representative slice, degrading recall corpus-wide. Reservoir-sample instead. |
| V6 | `TrackEmbeddingProcessor.cs:142-145` | Medium | `Skip(i).Take(n)` on a `List` is O(n²); `AddRange`+`SaveChanges` never clears the change tracker, so EF holds all ~162k entities. |
| V7 | `TrackEmbeddingProcessor.cs:48` | Medium | `MemoryMarshal.Cast<byte,float>` with no length validation — a truncated `.bin` yields a wrong-dimension vector silently. |
| V8 | `colbert_idx_builder.py` | Medium | Annoy stores full fp32 vectors in-index: ~40 GB at 9.7M×1024 before 200 trees of overhead. FAISS IVF-PQ is ~620 MB for the same job. |

### 6.1 Design issues with late interaction on music

- **Document-length bias.** MaxSim is unnormalised in |D|; a 300-chunk DJ mix
  gets 300 draws at the max per query chunk. The catalog is full of these
  (`TOHO COMPLETE BOX`, `NON-STOP-MIX`, eurobeat compilations). The notebook
  normalises votes during candidate generation but the rerank (cell 11) does
  not. **Measured** on synthetic data — query is a real short track:

  | | short real track | 400-chunk noise |
  |---|---|---|
  | maxsim | 0.3669 | **0.3607** ← nearly wins |
  | chamfer | **0.6835** | 0.3109 |

- **Generic chunks are false-positive attractors.** Silence, fade-ins, applause
  and plain drum loops sit near the centre of the space and match everything.
  Text ColBERT gets IDF for free; audio does not. Mitigation implemented as
  `estimate_chunk_weights()`.
- **2 s overlap makes adjacent chunks ~67% redundant** — good for generation
  robustness, wasteful and score-inflating in an index. Build the index from
  non-overlapping chunks.
- **No manifest** records which model, chunk config or pooling produced a given
  `.pt`.
- **UUID coupling.** Embeddings are keyed by `TrackId`, minted fresh in
  `id_assign_and_merge.py:74`. Rebuilding v6 from scratch invalidates the key of
  every existing embedding. **Store a content hash** (xxhash of the FLAC)
  alongside the UUID so vectors survive a re-mint.

### 6.2 Recommended serving shape

```
Stage 0  pooled track vector → pgvector HNSW → top 200        664 MB, filterable
Stage 1  symmetric Chamfer rerank over those candidates       ~18 GiB fp16 store
Stage 2  chunk ANN index — only for "find this moment"        FAISS IVF-PQ ~620 MB
```

pgvector first because **FAISS and Annoy cannot filter** — "similar but not the
same album", "similar within this circle" are trivial in SQL next to existing
metadata. The one case that forces chunk-level *retrieval* (not just rerank) is
finding tracks that share a section but differ overall; pooled recall will never
surface those.

### 6.3 DONE — shipped this session

`Experimental/vector_search/chunk_store.py` and `rerank.py`.

Store layout: `vectors.f16` (contiguous per track) + `index.npz` +
`manifest.json`, mmapped. `gather()` concatenates candidates into one matrix for
batched scoring. `ChunkStore.chunk_start_seconds()` derives timestamps from the
manifest so V4 cannot recur.

Scoring: `chamfer_scores` (symmetric, for track↔track), `maxsim_scores`
(asymmetric, for moment search), plus `estimate_chunk_weights()`.

**Measured** — verified against brute force at 1.19e-07 max abs error, symmetry
exact, self-match ranks first:

```
store size   : 2048 B/chunk → 18.4 GiB extrapolated to 162k tracks
rerank  200  : 42.8 ms/query    (gather 23.9 ms = 85%, matmul+reduce 4.4 ms)
rerank 1000  : 169.6 ms/query
```

The cost is the fp16→fp32 upcast copy, not the math. Cache gathered blocks if it
matters; `chamfer_scores` accepts a pre-gathered matrix for that reason.

---

## 7. Regeneration plan (GPU is on a separate box)

Data is on this machine; the 5090 is in `DESKTOP-OR1S0M8`, same LAN, direct
Tailscale path (no DERP relay).

### 7.1 Key move: transcode to 24 kHz mono before shipping

MERT resamples to 24 kHz mono internally, so anything above that is bytes you
move and the model discards. **Measured:** 101 MiB source FLAC (44.1 kHz stereo
16-bit) → **34 MiB** at 24 kHz mono s16 FLAC, a **3.0× reduction**, lossless with
respect to what the model consumes. Decode runs at **1052× realtime on one core**,
**≥2630× across 20 workers**.

### 7.2 Budget (*estimated* from measured rates)

| Stage | Volume | Time |
|---|---|---|
| Read FLAC + decode (one pass, disk-bound at ~250 MB/s) | 5.4 TB → ~1.4 TB | ~6 h |
| Ship over LAN | 1.4 TB | wired ~3.6 h / WiFi ~7.3 h |
| MERT on the 5090 | ~9.7M chunks | ~1 h |
| Embeddings back (fp16) | ~20 GB | ~5 min |

Pipelined: **~6 h wired** (disk-bound), **~7.3 h WiFi** (link-bound). The GPU is
mostly idle — the opposite of the GCP setup, where GPU time was the cost.

**Measured** link today: **54.7 MiB/s (437 Mbps)** over WiFi, with **1.28× wire
overhead** (1,309 MiB transmitted for a 1,024 MiB payload) — that is retransmission,
i.e. a lossy wireless link. Wired gigabit would be ~110 MiB/s.

Wiring saves only ~1.3 h on the first run, but **halves re-runs** (3.6 h vs
7.3 h) because those skip the 5.4 TB read. After the array rebuild the read drops
to ~2 h and the network becomes the bottleneck in every scenario — so wire it
before iterating.

### 7.3 Recommendations

- **Fold the 24 kHz decode into an existing full-catalog pass** (normalization or
  transcode) — saves a separate 6 h read of the array.
- **Keep the 1.4 TB of 24 kHz audio.** Re-embedding then costs ~3.6 h instead of
  ~10 h. Given G1 alone guarantees at least one redo, this is the highest-value
  1.4 TB on the array.
- Chunk tensors are the source of truth; pooled vectors are a projection. The
  ColBERT-vs-pooled decision does not have to be made before the GPU run.

---

## 8. Suggested order

1. Rebuild the array (enclosure first, then drives, then pool + L2ARC).
2. `sudo mkdir` the destination, re-plan, extract with `unlink`.
3. Resolve E4/E5 (no-audio archives, unreachable content).
4. **Switch HLS to `single_file` before transcoding** — cannot be retrofitted.
5. Normalization + transcode + 24 kHz decode in one pass.
6. Fix G1–G4 (data loss) and G11 (fp16), then run embedding generation.
7. Wire the desktop before iterating on embeddings.
8. Add the pgvector index (V2/V3) and wire up the Chamfer reranker.

---

## 9. Uncommitted / unmerged

- Branch `extract-stage-v6` (`9f28dad`) — **not merged to master**.
- `Experimental/vector_search/{chunk_store,rerank}.py` — untracked at time of
  writing.
- `origin/embedding-gen` is identical to `origin/master` (0 commits either way);
  the branch was already merged and can be deleted.
- Two throughput test files were left in the Taildrop folder on
  `DESKTOP-OR1S0M8` (`throughput_test.bin`, `throughput_test2.bin`, ~1.25 GB).
