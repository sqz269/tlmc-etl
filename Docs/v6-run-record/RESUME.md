# Where the v6 run stands

Branch `extract-stage-v6`, working tree clean, nothing running, nothing pushed.

## THE LIBRARY ROOT IS `/mnt/tlmc/TLMC v6`

Not `/mnt/tlmc`. Every stage that prompts for a root wants the full path
including the `TLMC v6` component, and it has a space in it.

The release now sits one level down from the mount point so the disk can hold
v7 beside it, and so paths carry a named release-root component. The backend's
`EtlDataLoader/Operations/MpegDashPlaylistProcessor.cs` reconciles HLS and DASH
paths produced on different machines by anchoring on exactly that component
(`StripTlmcPrefixRoot(path, "TLMC v5")`), and the flat layout gave it nothing to
anchor on. The v5 reference tree on `/mnt/tlmc-v5` has the same shape.

## Completed and verified

| stage | result |
|---|---|
| Archive extraction | 18,259 / 18,259, 0 unextracted |
| Cue splitting | 1,850 albums; the 3 logged failures are resolved (stale log) |
| Loudness measurement | 178,687 / 178,727 files |
| Disc identification | 580 albums / 1,263 discs, contract clean |
| Info scanner phase 1 | 18,360 albums, 164,287 tracks, 19,043 discs |
| Info scanner phase 2 | 18,360 albums, 164,287 tracks |
| Info scanner phase 3 | 18,360 albums, 164,287 tracks, 0 contract violations |
| Artist scanner | 2,943 circles, 196 collaborations, 0 albums unresolvable |
| ID assignment & merge | 18,360 albums / 19,043 discs / 164,287 tracks / 121,464 assets, 323,154 ids, 0 collisions |

Phase 2 flags 602 tracks (0.4%). Phase 1 flags 842 albums (4.6%). Phase 3 leaves
78 discs carrying duplicate track numbers, all duplicated in the source tags.

Section 7 output is `Processor/InfoCollector/Aggregator/output/assigned_megered.json`
(147 MB), which is what the HLS stage and the .NET EtlDataLoader consume. 101 albums
carry zero tracks -- 49 hold no audio at all (band scores, DVD releases, a
password-protected archive) and 52 are container albums still in the disc queue.
They are still emitted, with an AlbumId and their assets, so decide at load time
whether an album with no tracks should reach the database.

## Rerunning

Outputs under `Processor/InfoCollector/AlbumInfo/output/` are all current and
already point at the post-move paths. Every artifact stores absolute paths, so
moving the library again means rewriting all 22 of them -- 2.36 M occurrences
across ~1 GB. A plain prefix substitution does it, but it is not idempotent:
guard on the target prefix being absent before running one.

Order matters. `disc_auto_classify` writes the artifact from scratch and
`disc_duration_guard` merges into it, so running them the other way round
silently discards the guard's work:

    disc_scanner.py -> disc_auto_classify.py -> disc_duration_guard.py
    info_scanner_ph1.py -> info_scanner_ph2.py

The k8s backend deployment mounts the library identity-mapped -- `hostPath` and
`mountPath` must both equal the library root, because the backend stores absolute
paths in `HlsPlaylistPath` and opens them straight off the filesystem. That pair
lives in `tlmc-player/K8s/Backend/backend-api-depl.yaml` and now reads
`/mnt/tlmc/TLMC v6/`.

`info_scanner_ph1.py` reuses `info_scanner.filelist.output.json` and
`info_scanner.probed_result.output.json` whenever they exist. Delete both if the
library moved. It now refuses to start when the cached file list disagrees with
the disc artifact, and names the offending paths.

ffmpeg is not on the default PATH; use `nix-shell` or prepend the store path.
The scripts that read a path from stdin can be fed with
`echo "/mnt/tlmc/TLMC v6" | ...` -- quote it, the path contains a space.

## Open decisions — these need a human, not more analysis

1. **49 container albums.** DVD-Rs and box sets holding several separate
   releases. 14 of them are contiguous 1..N box sets and look mechanically
   resolvable, but one is `TOUHOU SKY ARENA BATTLE SOUNDTRACKS`, which embedded
   tags show is 10 separate releases plus a bonus disc. So the rule is not safe
   unsupervised.
2. **145 albums** the duration guard judged single-disc, and **6** genuinely
   ambiguous (duplicate or non-contiguous disc numbers).
3. **Five further filename-parsing rules** for the remaining 602 flagged tracks.
   Three measure 0.000% false positives (`D-NN-title`, `NN. title`, `NNN.ext`);
   three measure 0.23-1.09% (`NN - title`, `NN_title`, `NN title`). They only
   fire where a tag is absent, so nothing can contradict them. Not applied.
4. **The 10-character cap on a convention name** drops real ones —
   `ComicCreation18`, `Comic Treasure 8`, `砲雷撃戦！よーい！38`. Raising it is not
   safe as-is: of the 65 albums it would newly affect, many are labels
   (`Studio Lepus`) or catalog numbers (`KONAMI - KFC-1807-1`), not conventions.
5. **Thumbnails.** 545 albums have none named `folder`/`cover`; 214 have no image
   at all, 331 have one under another name (`jacket` 18, `front` 11). Widening
   `THUMBNAIL_FILE_NAMES` recovers about 29.

## Known-bad data in the release itself, not our doing

- **40 audio files are broken upstream.** Each matches its size inside the source
  `.7z`, so extraction was faithful. 18 are `__MACOSX/._` AppleDouble stubs that
  are not audio; one is 0 bytes; the rest are 6-11 KB FLAC fragments.
  `[TTL SOUND] TTL EUROBEAT VOL. 18` is 7 of 7 and yields an empty album.
- **3 empty album directories**: `[Aqua Style-ひえろぐらふ]/2017.05.07 フォークロア-天弓の章- [例大祭14]`
  and two under `[Baguettes Ensemble]`.
- **105 `.getxfer.*` aborted downloads**, including 6 in
  `[C88] TOHO CLUB MUSIC ESSENTIAL ver.2.0`, which is an incomplete rip.
- **13 album names have unbalanced brackets.** Four lose a catalog number that
  cannot be parsed at all, because the opener and closer are different bracket
  types: `{5150-A003]`, `{KWL-0011`, `{DVSP-0264~5`, `[HKMP-OTO25[`.

## Not blocking, but worth knowing

`AlbumArtist` is the bracketed directory name (`[EastNewSound]`) for 99.9% of
albums. That is deliberate, not a defect: `artist_scanner_ph2` keys the circle
list on the raw directory name and `id_assign_and_merge.match_circle_list` joins
on it lowercased. The display name lives in the circle record's `name` field.
Do not "clean" it without changing both sides.

HLS transcode is still blocked on an ffmpeg with `libfdk_aac`; nixpkgs ships
`ffmpeg-full` without it. `shell.nix` documents the opt-in override.
`hls_verify.py` and `finalize_filelist.py` are still syntax-broken stubs.
