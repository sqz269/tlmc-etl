# Phase 1 manual-review triage — `Unidentified Tracks`, `No Asset Files`

Scope: the 842 albums (of 18,360) that `info_scanner_ph1.py` flagged.
Everything below was measured from `info_scanner.phase1.output.json`,
`info_scanner.probed_result.tmp_lines.output.json` (durations),
`disc_manual_checker.output.json`, `disc_auto_classify.review.output.json`,
and direct read-only listings of `/mnt/tlmc`. No repo file or library file was modified.

Reason counts re-derived (matches the brief):
`No Thumbnail` 545, `Unidentified Tracks` 280, `No Asset Files` 161, `No Tracks` 101; 842 albums flagged.

---

## 0. What is actually at stake

`Processor/InfoCollector/Aggregator/id_assign_and_merge.py:35` —
`move_unassigned_tracks_to_asset()` appends every `UnidentifiedTracks` entry to the album's
`Assets` list and then empties the list. So an unidentified track is **not dropped from the
dataset**; it is demoted from a playable/tagged track to an opaque asset file. The cost of a
mis-triage is therefore "content invisible as music", not "content lost".

The 280 albums hold **14,199 unidentified audio files / 826.1 h** (20 of those 14,199 have no
probe duration, so the hour figure is a floor).

---

## 1. Cause table for the 280 `Unidentified Tracks` albums

Classification is per *directory group* (unidentified tracks grouped by their containing
directory, 1,296 groups in total), from the actual directory names plus two measured signals:
(a) duration-vector equality against an identified disc, (b) fraction of normalised title stems
that also appear among the album's identified tracks. "albums (primary)" attributes each album to
the cause of its largest group, so that column sums to 280; the tracks/hours columns are exact
per-group sums.

| cause | albums (primary) | dirs | tracks | hours |
|---|---:|---:|---:|---:|
| separate disc / sub-release dir — **all already in the disc review queue** | 48 | 434 | 7051 | 297.7 |
| CD-EXTRA / data-track / DVD-side content (`CD EXTRA`, `Data track`, `CD DATA`, `DVD n`, `データトラック`) | 21 | 279 | 2463 | 234.2 |
| alternate-format copy (`mp3`/`wav`/`WAVE`/`Hi-Res`/`24_882`/`48k-24`/`MP3データ`) | 44 | 264 | 2461 | 176.9 |
| DAW project stems / sample library (`.logicx/Media`, `Stem`, `Samples`, `KICK`/`SNARE`/`LOOP`…) | 4 | 33 | 713 | 2.4 |
| duplicate of identified tracks (≥80 % of titles already present on a disc) | 51 | 55 | 460 | 32.5 |
| bonus / extra / omake / special-contents / postcard content | 75 | 141 | 440 | 38.3 |
| instrumental / off-vocal mirror (`Instruments Track`, `Ex` = inst., `ボーカルパートなし`) | 9 | 43 | 349 | 26.8 |
| alternate edition (`web ver`, `booth ver`, `Dizzylab ver`, `bandcamp ver`, `DL ver`, `web fix`) | 10 | 17 | 107 | 8.4 |
| unclassified — small extras, hand-checked below | 7 | 10 | 75 | 1.9 |
| voice drama / SE / PC system voice | 2 | 10 | 47 | 4.4 |
| junk (`__MACOSX`) | 2 | 2 | 18 | 0.0 |
| tracks at album root while the only disc is a subdirectory | 7 | 8 | 15 | 2.8 |
| **TOTAL** | **280** | **1296** | **14199** | **826.1** |

Read this as: **94.7 % of the unidentified tracks (13,443 / 14,199) belong to albums that are
already sitting in the disc review queue.** Only 565 tracks are in albums the disc artifact has
already resolved, and 191 are in albums no disc stage ever looked at.

Same numbers split by pipeline state:

| bucket | albums | unidentified tracks |
|---|---:|---:|
| in `disc_auto_classify.review.output.json` (pending human disc decision) | 200 | 13,443 |
| resolved in `disc_manual_checker.output.json` (artifact assigned its discs) | 73 | 565 |
| in neither (disc scanner never saw them as multi-disc) | 7 | 191 |

---

## 2. Suspected *real* discs that disc detection missed

Method for shortlisting: only the 80 albums **not** in the review queue can need separate action
(the other 200 are decided by finishing the queue). Within those 80 I looked at every group that
is not a duration-identical or title-identical mirror, and used one hard piece of evidence —
**does the directory carry its own `.cue` / `.log` / `.accurip`?** An EAC log is proof the
directory was ripped as a physically separate disc. Seven artifact-bucket groups do; three of the
remainder are structurally unambiguous on inspection.

### High confidence — a physically separate disc exists and is unidentified

| # | album | directory | tracks | duration | evidence |
|---|---|---|---:|---:|---|
| 1 | `/mnt/tlmc/[Diverse System]/[C69] Diverse System — OURPATH： Diverse Style The Best 2000-2005 {DVSP-0028~31} [CD-FLAC] (20%)` | `BEMANI REMIX, Diverse Style the BEST` | 64 | 66 m | own `BEMANI REMIX, Diverse Style the BEST..log`; sits beside `disc 1`–`disc 4` which are registered discs. Caveat: every track is 59–63 s except one at 221 s, and files are named `Track01…Track64`, so this is a **1-minute-preview sampler disc**, not 64 full songs. It is still a separate ripped disc. |
| 2 | `/mnt/tlmc/[Glassy：oceaN]/2019.12.31 [GLOV-0020~22] GLASSY：MEMORIES [C97]` | `Bonus Disc` | 3 | 15 m | own `…-Bonus Disc-.log`; catalogue `GLOV-0020~22` is three numbers but only `Disc 1`/`Disc 2` are registered — this is the third. |
| 3 | `/mnt/tlmc/[Melonbooks Records]/2018.12.30 [MBCD-0037~8] 東方 Compilation CD-BOOK 萃星霜 弐 –限定版– [C95]` | `SPECIAL DISC -月-` | 2 | 8 m | own `.cue`; siblings `DISC 1 -星-` / `DISC 2 -霜-` are discs. |
| 4 | `/mnt/tlmc/[Melonbooks Records]/2018.08.10 [MBCD-0034~5] Compilation CD-BOOK 東方スチームパンク [C94]` | `Special Disc` | 2 | 7 m | own `.cue`. |
| 5 | `/mnt/tlmc/[Melonbooks Records]/2020.05.02 [MBCD-0074~5] Compilation CD-BOOK 東方 玉手箱 -限定版- [C98]` | `Special Disc` | 2 | 7 m | own `.log`. |
| 6 | `/mnt/tlmc/[冷猫] TUMENECO/2011.08.13 [TMNC-010] 現夢 -genmu- [C80]` | `現夢おまけCD` | 3 | 3 m | named "bonus CD", contains its own `少女秘封倶楽部.pdf`; siblings `現夢 -genmu- Disc1/Disc2` are discs. No log, but structure is unambiguous. |

### High confidence — the *main* album content is the unidentified part

Disc detection picked a subdirectory as the album's only disc and left the actual CD rip outside it.

| # | album | unidentified | registered disc | evidence |
|---|---|---|---|---|
| 7 | `/mnt/tlmc/[Diverse System]/[M3-30] Diverse System — Escape from 10 minutes {DVSP-0085} [CD-FLAC]` | 3 flac at album root, 10 m, with `Diverse System - Escape from 10 minutes.cue` **and** `.log` | `Extra` (6 mp3) | the cue/log prove the root files are the CD; a 6-track mp3 `Extra` folder became the sole disc. Clear inversion. |
| 8 | `/mnt/tlmc/[东方新春宴]/2024.02.11 [XCY-00] 童梦~Innocent Dreams` | 2 flac at root, 7 m (`童梦～Innocent Dreams` + its Instrumental) | `bonus` (4 mp3 named `demo…`, `XCY-demo6`) | the release is the 2 root flacs; a folder of demos became the disc. |

### Medium confidence — needs a human eye, small volume

| # | album | directory | tracks | duration | reasoning |
|---|---|---|---:|---:|---|
| 9 | `/mnt/tlmc/[東方耳かき屋]/2023.04.30 超貴重!霊夢・魔理沙に…` | album root | 1 | 58 m | root holds one 58-min flac; the registered disc `Vocal omly` holds 5 flac also totalling 58 m. One of the two is the primary product and the other the variant; the pipeline chose the variant. |
| 10 | `/mnt/tlmc/[Krik／Krak]/Free` | album root (2 mp3, 5 m) + `2008.01.02 … オフィーリアの涙 [WEB-WAV]` (1 wav, 6 m) | 3 | 11 m | this "album" is a container of two free web releases plus two loose singles; only one sub-release became a disc. Needs restructuring, not a disc flag. |
| 11 | `/mnt/tlmc/[A-One (A1) - Eurobeat]/A-One (A1) - Eurobeat` | album root | 3 | 10 m | container album holding four sub-releases as discs; three standalone single mp3s sit at root. Same shape problem as #10. |
| 12 | `/mnt/tlmc/[岡垣正志＆フレンズ]/2010.08.14 [KPCR-104S] JUPITER -the absolute- [C78]` | `JUPITER -the absolute- Present Disc` | 1 | 5 m | named "Present Disc" with its own `folder.jpg`; a real one-track giveaway disc. |
| 13 | `/mnt/tlmc/[岡垣正志＆フレンズ]/2011.05.08 [KPCR-113S] APHRODITE -SCARLET FANTASIA VII- [例大祭8]` | `APHRODITE … Present Disc` | 1 | 7 m | same pattern. |
| 14 | `/mnt/tlmc/[夢想夏月郷]/2021.03.21 [HICDS-0016] アリスマジック …` | `Disc 2/未使用曲等` | 3 | 9 m | `Disc 2` exists but holds only MIDI files plus this subfolder, so it never qualified as a disc; the 3 flac are genuine unused-track content. |
| 15 | `/mnt/tlmc/[ShibayanRecords]` Instrumental Vol.1 / Vol.2 / Vol.3 | `Assortment of sense`, `Crystal Stone`, `A procura de felicidade`, `TOHO BOSSA NOVA 3` | 1+1+1+2 = 5 | 19 m | these albums group instrumentals by source album; source-album folders holding only 1–2 tracks were not promoted to discs while their 3–4-track siblings were. Real album content, inconsistently handled. |

**Total actionable content in items 1–15: 98 tracks / 232 min across 17 albums**, of which the
single 64-track preview-sampler disc is 65 % of the tracks.

### Explicitly NOT missed discs (checked and dismissed)

- `[SYNC.ART'S] REQUIEM Re：miniscence` `Ex` (11 tracks, 55 m) — every filename ends `inst.` and
  matches `Disc2`'s titles one-for-one. Instrumental mirror.
- `[荒御霊] Listen 10` `DATA DVD SIDE/listen 10 Project/wav` (101 tracks, 112 m) and
  `Various Artists/Touhou Genso Wanderer -FORESIGHT-` `wav` (89 tracks, 326 m) — duration-identical
  to the registered `mp3` disc, file for file. Format mirrors.
- `[苺坊主] 東方夢玄稗叉` `disc1/flac+cue (for game rewards)` (29 tracks, 75 m) — duration-identical
  to `disc1`. Duplicate rip.
- `[FELT]` `… Special Contents/Instruments Track` in FELT-013 / -019 / -025 (23 + 22 + 24 = 69
  tracks) — instrumental mirrors (see §5 for the consistency note).
- `[幻想グリモワール] 高野史録` `BOOTH ver` (11), `[ヴェクセルドミナンテ] Bestworks` `24_882` (7),
  `[Whiskycat Work] 褌祭` `PCシステムボイス` + `携帯用着ボイス` (27 wav, 1 m total) — mirrors and SE.
- `[街角麻婆豆] お次は何処で踊りましょうか` and `[SPACELECTRO] TOHO 100EDM` root files — both are
  literally named クロスフェードデモ / `TOHO 100EDM DEMO`. Crossfade demos, correctly excluded.
- The 7 "neither" albums (191 tracks) are all CD-EXTRA/data-partition mp3: two duplicate copies of
  `[R-note] 東方M-1ぐらんぷり～Sound Collection～` (89 mp3 each under `CD EXTRA/…` — game-show
  intro/BGM/judge stingers, most under 60 s), `[NTconfess] 那由多の想いは…` `Other/DATA/PIX` (4),
  two `[salvation by faith records]` `Data track/OMAKE` (3 each), `[sbfr] マニアックすぎて…`
  `Extras/MP3` (2), `[Re：SPEC] SPELUNKER` `01. data track/DATA` (1). None is a disc.

---

## 3. Overlap with the disc review queue

- **200 of the 280** unidentified-track albums are exactly the 200 albums in
  `disc_auto_classify.review.output.json` — the overlap is 100 % of the queue. They carry
  **13,443 of the 14,199 unidentified tracks (94.7 %)**. Cause: these albums are absent from the
  disc artifact, so `Phase01.process_one` treats only the album root as a disc and files every
  subdirectory file as unidentified. **No separate action: working the queue resolves them.**
  Queue reasons for those 200: `duration guard: single disc after guards` 145,
  `container: more than 5 audio directories, likely several releases` 49,
  `duplicate disc numbers derived from names` 4, `non-contiguous disc numbers` 2.
- **73** are in `disc_manual_checker.output.json` (565 tracks) — the artifact assigned their discs
  and the leftovers are what §1/§2 classify. This is the only bucket where a genuine miss can hide,
  and §2 items 1–8 and 12–15 all come from it.
- **7** are in neither artifact nor queue (191 tracks) — all CD-EXTRA data-partition content,
  listed at the end of §2. **No action.**
- The 101 `No Tracks` albums split 52 in the queue / 49 in neither, and the 52 are a strict subset
  of the 280 unidentified-track albums (`unid ∩ notracks = 52`). Confirms the brief: nothing lost.
- `unid ∩ noasset = 0` — the two flags never co-occur, by construction.

---

## 4. The 161 `No Asset Files` albums — verdict: harmless

Measured by walking each of the 161 directories on disk and counting files whose extension is not
in `{flac, mp3, wav, wv, m4a}`:

- **0 of 161** albums contain any non-audio file. The flag is literally true, not a scanner bug.
- Reason combinations: 158 × (`No Asset Files`, `No Thumbnail`), 3 × (+ `No Tracks`). Every
  no-asset album is necessarily also a no-thumbnail album, so these 161 are a subset of the 545 —
  they are *not* 161 additional problems.
- 158 of them hold 837 tracks (608 flac, 205 mp3, 23 wav, 1 wv); 64 are single-track releases,
  median well under 5 tracks. These are web/download singles shipped without artwork. **Harmless.**
- The 3 with zero tracks are **completely empty directories** and are the only real finding here:
  - `/mnt/tlmc/[Aqua Style-ひえろぐらふ]/2017.05.07 フォークロア-天弓の章- [例大祭14]` — empty
  - `/mnt/tlmc/[Baguettes Ensemble]/[例大祭12] Baguettes Ensemble — Toho Jazz Sessions type SPB {BE-011} [MP3]` — empty
  - `/mnt/tlmc/[Baguettes Ensemble]/[C94] Baguettes Ensemble — Toho Jazz Connection Vol.4 [CD-FLAC]` — contains only an empty `Scans/` directory

  These 3 are part of the 49 `No Tracks` albums that hold no audio at all.

---

## 5. Two adjacent defects found while triaging (not `Unidentified Tracks`, but same root cause)

**(a) Three DAW project directories were registered as discs — 209 phantom tracks in the output.**
Scanning `disc_manual_checker.output.json` for disc paths matching `.logicx` / `Stem` / `Samples` /
`Media/Audio Files`:

| album | disc path | "tracks" |
|---|---|---:|
| `/mnt/tlmc/[灵社幻声]/2023.10.04 [LS-001] 波隙漂浮 [武漢TH7]` | `Dizzylab DL ver/GIFT/无昼之昼.logicx/Media/Audio Files` | 176 |
| `/mnt/tlmc/[Pure Highball]/2022.05.08 [CDNO-0001] Circus Delight [例大祭19]` | `bonus/シュレディンガートーク/Stem` | 17 |
| `/mnt/tlmc/[Pure Highball]/2022.05.08 [CDNO-0001] Circus Delight [例大祭19]` | `bonus/アストロノミーズイデア/Stem` | 16 |

This is the opposite error to a missed disc and is worse: 209 stem files will be published as
album tracks. The 波隙漂浮 case turns a 4-track release into a 180-track one.

**(b) Same folder pattern treated inconsistently across sibling albums.** Not lost content, but the
output will look arbitrary:
- `[FELT]`: `… Special Contents/Instruments Track` is a registered disc in **26 of 31** FELT albums
  in the artifact, but unidentified in FELT-013, FELT-019 and FELT-025 (the three that also have a
  real `Disc 1`/`Disc 2`). 69 tracks. (FELT-001 and FELT-031 have no such folder.)
- `[WAVE] ELEM.FABLE`: `CDExtra/wave0001` and `wave0002` are discs; `CDExtra/wave0003/エクストラミュージック` (4 files) is not.
- `[Presence∝fTVA] SP4`: `CD DATA/data/phase2` and `phase3` are discs; `phase1` (3) and `phase4` (1) are not.
- `[ShibayanRecords]` Instrumental Vol.1–3: 3–4-track source folders are discs, 1–2-track ones are not (§2 item 15).

---

## 6. Prioritised action list

Ordered by tracks at stake.

**Fix — real defects (209 phantom tracks added + 98 real tracks orphaned + 69 inconsistent)**

1. **209 tracks — reject DAW-project directories as discs.** Remove the three `.logicx`/`Stem`
   discs in §5(a) from the disc artifact and add a guard so `Media/Audio Files`, `Stem`, `Samples`
   and `.logicx`/`.band` paths never become discs. Highest-value single fix: it is the only place
   where the pipeline **adds** wrong tracks rather than dropping real ones.
2. **64 tracks — `[Diverse System] OURPATH` `BEMANI REMIX, Diverse Style the BEST`.** It has its own
   EAC log so it is a separate disc, but the tracks are 60-second previews named `Track01…Track64`.
   A human must decide: register as disc 5, or keep it as an asset. Do not automate this one.
3. **69 tracks — FELT `Instruments Track` consistency.** Decide once whether that folder is a disc
   or a bonus asset, then apply to all 31 FELT albums. Currently 26 say disc, 3 say asset.
4. **14 tracks across 7 albums — the genuine bonus discs** (§2 items 2–6 plus the two 岡垣
   `Present Disc` entries, items 12–13): add them to the disc artifact. Each is evidenced by its own
   `.cue`/`.log` or by an unambiguous name plus sibling discs.
5. **5 tracks — the two inverted albums** (§2 items 7–8): `Escape from 10 minutes` and
   `童梦~Innocent Dreams`. The root rip is the album; the folder that became the disc is a bonus.
   The cue/log at album root make this mechanically detectable — worth a rule: *if the album root
   holds audio plus a `.cue`/`.log`, the root is a disc.*
6. **15 tracks — the odds and ends** (§2 items 9, 10, 11, 14, 15, plus the `[WAVE]` and
   `[Presence∝fTVA]` inconsistencies from §5(b), 8 more tracks). Low value; batch them or
   deliberately leave them as assets.

**Do nothing — correctly-handled noise (this is the bulk)**

- **200 albums / 13,443 tracks (94.7 % of the whole `Unidentified Tracks` bucket)** — already in
  the disc review queue. They are flagged only because they have no disc artifact entry yet. Do not
  triage them separately; finishing the queue clears them.
- **2,461 tracks** of alternate-format mirrors (`mp3`/`wav`/`Hi-Res` copies of a registered disc,
  most verified duration-identical file-for-file). Correct to leave as assets.
- **2,463 tracks** of CD-EXTRA / data-track / DVD-side content.
- **460 tracks** that duplicate ≥80 % of an identified disc's titles, **349** instrumental/off-vocal
  mirrors, **440** bonus/omake/postcard extras, **107** alternate-edition mirrors, **47** voice
  drama / SE, **18** `__MACOSX` junk.
- **7 albums / 191 tracks** in neither the artifact nor the queue — all CD-EXTRA data-partition mp3.
- **158 of the 161 `No Asset Files` albums** — audio-only releases, verified on disk. They are a
  subset of the 545 `No Thumbnail` albums and add no new work.
- **`No Thumbnail` generally** — orthogonal to everything above; 161 of the 545 are these audio-only
  albums.

**Trivial cleanup**

- 3 completely empty album directories (§4). Delete or re-acquire.

**Net effect on the human's queue:** of the 280 `Unidentified Tracks` albums, **200 need no separate
look**, 7 more are provably noise, and of the remaining 73 only **17 albums** (§2) carry anything
worth a decision, plus 5 albums with the consistency problems in §5(b) — and 2 albums (3 discs)
where the pipeline invented tracks that must be removed.

---

## Measurement caveats

- 20 of the 14,199 unidentified files have no entry in the probe results, so their duration counts
  as 0; all reported hour figures are floors.
- The stem-similarity signal normalises away bracketed artist tags, leading track numbers and
  instrumental markers; it is a heuristic and was only used to *dismiss* mirrors, never to promote
  something to actionable. Every item in §2 was additionally confirmed by listing the directory.
- "albums (primary)" in the §1 table attributes each album to its largest group's cause, so the
  album column and the track column are not proportional.
