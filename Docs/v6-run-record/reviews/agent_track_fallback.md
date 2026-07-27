# Broadened filename fallback for track metadata — findings

Scope: `Processor/InfoCollector/AlbumInfo/info_scanner_ph2.py`, `Phase02TrackExtractor`.
Every number below comes from a script run against
`Processor/InfoCollector/AlbumInfo/output/info_scanner.phase2.trackinfo.output.json` (164,528 tracks),
`Processor/InfoCollector/AlbumInfo/output/info_scanner.probed_result.output.json` (ffprobe tags), and
`scratchpad/ph2_flagged_tracks.json` (3,323 flagged tracks). Scripts live in `scratchpad/tf/`.
Nothing in the repo or `/mnt/tlmc` was modified and no pipeline stage was re-run.

---

## 0. Headline: the biggest win is not a filename regex at all

The probe tags were read for all 164,528 tracks and the raw `track` tag classified:

| `track` tag form | count |
|---|---|
| decimal (`"7"`) | 144,562 |
| empty | 17,526 |
| **non-decimal** | **2,440** |

**All 2,440 non-decimal values are the ID3v2 `TRCK` "position/total" form (`"7/10"`, `"09/09"`).**
There is not a single other non-decimal shape in the library.

`extract_track_info_from_probed_results` does:

```python
if type(probed_data["track"]) == str and not probed_data["track"].isdecimal():
    probed_data["track"] = -1
```

so it throws all 2,440 away. **2,440 of the 3,254 tracks flagged `track == -1` (75.0%) have a
perfectly good track number sitting in their own tags.** These are the mp3/m4a files — which is
exactly why the mp3 flag rate is 64% and the flac flag rate is 0.1%.

Cross-check for safety: of those 2,440, 87 also have a canonical `(NN) [artist] title` filename.
The `N` from the tag matches the filename number in **87/87** cases, 0 disagreements. Parsing
`N/M -> N` is a zero-risk change.

Everything else in this document is about the residual **814** tracks whose `track` tag is genuinely absent.

---

## 1. Convention distribution over the 3,323 flagged filenames

Assigned by an ordered, first-match-wins pipeline (rules defined in §2). "needed-by" = how many of
the matched tracks actually require the filename (tags cannot supply the missing field).

| # matched | convention | needed-by | dominant extensions | example |
|---:|---|---:|---|---|
| 1,461 | `NN. title` | 56 | mp3 1338, flac 58, m4a 50, wav 15 | `04. おふらんすおぜう.mp3` |
| 687 | **no rule matches** | — | mp3 379, wav 224, flac 83 | `fly to night, tonight.wav` |
| 449 | `NN - title` | 24 | mp3 429, wav 10, flac 7 | `09 - Wonderful Occultism.mp3` |
| 393 | `NN title` | 61 | mp3 286, m4a 62, wav 38 | `01 Battle on the Bridge.mp3` |
| 168 | `(NN) [artist] title` (non-flac ext) | 81 | **wv 94, mp3 66, flac 8** | `(02) [Kaisei] 地蔵だけが知る哀嘆.wv` |
| 128 | `D<sep>NN<sep>title` (disc-prefixed) | 31 | flac 52, mp3 41, m4a 34 | `1.04. kokomochi — Artemis.mp3` |
| 29 | `NN-title` / `NN_title` | 24 | mp3 18, flac 7, wav 4 | `07_夕に焼ける故郷.flac` |
| 8 | `NNN.ext` (number, no title) | 6 | wav 6, mp3 2 | `1.mp3` |
| **3,323** | | | | |

Note the 168 canonical-form hits: **the whole `.wv` problem (94 files, 36% flag rate) is nothing
but the `\.flac` literal in the current regex.** Same for 66 mp3 and 8 flac (the 8 are files whose
extension case or spacing the strict `TRACK_INFO_VALIDATION_V2` rejected).

A large secondary theme, visible in the examples, is that the artist is embedded in the filename
after the number, separated by an em dash or hyphen: `04. Blue Twinkle — 永久リライト.mp3`,
`01. Yamajet feat. moham — Desired night.mp3`, `05. 北宮 - Stardust et finis.mp3`.
Naively treating everything after the number as the title corrupts these — see §3.

---

## 2. Proposed rules, recovery, and measured false-positive rates

### 2.1 How the false-positive test was built

The FP pool is every track that has **both** a non-empty tag `title` and a resolvable tag `track`
(decimal or `N/M`): **146,932 tracks**, i.e. the population that is parsed correctly today from tags.
Each rule is run against those filenames and the extraction compared with the tag.

Caveat stated up front: this is a proxy. Because the merge is field-level and tag-first, a wrong
regex can only do damage on a track where that field's tag is *missing* — which is precisely where
no ground truth exists. The tagged-pool disagreement rate is the best available estimate of how
often the rule is wrong; it is not a direct measure of harm.

Title comparison is bucketed, because "not byte-equal" is not the same as "wrong":

- **correct** — equal, or equal after NFKC/whitespace/`～`→`~` normalisation, or equal after
  stripping all punctuation (filesystem sanitisation: `:` → ` `, `?` dropped, `*` → `x`, `/` removed).
- **lossy** — extraction is a strict subsequence of the tag; the filename genuinely omits
  information the tag has (`03-Spear of Justice.mp3` vs tag `Spear of Justice / Undertale` —
  the `/` cannot exist in a filename). Not a parse error, and still better than an empty title.
- **WRONG** — extraction keeps text that is not the title, or is unrelated. This is the number that matters.

### 2.2 The ruleset

Ordered, first match wins. `EXT = \.(?:flac|mp3|wav|wv|m4a|ogg|opus|aac|ape|tta|tak|wma|aiff?)`,
all compiled `re.IGNORECASE`. After a match, a leading `[\s\-–—_.]+` run is stripped from the
remainder, then the artist-split of §3 is applied.

```python
R1 = r'^\((?P<t>\d{1,3})\)\s*\[(?P<a>[^\]]+)\]\s*(?P<r>.+?)' + EXT + r'$'
R2 = r'^(?P<d>\d{1,2})[-_.](?P<t>\d{1,2})[-_.\s]+(?P<r>\D.*?)' + EXT + r'$'
R3 = r'^(?P<t>\d{1,2})\.[\s]*(?P<r>\D.*?)' + EXT + r'$'
R4 = r'^(?P<t>\d{1,2})\s+-\s+(?P<r>.+?)' + EXT + r'$'
R5 = r'^(?P<t>\d{1,2})[-_](?P<r>\D.*?)' + EXT + r'$'
R6 = r'^(?P<t>\d{1,2})\s+(?P<r>.+?)' + EXT + r'$'
R7 = r'^(?P<t>\d{1,3})' + EXT + r'$'
```

### 2.3 Results

Recovery is counted only where the field is actually needed (tag cannot supply it).

| rule | pattern | tagged-pool matches | track disagree | track FP | title correct | title lossy | title WRONG | recovers track | recovers title |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| R1 | `(NN) [artist] title` | 123,741 | 155 | 0.125% | 99.84% | 0.01% | 0.15% | 15 | 75 |
| R2 | `D<sep>NN<sep>title` | 1,341 | 0 | **0.000%** | 94.18% | 0.97% | 4.85% | 30 | 0 |
| R3 | `NN. title` | 11,148 | 0 | **0.000%** | 95.78% | 1.09% | 3.13% | 56 | 13 |
| R4 | `NN - title` | 4,820 | 11 | 0.228% | 92.49% | 0.85% | 6.66% | 24 | 21 |
| R5 | `NN-title` / `NN_title` | 260 | 1 | 0.385% | 51.54% | 5.00% | 43.46% | 24 | 23 |
| R6 | `NN title` | 2,579 | 28 | 1.086% | 92.47% | 2.02% | 5.51% | 61 | 38 |
| R7 | `NNN.ext` | 103 | 0 | **0.000%** | n/a | n/a | n/a | 6 | 0 |
| | **all** | **143,992** | **195** | **0.135%** | **99.01%** | 0.17% | 0.82% | **217** | **169** |
| | **new rules only (excl. R1)** | **20,251** | **40** | **0.198%** | **93.89%** | 1.19% | 4.91% | 202 | 94 |

Reading of each row:

- **R1 (extension generalisation).** Broken out by extension, extending past `.flac` adds 433
  tagged matches — mp3 225, wv 198, wav 8, m4a 2 — with **0 track disagreements and 0 title
  disagreements on mp3/wv/wav**. The only 2 m4a "failures" are an album where the tag title itself
  carries a ` - artist` suffix the filename lacks. The 0.125% flac figure is the *existing* rule's
  behaviour, unchanged and today invisible because tags win.
- **R2, R3, R7** have a literally zero track-number disagreement rate over 12,592 tagged tracks.
- **R4**'s 11 disagreements are **all one album** (`SSEB-0027`) whose tags are offset by +7 from
  the filenames, out of 474 albums matched.
- **R5**'s single track disagreement is one pathological name
  (`3-kyū - NAPTERRO WORSHIP - 53 p 45 a (…).flac` — `3-kyū` is a circle name, not a number).
  Its 43% title-WRONG rate is **not a parse failure**: 113 wrong titles concentrate in 7 albums,
  86 of them one soundtrack whose tags are English translations of Japanese filenames
  (`08_垣間見える異変.mp3` → tag `Glimpse of an Incident`). The regex extracted the filename title correctly.
- **R6** is the weakest, at 1.086% (28/2,579). Those 28 span only 5 albums and in at least 13 of
  them the *tag* is wrong, not the filename (an album where every `track` tag is `0`). Even so this
  is the rule I would gate most tightly.

---

## 3. The artist-in-filename problem, and the dash split

Without splitting, the `NN. <rest>` family assigns the entire remainder as the title, and the
remainder very often begins with the artist. Measured on the tagged pool:

| rule | title correct, no split | title correct, with dash split |
|---|---:|---:|
| R2 | 31.04% | **94.18%** |
| R3 | 22.85% | **95.78%** |
| R4 | 41.15% | **92.49%** |
| R6 | 80.14% | **92.47%** |
| all rules | 90.83% | **99.01%** |
| titles written wrong (absolute) | 13,108 | **1,174** |

The split is: try `^(?P<a>[^—–―]{1,60}?)\s+[—–―]\s+(?P<r>.+)$` (em dash) first, then
`^(?P<a>[^-]{1,60}?)\s+-\s+(?P<r>.+)$` (hyphen). Both require whitespace on either side of the
separator, which is what keeps `LEVEL5 -Judgelight-` and `2nd generation-- instrumental` intact.

**Do not write the split's left side into `artist`.** Measured separately: the split-derived artist
agrees with the tag artist in 11,339/11,851 cases (95.68%), but the 512 disagreements include real
corruption where the left side is part of the title, not an artist —
`08. ラストリモート - Type γ.flac` yields artist `ラストリモート` (a Touhou song name) when the true
artist is `Dark PHOENiX`. Since `artist` is not part of the `NeedsManualCheck` criteria, assigning
it buys nothing and costs 4.3% wrong data. Use the split only to strip the prefix off the title.

**Important:** the dash split changes zero flag counts (§5, configs 3 and 4 are identical at 609).
It is purely a data-quality improvement on the ~169 titles recovered and, more importantly, it is
what makes the broadened rules safe to *believe*.

---

## 4. Traps, measured

**Leading number is a disc prefix.** Real and common. 183 filenames in the tagged pool have a
3-digit leading number where `n % 100 == tag track` — `104 - good-cool feat.Sana - With The Flow.flac`
is disc 1 track 4, not track 104. Restricting the track group to **exactly 1–2 digits** is what
fixes this: on `NN - title`, widening `\d{1,2}` → `\d{1,3}` takes the track FP rate from
**0.228% → 3.878%** (11 → 194 disagreements). On `NN title`, from **1.086% → 2.928%** (28 → 222).
R2 exists to consume `D-NN-title` / `D.NN. title` explicitly and take group 2.

**Leading number is part of the title (`19 Eighty-Four.mp3`).** Structurally real but *empirically
almost absent here*. 1,488 tag titles begin with a digit, but only **1** track in the whole library
has `filename stem == tag title` with a leading digit run (`02 しんしんと.mp3`), and only **4** under
a looser test. Only **3** tracks exist where a leading-number rule extracts a number that is both
wrong and part of the title (`1.10 - yuzen - 1994.flac`, `1.13 - HALLPBE.S - 1950 -Impossible-.flac`,
`1-04 cosMo＠暴走P — 1000年後もきっと快晴.flac`) — and all three are handled correctly by R2, which
consumes the disc prefix. This trap is worth 3 tracks, not a rule change.

**Leading number is a year.** **0** filenames in the 164,528 start with `(19|20)\d\d` followed by a
separator. Non-issue in this library.

**Leading number is a BPM / sample index.** Present in the flagged set:
`140BPM Dubstep Drums Loop.wav`, `140BPM_Hi-HatsLoop 1.wav`, `3333_Track_2.wav`, `444_未命名音轨_1.wav`.
All are ≥3 digits and so are excluded by the 1–2 digit constraint, except via the rejected
no-separator rule (§6).

**Titles contain dots.** 7,987 tag titles contain a dot (`Memory out...`, `(Arrange ver.)`,
`FULLMOON-380.000`, `トップマン (S.S.T.N)`). This is why the extension must be an explicit alternation
anchored at `$` with a lazy title group — `os.path.splitext` or a greedy `(.+)\.\w+$` would eat
into these. The proposed `(?P<r>.+?)EXT$` form measured 0 title corruption from this cause.

**`NN.` vs `D.NN.`** `1.04. kokomochi — Artemis.mp3` — a naive `^(\d{1,3})\.` gives track 1 when the
truth is 4. R2 is ordered before R3 and the `(?P<r>\D...)` guard on R3 refuses a remainder starting
with a digit, so this is handled. Without the ordering, the no-separator rule mis-parses 1,499 tracks.

---

## 5. What each change is worth (ablation, on the 3,323 flagged)

| configuration | still flagged | missing track | missing title |
|---|---:|---:|---:|
| 0. today | 3,323 | 3,254 | 543 |
| 1. + parse `N/M` track tag **only** | **884** | 814 | 543 |
| 2. + R1 extension generalised only | 805 | 799 | 470 |
| 3. + full rule pipeline, no dash split | **609** | 597 | 374 |
| 4. + full rule pipeline, with dash split | **609** | 597 | 374 |
| 5. full pipeline **without** the `N/M` fix | 695 | 684 | 374 |

The `N/M` tag fix alone removes 73.4% of the flags. The full pipeline on top brings it to 81.7%
(3,323 → 609). Residue by extension: mp3 294, wav 229, flac 85, no-extension 1.

---

## 6. Rejected rules, with the measurements that reject them

| rejected rule | tagged matches | track FP | title FP | would recover | verdict |
|---|---:|---:|---:|---:|---|
| `^(\d{1,3})(\D.*)EXT$` — no separator | 20,442 | **7.333%** (1,499) | 66.60% | 226 | Reject. Highest recovery of any single rule and by far the highest damage: it eats disc prefixes (`1.04.` → 1), BPMs (`140BPM …` → 140) and any title starting with a digit. |
| `^(.+?)\s+-\s+(\d{2,3})EXT$` — trailing `- NNN` | 6 | **100.000%** (6) | 100.00% | 25 | Reject outright. Every single tagged match is wrong (`anoare - 99.mp3` is track 3; `04 AL-KAMAR - 800.flac` is track 4). The 25 it "recovers" are DPTE/KSHMR sample-pack libraries where the trailing number is a sample index, not a track. |
| `^(.+?)_(\d{1,3})EXT$` — trailing `_NN` | 98 | **62.245%** (61) | 100.00% | 48 | Reject. `(01) [AsparTateRecords] Night_303.flac` → 303 (true 1). |
| `^(.+?)-(\d{1,3})EXT$` — trailing `-NN` | 109 | **88.073%** (96) | 99.08% | 14 | Reject. `05. siromaru — C-4.flac` → 4 by luck; `Pumpkin of September-31.flac` → 31 (true 3). |
| widening track group to `\d{1,3}` on R4/R6 | 5,003 / 7,582 | 3.878% / 2.928% | — | +0 / +24 | Reject the widening. 17× and 8× the disagreement rate for essentially no extra recovery. |
| writing the dash-split left side into `artist` | 11,851 | — | 4.32% wrong artist | 0 flags | Reject. No flag benefit (artist is not a flag criterion) and it turns song titles into artist names. |

---

## 7. Genuinely unrecoverable residue

**597 tracks have no recoverable track number** from tag or filename:

- **318** contain **no digit anywhere** in the filename. Truly unrecoverable from the name alone.
  Examples: `fly to night, tonight.wav`, `Funny Hardbeat（始原のビート～Pristine Beat）.mp3`,
  `Demosong.mp3`, `Bonus Track.mp3`, `ほおずきみたいに紅い魂.mp3`.
- **279** contain a digit that is not a track number: `XCY-demo6.mp3`, `OT062_ReVolte_secretC9BGDX.mp3`,
  `[Exclusive]fly to night, tonight ななひらCover.mp3`.

**374 tracks have no recoverable title** (the file is bare `1.mp3` / `02.wav`, or nothing parses).

The 609-track residue concentrates in **96 album directories**, and the head of the distribution is
almost entirely bonus/extra content rather than real albums:

| n | directory |
|---:|---|
| 176 | `…/无昼之昼.logicx/Media/Audio Files` — Logic Pro project scratch audio |
| 42 | `[A-GEAR]/東方動画BGM支援` — loose BGM assets, no numbering at all |
| 31 | `[Innocent Key]/…/溝口ゆうまの仮歌地獄2` — guide-vocal takes |
| 17+16 | `[Pure Highball]/…/bonus/…/Stem` — stem exports (`Bass_main.mp3`) |
| 15 | `[Login Records]/…Never Forget Vacation 8` — `artist - album - NN title.wav` (see below) |
| 13 | `[SPACELECTRO]/…ボカロEDM13` — same `artist - album - NN title.wav` shape |
| 12 | `…/オマケ、ゲームBGM` — game BGM extras |

Two further conventions are visible in the residue but I recommend **not** chasing them:

- **30 files** of the shape `artist - ALBUM - NN title.ext`
  (`A.D.A.M - Never Forget Vacation 8 - 05 Cyberium.wav`). Recoverable in principle, but the
  regex would need `^.+ - .+ - (\d{1,2}) ` which is exactly the kind of loose pattern that would
  need its own FP study; 30 tracks in 2 albums is not worth it.
- **8 files** `[unnamed]. artist — title.flac` (Wakaru Records). The number is literally absent —
  the string `[unnamed]` is where it should be. Unrecoverable by definition.

For most of the rest, the correct answer is arguably not "parse harder" but "these are bonus
content, not tracks" — which is the concern of the disc/bonus classifier, not phase 2.

---

## 8. Recommendation

**Adopt, in this order:**

1. **Parse `N/M` in the track tag** (`extract_track_info_from_probed_results`). Highest value by a
   wide margin — 2,440 tracks, 73.4% of all flags, measured 0 disagreements against 87 independent
   cross-checks. This is a tag-reading bug, not a filename problem, and it should land on its own
   regardless of what happens to the filename fallback.
2. **Generalise the extension** in the existing canonical rule from `\.flac` to the alternation.
   168 flagged tracks match, 0 measured track/title disagreements on the 431 non-flac tagged
   controls. Eliminates the entire `.wv` failure class.
3. **Add R2, R3, R7** (`D<sep>NN<sep>title`, `NN. title`, `NNN.ext`). All three measured
   **0.000% track disagreement** across 12,592 tagged controls.
4. **Add R4** (`NN - title`). 0.228%, and all 11 disagreements are one album with offset tags.
5. **Add R5** (`NN-title` / `NN_title`). 0.385% (1 case, a pathological circle name).
6. **Apply the dash split to the title only** — em dash first, then spaced hyphen. Takes overall
   title correctness from 90.83% to 99.01% and cuts wrong titles from 13,108 to 1,174. Do **not**
   populate `artist` from it.
7. **Keep the tag-first merge ordering exactly as it is.** Every FP number above is survivable only
   because a wrong parse can never overwrite a present tag. If that ordering ever changes, the
   R4/R5/R6 rules must be re-evaluated first.

**Adopt with a caveat: R6** (`NN title`, space-separated). It is the largest single contributor to
number recovery among the new rules (61 tracks) but also the least precise at 1.086%. Its 28
disagreements span 5 albums and several are cases where the tag is wrong, not the filename. If a
tighter bar is wanted, gate it behind a per-directory sanity check (numbers distinct and forming a
plausible 1..N run) — though note that such a guard would **not** have caught the observed failures,
which are whole-album off-by-one shifts, so its practical value is limited. My recommendation is to
adopt R6 as-is.

**Reject:** the no-separator rule, all three trailing-number rules, widening the track group beyond
2 digits, and writing a split-derived artist. Together they would add ~313 recovered numbers at the
cost of 1,600+ measured mis-parses.

**Expected outcome:** 3,323 flagged → **609** (81.7% reduction), of which 318 have no digit in the
filename at all and are unrecoverable by any regex, and the bulk of the remainder is bonus content,
DAW project scratch audio, and stem exports rather than real tracks.
