# TLMC v6 run record

What was actually done to build the v6 tree, in the order it happened, with the
commands to replay each step and the measurements that justified the decisions.

Written 2026-07-25. Branch `extract-stage-v6`, on top of `d01916f`.

**Scope note.** This records the *preprocessing* run: archive snapshot, extraction,
and the cue-split analysis. Normalization (step 3) and the actual cue split (step 4
execution) have NOT been run. Neither has anything downstream of preprocessing.

---

## 1. Environment

Recorded because several results below are hardware-dependent and will not
reproduce elsewhere.

| | |
| --- | --- |
| OS | NixOS 26.05.889, kernel 7.1.4 |
| Repo commit | `d01916f350ac8a815176a5c6186c648d7816e8d4` |
| Branch | `extract-stage-v6` (2 commits ahead of `master`, unmerged) |
| 7-Zip | 17.05 |
| ffmpeg/ffprobe | 8.1.2 (via `shell.nix`, **not** in the system profile) |
| dotnet | 8.0.423 (via `shell.nix`) |
| Python | `./.venv/bin/python` 3.12, uv-managed |

Storage, both on **one** Sabrent Dual SATA bridge at `usb4/4-2`, 5000 Mbps:

| device | model | serial | role |
| --- | --- | --- | --- |
| `/dev/sda1` | WDC WD122KRYZ-01CDAB0 | B0086E4D | `/mnt/tlmc` — extracted library |
| `/dev/sdb1` | ST12000NT001-3MD101 | ZZ30M01Q | `/mnt/external_storage` — source archives |

`/mnt/tlmc` filesystem UUID `aec267a4-18ad-4342-809d-5c11e2f9439e`.
**Not in `/etc/fstab`** — it will not survive a reboot until added:

```
UUID=aec267a4-18ad-4342-809d-5c11e2f9439e /mnt/tlmc ext4 noatime,nofail 0 2
```

### Tooling prerequisite

`ffmpeg`, `ffprobe` and `dotnet` are absent from the system profile. Every step
below that needs them must run inside the dev shell:

```sh
cd /home/sqz269/prog_other/tlmc-etl
nix-shell            # provides ffmpeg 8.1.2, dotnet 8, 7z, PYTHONPATH, DOTNET_ROOT
```

`shell.nix` is new in this run. It deliberately does **not** provide Python — the
repo's `.venv` carries `mslex`, `pythonnet`, `xxhash`.

---

## 2. Disk initialisation

`/dev/sda` was a new WDC 12 TB, verified blank before any write: **0 power-on
hours, 1 power cycle**, no partition table, no filesystem signatures, first 4 KB
all zeros. Serial was re-checked immediately before partitioning with an abort on
mismatch, because `/dev/sdb` is an identically-sized disk holding the source data.

```sh
sudo parted -s /dev/sda mklabel gpt
sudo parted -s -a optimal /dev/sda mkpart primary ext4 1MiB 100%
sudo mkfs.ext4 -F -m 0 -i 262144 -L tlmc \
  -E lazy_itable_init=0,lazy_journal_init=0 /dev/sda1
sudo mkdir -p /mnt/tlmc && sudo mount -o noatime /dev/sda1 /mnt/tlmc
sudo chown -R sqz269:users /mnt/tlmc
```

Choices worth keeping: `-m 0` drops the 5% root reserve (~545 GB reclaimed on a
data disk); `-i 262144` gives ~45.8M inodes, enough even for a 17M-file HLS tree;
`lazy_*_init=0` builds the inode tables up front rather than in the background
competing with the extraction.

Result: 10.9 TiB usable, 268 MB/s single-stream write.

---

## 3. Extraction

The plan was generated in an earlier session and lives at
`Preprocessor/Extract/output/extraction_plan.output.json`. Its destination was
rewritten from `/mnt/external_storage/tlmc-v6` to `/mnt/tlmc` because the
extraction needs 5.30 TiB and the old destination had only 4.89 TiB free. The
rewrite edited the `ExtractInto` field on each of 18,259 entries and asserted
afterwards that every source `Archive` path still pointed at `sdb`. Backup at
`extraction_plan.output.json.pre-sda.bak`.

Replay:

```sh
# regenerate the plan from scratch (re-reads every archive index, no extraction)
./.venv/bin/python -m Preprocessor.Extract.extract_plan     # prompts for destination

# execute it
echo "" | ./.venv/bin/python -u -m Preprocessor.Extract.extract
```

Run as a detached systemd unit so it survived SSH disconnect:

```sh
sudo systemd-run --unit=tlmc-extract --collect \
  --property=User=sqz269 --property=Group=users \
  --property=WorkingDirectory=/home/sqz269/prog_other/tlmc-etl \
  --property=Nice=5 --property=KillMode=mixed \
  --setenv=PATH=/etc/profiles/per-user/sqz269/bin:/run/current-system/sw/bin:/usr/bin:/bin \
  /bin/sh -c 'echo "" | ./.venv/bin/python -u -m Preprocessor.Extract.extract >> /mnt/tlmc/.extract.log 2>&1'
```

`DELETE_ARCHIVE_AFTER_EXTRACT` was left `False`. The source archives are intact
and the torrent is unaffected.

### Result

**18,259 / 18,259 archives extracted, 0 failures.** 5.3 TB written in 10h18m wall
(4h27m CPU, 5.2 TB read, 5.2 TB written).

Verified afterwards: **0 missing album directories**. Of 18,350 albums, 18,317
contain audio; the remaining 33 were all already flagged `NeedsManualReview` in
the plan and are genuinely audio-free (DVD `.vob`/`.ifo`/`.bup`, `.mkv`/`.mp4`,
scan-only releases).

Corpus census: 151,332 `.flac`, 10,084 `.mp3`, 1,391 `.wav`, 3,270 `.cue`.

### Three failures during setup, and their fixes

Recorded because each will recur on a fresh machine:

1. **`7z` not on systemd's PATH.** It lives in `/etc/profiles/per-user/sqz269/bin`,
   which login shells get and systemd does not. Every archive failed instantly;
   2,849 were journaled as failed before it was caught. Fixed by pinning `PATH`
   on the unit. Because `load_journal()` only honours `Status == "completed"`,
   the failed entries were simply retried — no work was lost.
2. **Root-owned output files.** The first run executed as root (Claude Code was
   under `sudo`), so the journal and `/mnt/tlmc` ended up `root:root` and the
   later `sqz269` service could not append. Fixed by `chown -R sqz269:users` on
   both the output directory and the library. **Test writability as the service
   user, not by reading `ls`** — an `ls` inspection missed this twice.
3. **Empty album directories.** Each failed attempt had already created its
   destination via `os.makedirs` before `7z` ran, leaving 7,823 empty
   directories. Removed with `find /mnt/tlmc -depth -mindepth 2 -type d -empty -delete`.
   Note this also removes ext4's `lost+found`, which must be recreated
   (`mkdir`, `chmod 700`, `chown root:root`) — see §5, it later caused a crash.

---

## 4. Archive hash snapshot (step 0)

Hashes the *source archives* with xxh128 as the cross-release identity baseline.
Must run while the archives exist. Started after extraction; still running at the
time of writing.

```sh
setsid nohup sh -c 'echo "/mnt/external_storage/downloads/TLMC v6" | \
  exec ./.venv/bin/python -u -m Preprocessor.Extract.unextracted_snapshot \
  >> /mnt/tlmc/.snapshot.log 2>&1' < /dev/null > /dev/null 2>&1 &
```

`setsid` rather than systemd, because this session ran as `sqz269` without
passwordless sudo and `Linger=no` means a `--user` unit dies at logout. The
process ends up PPID 1, session leader, no controlling terminal; combined with
`KillUserProcesses=false` it survives SSH close.

Resumable: `filter_archive_list_by_completed` skips already-hashed archives, so
re-running the same command continues where it stopped.

Scope: 18,525 archives — the whole release, including the 266 the extraction plan
excluded. That is intentional; the snapshot is the identity baseline for the
release, not for what was ingested.

**Completed: 18,525 / 18,525 archives, 5.92 TB hashed in 8h57m.** Verified after
the run: no malformed lines, no duplicate entries, and a walk of the release
found 0 archives absent from the snapshot.

**Measured throughput ~175 MB/s median on cold sequential reads, ~8.6 h total.**
An earlier estimate of 5–6 h was wrong; it reused a 283 MB/s figure measured
under different conditions instead of re-deriving it for this workload.

Two anomalies, both benign, both worth carrying into the next release:

- **One album is duplicated in the release under two circle spellings.** The
  same 301 MB archive appears as `various album/[Alice in the Hole ! ]/…` and
  `various album/[Alice in the hole!]/…`, byte-identical (xxh128
  `fe7b139c0d19a21a`). Both are in the extraction plan, so it was extracted
  twice. Circle-alias folding normalises `[IOSYS]`/`[IOSYS] イオシス`-style
  variants but not this pair, which differs by case and internal spacing — add
  it to `CircleAliasOverrides` in `extraction_exclusions.json`.
- **One zero-byte archive** (an art-book entry under `Various Artists`). Already
  excluded from the extraction plan, so it never reached extraction.

The 4 KB read block size in `unextracted_snapshot.py` was investigated and left
alone. Warm-cache it sustains 4,372 MB/s, ~15× what the disk supplies, and a
cold-cache interleaved test (n=8 per arm) put 1 MB reads at only 1.10× the median
of 4 KB — within noise.

---

## 5. Cue split analysis (step 4, analysis only — nothing has been split)

### 5.1 Scanner

```sh
nix-shell --run 'echo "/mnt/tlmc" | ./.venv/bin/python -u -m Preprocessor.CueSplitter.cue_scanner'
```

**18,360 albums scanned, 3,016 flagged**, ~35 min.
Output: `Preprocessor/CueSplitter/output/scanner.potential.output.json`.

`cue_scanner.py` was modified during this run — see §7. Notably it would have
**crashed on `/mnt/tlmc/lost+found`** (root-owned 700, `os.listdir` raising
uncaught `PermissionError`) and, because results were written only at the very
end, produced no output at all. It was killed at 772/18,360 and restarted after
the fix.

### 5.2 Fact extraction

Reads every cue file, counts `TRACK` entries by mode, extracts `FILE` references
and tests whether they resolve. Handles the encodings actually present.

```sh
./.venv/bin/python Docs/v6-run-record/scripts/cue_facts.py   # -> cue_facts.json
./.venv/bin/python Docs/v6-run-record/scripts/datatrack.py   # AUDIO vs data tracks
./.venv/bin/python Docs/v6-run-record/scripts/degen.py       # gb18030 + degenerate cues
./.venv/bin/python Docs/v6-run-record/scripts/final2.py      # -> cue_split_plan.json
```

Cue encodings found: 2,847 utf-8-sig, 302 cp932, **76 gb18030**, 25 cp1252,
6 latin-1. The gb18030 set previously decoded as latin-1/cp1252 mojibake; decoded
correctly, six albums' `FILE` refs turned out byte-identical to the real
filenames — they were never renamed at all. **`gb18030` must precede the latin-1
fallback in the codec list.**

Also found: 31 albums whose cue contains a non-AUDIO `MODEx/2XXX` CD-Extra data
track (32 occurrences). Counting those as tracks inflates the count by one and
was the direct cause of one classification bug.

### 5.3 Classification

Final verdicts, in `Preprocessor/CueSplitter/output/cue_split_plan.json`:

| verdict | albums |
| --- | --- |
| `SPLIT` — resolvable image cue | 1,648 |
| `SPLIT_RESOLVE_BY_DURATION` — stale/renamed `FILE` ref | 35 |
| `SPLIT_FROM_EMBEDDED` — no sidecar cue, embedded CUESHEET | 33 |
| `SKIP` | 1,300 |
| **to split** | **1,716** |

**The decisive predicate**, arrived at independently by two adversarial audits
working on opposite classes:

> A genuine image cue has **exactly one `FILE` statement and more than one AUDIO
> `TRACK`**, and that `FILE` resolves.

Not file counts, not sizes, not the scanner's confidence score. Each auditor
scored 40/40 against their hand-checked sample with this rule.

### 5.4 Classifier errors that the audits caught

Both are recorded because they are easy to reintroduce:

- **False splits, 81 albums (4.83%).** An ordering bug: an `n_audio <= 3`
  fallback fired *before* the `n_audio >= max_tracks` already-split test and had
  no resolve check, so short per-track-ripped EPs were labelled as images.
- **False skips, 25 albums / 346 cue tracks.** Audio files were counted
  recursively across the whole album tree (a nested `Dizzylab DL ver/` edition
  masked one album's un-split image), and the comparison used the *max* per-cue
  track count instead of the sum across cues. That let a **15-disc box set with
  all 15 discs un-split** (`[Casket] 幻想パブの夜`, 103 tracks) pass as "already
  split".

A third error was caught mid-analysis: applying the degenerate-cue rule without a
"not already split" guard inflated the split list to 2,412. Albums whose image was
already deleted, leaving a stale cue, are correct skips.

### 5.5 Cases the splitter must handle

Verified individually by ffprobe, not inferred:

- **7 albums have degenerate cues** — multi-`FILE`, every `INDEX 01 00:00:00`.
  Splitting from the sidecar emits N identical whole-album copies. In
  `[電奏楽団]/2002.05.24 [PWCD-0002] ほしのこえ SOUNDTRACK` the first `FILE`
  *does* resolve, so a naive splitter silently succeeds and writes 12 full-album
  files. These must use the embedded `CUESHEET` instead. Full list in
  `cue_split_plan.json` under `SPLIT_FROM_EMBEDDED`.
- **Multi-image albums**: `[Casket] 幻想パブの夜` (15 discs), `[さんぼん堂] 幻想少女大戦 夢`
  (3), plus two-disc sets and TH13 (main + bonus image). "One image per album
  directory" is false.
- **Over-length images**: TH04 *Lotus Land Story* 108.5 min / 28 tracks and TH13
  *Ten Desires* 116.7 min / 31 tracks are compiled, not 1:1 disc rips. Any
  `duration <= 80 min` sanity check rejects them.
- **Stale `.wav` refs** pointing at files now stored as `.flac`. `cue_facts.py`
  does extension-agnostic stem matching; `cue_splitter.py` must too.
- **`[緋月ノ雫]/2017.05.07 [AKS-0007] PHANTASY STAR SYMPHONY ～裁世輪廻`** will fail:
  cue says `…裁世輪廻.flac`, the file is `…裁世輪廻cue.flac`.
- **`[Casket] Broadside of the notes vol.3`** carries a stray
  `ONNUEHO 3rd Edition.cue` belonging to a different album (all 15 refs absent).
  Must not be used as a split source.
- **Two albums are genuinely missing tracks**: `[BubbleRecords] compass`
  (`1-05. ぺた - Night arfare`) and `sbfr ほしぞらの大演奏会 (復刻版)` (track 06).

**14 of the 33 `SPLIT_FROM_EMBEDDED` albums are the official ZUN soundtracks**
(`[上海アリス幻樂団]`, TH01–TH14) — un-split images with no external cue, invisible
to any cue-file-based scan.

---

## 6. Artifacts

| sha256 (16) | lines | path |
| --- | --- | --- |
| `4da695fb928bfbcd` | 256,043 | `Preprocessor/Extract/output/extraction_plan.output.json` |
| `6e9cfaaab9e1c4e6` | 18,259 | `Preprocessor/Extract/output/extraction_journal.output.jsonl` |
| `3e98f4b278f91745` | 209 | `Preprocessor/Extract/extraction_exclusions.json` |
| `908a2d22a8129917` | 33,906 | `Preprocessor/CueSplitter/output/scanner.potential.output.json` |
| `a58f975b9131ed3d` | 24,129 | `Preprocessor/CueSplitter/output/cue_split_plan.json` |
| `e85abaca8647e5f5` | 142,974 | `Docs/v6-run-record/cue_facts.json` |
| `5a2a95c556866284` | 18,525 | `Preprocessor/Extract/output/unextracted_rar_snapshot.output.json` |

`scripts/` holds the analysis chain in execution order. `scripts/audits/` holds
the scripts the adversarial auditors wrote — kept because they produced the
evidence that corrected the classifier, and their per-album ffprobe measurements
are expensive to regenerate.

### Reproducible vs one-shot

**Reproducible** from the repo plus the source archives: the extraction plan, the
extraction, the cue scan, and the whole cue-split classification chain.

**One-shot**: the throughput measurements in §3–§4. They depend on both disks
sharing one 5 Gbps bridge and will differ on other hardware.

---

## 7. Working tree state

Modified by this run:

| file | change |
| --- | --- |
| `Postprocessor/HlsTranscode/hls_runner.py` | source FLAC no longer unlinked when encodes fail; `DELETE_SOURCE_AFTER_TRANSCODE = False`; error handler no longer raises `KeyError` from inside itself |
| `Postprocessor/HlsTranscode/hls_completed_cleanup.py` | `__main__` guard (it deleted source audio on *import*); fixed global-vs-parameter bug; typed confirmation |
| `Preprocessor/CueSplitter/cue_scanner.py` | skips unreadable directories; `isdir` filter on albums; partial results every 250 albums via atomic replace; 8 worker threads (2 h → 35 min) |
| `Shared/utils.py` | `probe_flac` judges success by exit status, not by whether anything reached stderr; 60 s timeout |
| `shell.nix` | new — ffmpeg, dotnet, 7z, PYTHONPATH, DOTNET_ROOT |

Also built (untracked, generated): `Preprocessor/CueSplitter/CueSplitInfoProvider/bin/Release/net6.0/`
— `CueSplitInfoProvider.dll` + `UtfUnknown.dll`. Verified loadable through
pythonnet: `set_runtime("coreclr")` → `clr.AddReference` → `from CueSplitter import CueSplit`.

### Not from this run — needs review before committing

These appeared in the working tree during the session but were **not** made by the
preprocessing work recorded here. They implement the HLS `-hls_flags single_file`
change, which was deliberately left out of §7's fixes as an architecture decision
rather than a bug fix:

- `Postprocessor/HlsTranscode/hls_assignment.py` (+42/−10)
- `Postprocessor/HlsTranscode/hls_finalizer.py` (+107/−52)
- `Postprocessor/DashRepackage/file-target.py` (+33/−17)
- `Postprocessor/DashRepackage/dash-repackage.py` (+109/−23)
- `Docs/v6-pipeline-fixes.patch` (untracked, 1,254 lines)
- `Postprocessor/HlsTranscode/docker/` (untracked: `Dockerfile`, `ffmpeg-docker`, `README.md`)

They cite measurements from this session's HLS review, so they are almost
certainly deliberate work from a parallel session rather than anything stray — but
they should be reviewed and attributed before being folded into a commit.

---

## 8. Not done

- **Normalization (step 3) — replaced, not run.** The two-pass in-place
  normalizer is superseded by measure-then-apply-at-transcode; see §9.
- **Cue splitting (step 4 execution)** — analysed only. `cue_split_plan.json` is
  the input; `cue_designator.py` and `cue_splitter.py` have not been run, and
  `cue_splitter.py` deletes originals.
- **Extracted filesystem snapshot (step 2)** — deliberately deferred so it
  snapshots the final tree, after normalization and splitting.
- **Everything downstream of preprocessing** — disc identification, info scanner
  phases, artist identification, aggregation, HLS, DASH, DB push.
- **`libfdk_aac`** — unobtainable from nixpkgs (unfree, not redistributable in
  binary form). `ffmpeg-full` ships without it. `Docs/STEPS.md` and
  `hls_assignment.py` both require it. Either build locally with `withFdkAac` and
  `allowUnfree`, or fall back to ffmpeg's native `aac`. Blocks the HLS stage.
- **`hls_verify.py` and `finalize_filelist.py`** remain syntax-broken stubs
  (`hls_verify.py` ends mid-assignment at line 20; `finalize_filelist.py:30` has a
  `def` with no colon or body). Neither can be imported.
- **Branch `extract-stage-v6` is unmerged** and everything in §7 is uncommitted.


---

## 9. Loudness: measured once, applied at transcode

The original stage measured every FLAC with `loudnorm` and then rewrote it in
place. That is replaced by measuring with `ebur128` and applying a static gain
while transcoding to HLS. The source audio is never modified.

### Why

- **`loudnorm` analysis is the cost, not the decode.** Measured here: plain FLAC
  decode runs at 1753x realtime, decode+`loudnorm` at 26x, decode+`ebur128` at
  156x. For 166,787 tracks that is ~8h instead of ~45h.
- **`loudnorm`'s machinery is for a problem this corpus does not have.** Its
  dynamic-fallback limiter and `target_offset` exist to push quiet broadcast
  material up against a peak ceiling. Measured over 1,044 tracks: the true-peak
  clamp binds on **0%**, and exactly **1 track** needs any boost. Everything else
  only ever gets turned down.
- **A plain static gain is exact.** `min(target_I - measured_I,
  target_TP - measured_TP)` hit the target on 10/10 sampled tracks. Verified
  end-to-end: a track measured at -8.20 LUFS took -5.800 dB and landed at exactly
  -14.00 LUFS with 3.8 dB of peak headroom.
- **The second pass was the only irreversible step in the pipeline.** It is gone.

### Why not at serve time

Applying gain in the client would be better still, and is what Spotify does --
they measure at upload and never modify the audio. It is not available to a
browser client serving HLS:

- `HTMLMediaElement.volume` is not settable on iOS; writes are ignored and it
  always reads 1.
- The documented workaround, Web Audio, cannot see HLS audio in WebKit:
  `createMediaElementSource()` on an HLS stream yields silence. Open WebKit bug
  231656, affects desktop Safari and every iOS browser.

Both paths are closed on Apple platforms, so the gain is baked into the AAC at
transcode time instead. The FLAC stays untouched.

### Does loudness contaminate MERT embeddings?

Tested on the RTX 5090, since MERT's feature extractor has `do_normalize: false`
and raw amplitude reaches the model:

| test | result |
| --- | --- |
| same track, +/-24 dB | cosine 0.9903 - 1.0000 |
| same track, +/-6 dB (realistic spread) | 0.9986 - 0.9990 |
| different tracks, same loudness | 0.9175 (0.8357 - 0.9689) |

A 24 dB shift moves a track 0.0097 in cosine distance; different tracks sit
0.0825 apart, so the gain effect is ~8x smaller than the musical signal. Over 24
clips spanning 41 dB, re-normalising changed pairwise-similarity rankings by
rho = 0.9893 and left the top-1 neighbour unchanged for 20/24.

The corpus is tighter than that test: median -7.0 LUFS, p10 -10.3, p90 -5.2, a
**5 dB interdecile spread**, where the effect is ~1%.

Normalising does not remove the correlation anyway: 54 embedding dimensions
correlate with loudness at |r|>0.7 on natural audio, and still 42 after
normalising to a common target. What MERT encodes is production style -- loud
masters are compressed, limited and bright -- not level. Attenuating a
brickwalled track does not make it sound un-brickwalled.

**Conclusion: embeddings do not need normalised input, and no longer depend on
the normalization stage at all.**

### Open choices

- **Target is -14 LUFS / -1.0 dBTP** (`loudness_measure.py`), matching Spotify,
  YouTube, Tidal and Amazon. The pipeline previously targeted -24, the EBU
  *broadcast* figure, which would leave the library conspicuously quiet. Cheap to
  change now that it lives in the transcode.
- **Per-track gain, not album gain.** Spotify normalises per album during album
  playback so quiet interludes stay quiet relative to their neighbours. Baking
  per-track gain in loses that. The measurement file has what album gain needs;
  it is a grouping decision, not more measurement.
