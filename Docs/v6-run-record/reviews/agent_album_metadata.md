# Phase 2 album metadata — correctness audit

Scope: `Processor/InfoCollector/AlbumInfo/info_scanner_ph2.py` (`Phase02AlbumExtractor`),
output `info_scanner.phase2.albuminfo.output.json`, 18,360 albums.
Every number below comes from a script in
`/tmp/claude-1000/-home-sqz269-prog-other-tlmc-etl/40bf1717-aa71-4f93-a8be-f1f5f42a4bbe/scratchpad/alb/`
run against that file, `info_scanner.phase1.output.json` and
`info_scanner.probed_result.output.json` (178,707 probed tracks). Nothing in the repo
or `/mnt/tlmc` was modified.

## 0. Headline

`NeedsManualCheck` is true for **0 / 18,360** albums, and `AlbumName` is empty for
**0 / 18,360** — the flag can only fire on the one condition that the code has already
guaranteed can never hold. It carries no information. Measured against the directory
names and the embedded tags, **2,068 albums (11.3 %) carry at least one demonstrable
defect** in a field other than `AlbumArtist`; including the `AlbumArtist` path/tag
disagreements the figure is **2,579 (14.0 %)**.

## 1. Measured accuracy on the 151-album sample

Sample: `scratchpad/ph2_album_sample.json`, 151 albums, evenly spaced through the
sorted album list. Each album was compared by hand against its directory name, its
parent (circle) directory name, and the majority-vote embedded tags of its tracks
(`album`, `album_artist`, `date`, `event`, `catalogid`/`catalognumber`/`catalog`).
Dump used for the review: `alb/sample.txt`.

| Field | Correct | Denominator | Accuracy |
|---|---|---|---|
| `AlbumName` | 148 | 151 | **98.0 %** |
| `ReleaseDate` — value not wrong | 151 | 151 | **100 %** |
| `ReleaseDate` — full precision available *and* delivered | 139 | 151 | **92.1 %** |
| `CatalogNumber` | 146 | 151 | **96.7 %** |
| `ReleaseConvention` | 142 | 151 | **94.0 %** |
| `AlbumArtist` — names the right entity | 148 | 151 | **98.0 %** |
| `AlbumArtist` — usable as an artist string (no directory syntax) | 1 | 151 | **0.7 %** |

### Every error found, classified

**AlbumName — 3 errors (2 classes)**

- *Disc-level tag chosen as the album name* (2): `#029 [C62] Diverse System — D5： Diverse
  Style from ''B'' 5th style {DVSP-0009~10}` → `D5: Diverse Style from "B" 5th style **Side-A**`;
  `#093 2015.05.10 [ALMR-027~8] TRAIL II [例大祭12]` → `TRAIL II **DISC 1**`. The
  majority vote in `extract_album_info_from_probed_results` picks whichever disc has more
  tracks; the album name is not a per-disc value.
- *Tag free-text preferred over the clean directory name* (1): `#059 2019.03.10
  Revelations - 異聞` → `Revelations - 異聞 (162BPM fixed, recommended random playback
  series original anecdote 1)`.
- Not counted as an error but unadjudicable: `#147` directory says `麗 -RAY- 月天夜姫`,
  the tag says `麗 -REI- 月天夜姫`; the tag wins and one of the two is wrong.

Corpus-wide confirmation: **174 albums** have an `AlbumName` still carrying a disc/side
marker chosen out of a multi-valued `album` tag (292 albums have tracks carrying more than
one distinct `album` tag). **109 albums** have an `AlbumName` containing `[`/`]`/`{`/`}`,
of which 5 are parser residue (the other 104 come verbatim from the tag).

**ReleaseDate — 0 wrong values, 12 degraded**

No sampled album received a date that contradicts its directory name or tags. The path
override is doing real work: `#083 2014.05.11 [UTGN-0011] Tranquillity Moon` has the
literal string `例大祭11` in its `date` tag, and the path value replaced it.

- *Year only where the corpus itself could supply a day* (9): `#019 (C86)`, `#028 秋季例大祭2`,
  `#050 M3 Festa`, `#071 C92`, `#088 例大祭8`, `#089 C95`, `#090 M3-50`, `#092 M3-46`,
  `#096 M3-45`. The `ReleaseConvention` back-fill is only applied when `ReleaseDate` is
  *empty*, so a year-only tag date blocks it.
- *Year only, nothing better exists anywhere* (3): `#014`, `#046`, `#052`.
- *Path and tag disagree at day level, unadjudicable* (2, not scored as errors):
  `#075 2022.02.02 Midnight Glow-Resurrection` (tag `2022.02.01`), `#134 2021.11.14 雪蓮`
  (tag `2021.10.31`).

Corpus-wide confirmation: of the 16,495 directory names beginning `YYYY.MM.DD`,
**16,495 (100.0 %)** produced exactly that `ReleaseDate` — zero mismatches. Shape census
of all 18,360: `YYYY.MM.DD` 16,923 · bare year 1,207 · empty 42 · 186 other
(`2018-08-30`, `2015/12/31`, `2015-05-2`, `1996.Xx.Xx`, …), 2 `YYYY.MM`. The 186
non-canonical strings are copied straight out of the tags and never normalised.

**CatalogNumber — 5 errors (3 classes)**

- *Present in the directory's catalog slot, rejected by the extraction rule* (2):
  `#037 2011.05.08 [F306-0007] Eryngiusis` (`F306-0007` has only one ASCII letter, rule
  requires ≥2); `#046 SOUND VOLTEX ULTIMATE TRACKS -LEGEND OF KAC- {KONAMI - LC-2237~8}`
  (bracket is 19 chars, rule requires ≤15).
- *Present only in an embedded tag; phase 2 never reads catalog from tags* (2):
  `#020 CIXO0017`, `#134 AZSE-0004`.
- *False positive — the release convention emitted as the catalog* (1):
  `#146 2010.05.05 幻想ホモ・ルーデンス [M3-10春]` → `CatalogNumber = "M3-10春"`.
  (`春`.isalpha() is true in Python, so the CJK suffix satisfies the ≥2-letter test that
  normally protects `M3-xx` from being read as a catalog.)

**ReleaseConvention — 9 errors (5 classes)**

| # | Directory | Emitted | Why wrong |
|---|---|---|---|
| 001 | `2020.04.10 [NA] Touhou Blooming Chaos - Soundtrack` | `NA` | `[NA]` is the "no catalog" placeholder in the catalog slot |
| 008 | `[2017.06.17] AlphaVersion Records — Phalang EP {AVRN-013} [WEB-320]` | `WEB-320` | source/quality token |
| 019 | `(C86) Crest - おとなの艦これ` | *(empty)* | `(C86)` is in parentheses, which `extract_bracket_content` deliberately does not parse |
| 024 | `[2010.08.14] MajLOVE × MinBABY` | `2010.08.14` | the date bracket reused as the convention |
| 059 | `2019.03.10 Revelations - 異聞` | `019.03.10 Revelations - 異` | corrupt `event` tag, taken verbatim |
| 078 | `2021.01.11 【睡眠用】…【1時間】 [作業用・睡眠用BGM]` | `作業用・睡眠用BGM` | genre/usage label |
| 079 | `[2022.04.24] TTL SOUND - DOKI DOKI HEART (feat. HIROKO)` | `2022.04.24` | date |
| 084 | `2009.01.27 [VNHS-0001] 桃源Garden` | `源Garde` | corrupt `event` tag |
| 095 | `[2018.03.18] salvation by faith records — しきのおもいで {SBFR-0078}` | `2018.03.18` | date |

Corpus-wide confirmation (16,100 albums have a non-empty `ReleaseConvention`):
**276 (1.71 %) are demonstrably not a convention** — 175 are a date or bare year, 50 are a
format/quality token (`WEB-320`×15, `MP3 320`×7, `MP3`×6, `MP3 V0`, `CDr-320`, `CD7`…),
43 are the album's catalog number, 8 are the literal `NA`. Full list:
`alb/conv_bad.json`.

**AlbumArtist**

- 18,346 / 18,360 values (**99.9 %**) are the raw circle directory name and begin with `[`.
  The only 14 exceptions are all `Various Artists`. 1,233 of them additionally carry a
  romanisation appended after the closing bracket (`[Liz Triangle] りすとら`,
  `[はちみつくまさん／ひえろぐらふ] hachikuma-hierograph`). Nothing downstream strips this.
- Identification errors in the sample (3): `#004 [A1]` where the circle is `A-One`
  (a directory abbreviation, not the artist's name); `#052 [MAD BREAKS]` for an album whose
  own directory is `modest by default - SEMIOTICS …`; `#125 [少年ヴィヴィッド]` for a
  collaboration the tag records as `少年ヴィヴィッドと天狗ノ舞`.

## 2. Unterminated / mismatched brackets — the full list

**13 of 18,360 directory names have unbalanced `[]`/`{}` counts.** Ten of them make
`extract_bracket_content` hit the `outer_bracket_end == -1` branch and print
`Invalid string: Unterminated bracket`; the other three parse but pair the wrong
delimiters. The `return []` on bail only discards the *remainder* of the string — brackets
already consumed by earlier recursion levels survive — and every one of these 13 albums has
usable `album`/`album_artist`/`date`/`event` tags, so `AlbumName`, `ReleaseDate`,
`AlbumArtist` and `ReleaseConvention` were all recovered from tags. **The only field
actually lost is `CatalogNumber`, on 4 albums.**

| Directory name | Bail? | Fields lost |
|---|---|---|
| `[M3-29] 5150 — 神竜物語 {5150-A003] [CD-FLAC]` | yes | **CatalogNumber `5150-A003`** (also sitting unused in the `catalogid` tag) |
| `[C87] k-waves LAB — la malgrava peto {KWL-0011 [CD-FLAC] (45%)` | yes | **CatalogNumber `KWL-0011`** |
| `[C99] Diverse System — AD：TRANCE 8 {DVSP-0264~5 [CD-FLAC]` | yes | **CatalogNumber `DVSP-0264~5`** |
| `2008.05.25 [HKMP-OTO25[ 東方見文録 [例大祭5]` | no (crossed pair) | **CatalogNumber `HKMP-OTO25`** — the stray `[` makes the first bracket run to the far `]`, yielding a 29-char token that fails both the catalog (≤15) and event (≤10) length rules |
| `[M3-34] 9bit Log!Q+ — DUSTBRAIN CHARIOT {9QCD-0012} [CD-FLAC} (No Log)` | yes | none — bail is at the trailing `[CD-FLAC}` |
| `[M3 Festa] Liz Triangle — Lily {no cat#} [CD-FLAC} (No Log)` | yes | none |
| `[M3-43] 外柿山 — Back to 奥 好義 {TGCD-0023} [WEB-FLAC}` | yes | none |
| `[M3-11] Diverse System — Diverse Style, THE RAGNAROK {DVSP-0013} [CD-FLAC} (25%)` | yes | none |
| `[2007.11.20] Diverse System — Dear, Mr.Nagureo {DVSP-0043} [CD-FLAC}` | yes | none from the bail (but `ReleaseConvention` = `2007.11.20`, the date-as-convention defect) |
| `[C92] BubbleRecords — Amaretto {BR-0029} [CD-FLAC} (No Log)` | yes | none |
| `[C67] Hellion Sounds — Baroque {HSCD-0003} [CD-FLAC} (No Log)` | yes | none |
| `2010.03.14 博麗神社例大祭(第7回) オマケディスク [[例大祭7]` | no | none — path would have yielded `[例大祭7`, but the `event` tag `例大祭7` won |
| `2005.08.14 [STAL-0501] The disappearing planet [C68]]` | no | none |

So the console noise overstates the damage: 6 of the 10 bails happen at the last bracket
in the string and cost nothing, and tags absorb the rest. The residual risk is that the
same bug on an album with no tags would silently drop every field — 135 albums corpus-wide
have no `album` tag at all and depend entirely on the path parser.

## 3. The 42 albums with no `ReleaseDate`

14 of the 42 have **zero tracks** — phase 1 emitted a container directory (whose real
albums are its children), or a directory holding only `.rar`/`.iso`/`.tta`/MIDI/DVD
content, as an album. Those cannot have a date because they have no tags and no dated
name; the defect is upstream in phase 1, not in phase 2.

| # | Album directory | Trk | Verdict | Recoverable value / source |
|---|---|---|---|---|
| 1 | `[TTL SOUND]/(M3-46)(同人音楽)[TTL SOUND] TTL EUROBEAT vol.14` | 12 | **recoverable** | `2020.10.25` — `(M3-46)` in parentheses; the corpus convention table has M3-46 → 2020.10.25. Parentheses are not parsed |
| 2 | `[DeZI：R]/Password Protected - I dont have the password` | 0 | absent | holds one `.rar` only |
| 3 | `[R-note] あ～るの～と/東方M-1ぐらんぷり` | 0 | absent (container) | 12 dated child album dirs |
| 4 | `Various Artists/project-SIGMA - Sound Catalog 001 (2009 Autumn Version)` | 0 | absent from name/tags | `2009` inferable from the title; the single file `090928_1549.iso` implies 2009.09.28 (filesystem, outside the fields audited) |
| 5 | `Various Artists/Touhou Genso Wanderer -Reloaded- Complete Edition` | 0 | absent (container) | — |
| 6 | `[AGENT 0]/{AGENT-0018} [Comiket99] AGENT 0 - The Beast Tempts From Within …` | 9 | **recoverable** | `2021.12.31` — `ReleaseConvention` is `Comiket99`; the table is keyed `C99`, so the back-fill missed it purely for want of alias normalisation |
| 7 | `[AGENT 0]/Bandcamp Albums` | 0 | absent (container) | 12 child albums |
| 8 | `[AGENT 0]/AGENT 0 - Curse of the Endless Sea [FLAC]` | 3 | absent | no date in name or any tag |
| 9 | `[Casket]/Tracks` | 2 | absent | — |
| 10 | `[Re：SPEC]/Re：SPEC — ふらみねっ! -Smell Our Flowmination!-` | 17 | absent | — |
| 11 | `[Re：SPEC]/Keep Our Determination!` | 28 | absent | — |
| 12 | `[Java Sparrow Music!!]/… J-CORE Alive 4 [FLAC]` | 15 | absent | — |
| 13 | `[Squall Of Scream]/… WHAT COLOR EP [FLAC]` | 5 | absent | — |
| 14 | `[Studio Lepus]/(展会未知)[Studio Lepus] Fragments of Malice` | 4 | absent | `展会未知` literally means "event unknown" |
| 15 | `[Alice＊Iris]/君と密になる` | 1 | **recoverable** | `2023` — `year` tag (phase 2 reads only `date`, never `year`) |
| 16 | `[Alice＊Iris]/大嫌いlie好き` | 1 | **recoverable** | `2023` — `year` tag |
| 17 | `[bunny rhyTHm]/bunny rhyTHm` | 0 | absent | only `folder.jpg` + `Thumbs.db` |
| 18 | `[SiesTail]/Mt.FUJI EP` | 0 | absent | `.tta` + `.cue` only |
| 19 | `[nekomimi style]/nekomimi style - クロレラE.P. [FLAC]` | 8 | absent | (`comment` tag holds the catalog `NMCD-0023`, no date) |
| 20 | `[nekomimi style]/くまおと！ おさらい` | 9 | absent | — |
| 21 | `[KONAMI]/SOUND VOLTEX CD JAEPO … {KONAMI - KFC-1901} (2019) [CD-FLAC] (85%)` | 2 | **recoverable** | `2019` — parenthesised year, not parsed |
| 22 | `[Lunar Machines]/… Claranieve {LMCA-00004} [CD-FLAC]` | 11 | absent | — |
| 23 | `[Lunar Machines]/… Atmosync {LMCA-00002} [CD-FLAC]` | 8 | absent | — |
| 24 | `[Hand Craft records] crft side/六塵サティスファイ` | 6 | absent | (tags are mojibake: `AlbumName` came out `ZoTeBXt@C`) |
| 25 | `[dBu music]/DISC16 … EXTRA ENCODED DVD` | 0 | absent (container) | — |
| 26 | `[dBu music]/DISC15 … EXTRA DATA DISC` | 0 | absent (container) | — |
| 27 | `[DTXFiles.nmk&Colorful Umbrella]/… Collaboration E.P` | 5 | absent | — |
| 28 | `[Xceon vs Starving Trancer]/EUROBEAT Summit REMIXED BY A-One` | 10 | **recoverable** | `2015.04.26` — `TYER` tag on all 10 tracks; phase 2 reads only `date` |
| 29 | `[KANPYO'S MIDI]/kanpyo_legacy_music` | 0 | absent | MIDI subdirectories only |
| 30 | `[Astral Sky + 非可逆リズム]/Astral Sky + 非可逆リズム` | 0 | absent (container) | 12 dated child album dirs |
| 31 | `[Diverse System]/[DVSP-0002] D2： Diverse Style from ''B'' 2nd style. (C59) (mp3)` | 8 | **recoverable** | `2000.12` — `TYER` tag on all 8 tracks. `ReleaseConvention` is `C59` but no other album in the corpus carries `C59` with a date, so the back-fill had nothing to copy |
| 32 | `[D'va;;;;;;;;5]/D'va… Archives - Patchwork Chimera … (16-24bit FLAC)` | 0 | absent (container: `16bit`/`24bit` subdirs) | — |
| 33 | `[Static World]/Static World - 末紀天穹` | 8 | absent | — |
| 34 | `[twinkle＊twinkle]/[TSDM@zhuxian9005](M3-34)(同人音楽)[twinkletwinkle] SUPERNOVA…` | 0 | **recoverable** | `2014.10.26` — `(M3-34)` in parentheses. (0 tracks: the audio is `.tta`) |
| 35 | `[Login Records]/… Splash Trigger 6 [FLAC]` | 20 | absent | — |
| 36 | `[Login Records]/… Never Forget Vacation 8` | 15 | absent | — |
| 37 | `[CODE ZTS LABEL]/… VAGUE IN WINTER 2 [ZTSL-016] (C73)` | 9 | **recoverable** | `2007.12.31` — `(C73)` in parentheses; the table has C73 → 2007.12.31 (86 albums) |
| 38 | `[CODE ZTS LABEL]/… VAGUE IN WINTER 3 [ZTSL-017]` | 9 | absent | — |
| 39 | `[IRON ATTACK!]/[MIA-055] 凱 ～Power and glory～` | 9 | absent | — |
| 40 | `[Engage Blue]/Engage Blue` | 0 | absent (container) | 7 child album dirs, each with a `(convention)` |
| 41 | `[Layla.]/Layla - Awakening [FLAC]` | 6 | absent | — |
| 42 | `[CLOCKWORKS TRACER]/… House of Cards` | 1 | absent | — |

**Tally: 9 of the 42 are recoverable** (rows 1, 6, 15, 16, 21, 28, 31, 34, 37) — 4 from a
parenthesised convention or year, 3 from a `TYER`/`year` tag phase 2 does not read, 1 from
convention-alias normalisation (`Comiket99` → `C99`), 1 from a parenthesised year.
**33 are genuinely dateless** in the directory name and in every embedded tag; 14 of those
are directories that hold no tracks at all.

## 4. `AlbumArtist`: is the path override the right call?

Comparison method: NFKC-normalise and casefold both sides, strip whitespace and
punctuation, and treat the path value as matching if the tag equals the whole string, the
`[...]` head, the trailing romanisation, or any `／ / & ＆ × +`-separated component of the
head.

| | Albums | % of comparable |
|---|---|---|
| Total albums | 18,360 | |
| No `album_artist` tag at all (path is the only source) | 455 | |
| Comparable (tag present) | 17,905 | 100 % |
| Path string identical to tag | 1 | 0.01 % |
| Same entity after stripping brackets/normalising | 16,332 | 91.2 % |
| One contains the other | 751 | 4.2 % |
| **Genuinely different strings** | **821** | **4.6 %** |

Albums where tracks disagree among themselves on `album_artist`: 24.

**Judging a sample of 40 of the 821 disagreements** (`alb/artist_unrelated.json`), against
the album's own directory name:

| Outcome | n / 40 |
|---|---|
| **Tag is the better value** — path is a directory abbreviation (`[A1]` vs `A-One`, 7 cases), or the circle folder is a label and the album directory itself names the artist (`[MAD BREAKS]`/`Aki`, `/Dev`, `/不味い`; `[トマト組]`/`kAmp`; `[Black Label Records]`/`BL-Records`; `[Rice Records]`/`Ashay`), or the tag records a collaboration the folder flattens | 16 (40 %) |
| **Path is the better value** — the tag holds a member/guest named in parentheses in the directory (`[C.H.S]` vs `t+pazolite`, `[Diverse System]` vs `Nhato`/`Hiroshi Okubo`, `[CXR Record]` vs `cexiria`, `[Draw the Emotional]` vs `ゆよゆっぺ`, `[Melonbooks Records]` vs `幽閉サテライト`, `[S.D.HARDCORE]` vs `TMTK`), or the tag holds an album-series name (`[TTL SOUND]` vs `TTL EUROBEAT`) | 8 (20 %) |
| **Tag says `Various`/`Various Artists`** on a circle-published compilation; path is more informative but the tag is not wrong | 6 (15 %) |
| Same entity, spelling/typo/quote-character variant, no winner (`[SOUTH OF HEAVEN]`/`SOUND OF HEAVEN`, `[Kissing the Mirror]`/`Kissing Mirror`, `[808sndmindsbreak]`/`808sndmindbreak`, `[lol project]`/`laughing out loud`) | 7 (17.5 %) |
| Genuinely different names, no evidence either way (`[猫大樹]`/`猫体質`, `[岡垣正志＆フレンズ]`/`Aphrodite Symphonics`, `[さやかた紅茶館さん＆GenocideKitten]`/`レミ咲合同企画`) | 3 (7.5 %) |

Corpus-wide, 73 of the 821 disagreements have a tag reading `Various`/`V.A.`, and 161 have
the tag string appearing verbatim inside the album directory name (20 of those inside
parentheses, i.e. the `Circle (member)` form). Concentration: `[A1]` 97, `[MAD BREAKS]` 60,
`[salvation by faith records]` 37, `[Cytokine]` 26, `[KyokudoCore Records]` 23,
`[Black Label Records]` 23.

**Verdict.** The override is defensible but not correct as stated. Where it wins it wins
big (455 albums have no tag at all; the tag is mojibake in cases such as
`ぐ文水海洋俱樂部ゴ` for `[文水海洋俱乐部]`), and it correctly resists per-track artist
leakage. But in the disagreement set the tag is the better value more often than the path
(16 vs 8 of 40), and the path value is *always* a directory string — 18,346 values carry
`[...]` and 1,233 carry an appended romanisation. The right shape is: keep path priority,
but (a) parse the directory name into a circle name rather than storing it raw, and (b)
prefer the tag when the album's own directory name names a different artist.

## 5. `CatalogNumber` empty for 5,933 albums — how many are real gaps?

TLMC's dominant naming form is `YYYY.MM.DD [CATALOG] Album [EVENT]`. **11,079** album
directories use it; **10,933 (98.7 %)** produced `CatalogNumber` exactly equal to the slot
token, with **0** mismatches. The remaining 146 are losses.

Corpus-wide census of the 5,933 empty values, using three independent objective tests
(catalog visible in the `YYYY.MM.DD [X]` slot; catalog visible in a `{...}` brace, which is
TLMC's catalog slot in the `Circle — Album {CAT} [FORMAT]` style; a catalog-bearing
embedded tag) after excluding dates, format tokens, the placeholders `NA` / `no cat#` /
`unknown cat#`, and ZUN's `TH##` game codes:

| | Albums |
|---|---|
| `CatalogNumber` empty | 5,933 |
| catalog visible in the `YYYY.MM.DD [X]` slot | 105 |
| catalog visible in a `{brace}` | 64 |
| catalog present in an embedded tag (`catalogid` 39, `catalog` 6, `catalognumber` 4, `itunescatalogid` 3, `discogs_catalog` 1) | 53 |
| **union — a catalog is demonstrably available and was missed** | **215 (3.6 %)** |
| **no catalog demonstrable anywhere** | **5,718 (96.4 %)** |

Independent check by hand: a random sample of **150** of the 5,933 (`alb/cat.txt`,
seed 11) contained **5** with a recoverable catalog (`{KCRCD008}`, `{ABCD006}`, and tag
values `FLIO-0012`, `CIXO0012`, `ACCP0001`) — **3.3 %**, consistent with the 3.6 % census.
The other 145 have no catalog token in the directory name and no catalog tag; two of them
say so explicitly (`{no cat#}`, `{Self-Released - no cat#}`).

Why the 215 were rejected (`try_extract_catalog_number` requires a `-`, length 5–15,
≥2 digits and ≥2 letters):

| Rule that rejected it | Albums |
|---|---|
| requires a `-` (`KCRCD008`, `ABCD006`, `CJVK0021~22`, `CO1168CD05`, `MSTBL007`, `BPCD0001`) | 81 |
| ≥2 letters (`F306-0007`, `m9-001`, `K2-0017`, `N-002`, `A.F.D001`) | 40 |
| ≥2 digits (`COM-2`, `TDOS-3`, `ASPA-1`, `WX-EX`, `DNAS-MJST`, `AREP-LMTD`) | 24 |
| length 5–15 (`KONAMI - LC-2237~8`, `ZERO-KNKR-GO-0001`, `SBFR-0029／SSEB-0019`) | 24 |

A secondary consequence: for **51 albums** the rejected catalog token was then picked up by
`try_extract_event_number` (which accepts any single ≤10-char bracket) and stored as the
`ReleaseConvention` — e.g. every `KCRCD0xx` / `KCRFREE00x` album of KyokudoCore Records, and
ZUN's `TH02`…`TH19`. 50 of those 51 came from the path with no tag agreeing.

## 6. Problems ranked by albums affected

| Rank | Problem | Albums | % of 18,360 |
|---|---|---|---|
| 1 | `AlbumArtist` is the raw circle **directory** string — `[...]` wrapper, and for 1,233 an appended romanisation | 18,346 | 99.9 % |
| 2 | `ReleaseDate` is a bare year although the field is meant to be a date | 1,207 | 6.6 % |
| 3 | `AlbumArtist` from the path names a different entity than the `album_artist` tag; on the sample the tag was the better value 40 % of the time vs the path's 20 % | 821 | 4.5 % |
| 4 | `ReleaseConvention` holds something that is not a convention (175 dates, 50 format tokens, 43 catalog numbers, 8 `NA`) | 276 | 1.5 % |
| 5 | `CatalogNumber` empty although a catalog is present in the name or tags | 215 | 1.2 % |
| 6 | `ReleaseDate` in a non-canonical format (`2018-08-30`, `2015/12/31`, `1996.Xx.Xx`) — copied from tags, never normalised | 186 | 1.0 % |
| 7 | `AlbumName` is a *disc* name (`… DISC 1`, `… Side-A`) because the album tag is multi-valued and decided by majority vote | 174 | 0.9 % |
| 8 | `AlbumName` contains bracket characters (5 of them parser residue, 104 verbatim from tags) | 109 | 0.6 % |
| 9 | Albums with zero tracks emitted as albums by phase 1 (unfixable at phase 2; the source of a third of the missing dates) | 101 | 0.6 % |
| 10 | `ReleaseDate` empty; 9 of the 42 are recoverable | 42 | 0.2 % |
| 11 | Directory name has unbalanced brackets; 10 trigger the `Unterminated bracket` bail, 4 lose `CatalogNumber` | 13 | 0.07 % |
| — | `NeedsManualCheck` true | 0 | 0 % |

Union of rows 2 and 4–11: **2,068 albums (11.3 %)**. Adding row 3: **2,579 (14.0 %)**.

## What could not be measured

- For the two path/tag date conflicts (`Midnight Glow-Resurrection`, `雪蓮`) and the
  `麗 -RAY-` / `麗 -REI-` name conflict there is no third source in the dataset, so which
  side is right is undecidable from the data at hand.
- Circle-name questions such as `[猫大樹]` vs `猫体質` need an external circle registry;
  neither the directory tree nor the tags settle them.
- Whether a `.log`, `.cue` or `.txt` inside the 33 genuinely-dateless album directories
  carries a date was not checked — the brief scoped date recovery to the directory name,
  the tags and the convention back-fill.
