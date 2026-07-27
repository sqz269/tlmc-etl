# Where the v6 run stands

Written before a planned shutdown to reconfigure the disk array. Branch
`extract-stage-v6`, working tree clean, nothing running, nothing pushed.

## Completed and verified

| stage | result |
|---|---|
| Archive extraction | 18,259 / 18,259, 0 unextracted |
| Cue splitting | 1,850 albums; the 3 logged failures are resolved (stale log) |
| Loudness measurement | 178,687 / 178,727 files |
| Disc identification | 580 albums / 1,263 discs, contract clean |
| Info scanner phase 1 | 18,360 albums, 164,287 tracks, 19,043 discs |
| Info scanner phase 2 | 18,360 albums, 164,287 tracks |

Phase 2 flags 602 tracks (0.4%). Phase 1 flags 842 albums (4.6%).

## Rerunning after the array work

Outputs under `Processor/InfoCollector/AlbumInfo/output/` are all current. If the
library's mount path changes, everything must be regenerated, because every
artifact stores absolute paths.

Order matters. `disc_auto_classify` writes the artifact from scratch and
`disc_duration_guard` merges into it, so running them the other way round
silently discards the guard's work:

    disc_scanner.py -> disc_auto_classify.py -> disc_duration_guard.py
    info_scanner_ph1.py -> info_scanner_ph2.py

`info_scanner_ph1.py` reuses `info_scanner.filelist.output.json` and
`info_scanner.probed_result.output.json` whenever they exist. Delete both if the
library moved. It now refuses to start when the cached file list disagrees with
the disc artifact, and names the offending paths.

ffmpeg is not on the default PATH; use `nix-shell` or prepend the store path.
The scripts that read a path from stdin can be fed with `echo /mnt/tlmc | ...`.

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
