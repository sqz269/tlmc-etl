import os
import re
from typing import Dict, List, Tuple

import Shared.utils as utils
from Processor.InfoCollector.AlbumInfo.output.path_definitions import (
    DISC_SCANNER_OUTPUT_NAME,
)
from Shared.json_utils import json_dump, json_load

output_root = utils.get_file_relative(__file__, "output")
os.makedirs(output_root, exist_ok=True)
scanned_output_file = os.path.join(output_root, DISC_SCANNER_OUTPUT_NAME)


ACCEPTED_AUDIO_FILE_EXTENSIONS = (".flac", ".mp3", ".wav", ".wv", ".m4a")

INTEGER_EXTRACTOR = re.compile(r"(\d+)")

# Matches a leading "<disc><sep><track>" prefix. Only meaningful when EVERY file
# in the album matches it -- see filename_discs().
DISC_TRACK_PREFIX = re.compile(r"^(\d{1,2})[-._ ](\d{1,3})(?!\d)")

# The old heuristic was `^\d+\D\d+.+$` on *any* file in a single directory.
# Reviewed against all 145 albums it flagged: 126 were wrong, an 86.9% false
# positive rate, in two distinct ways.
#
#   * 98 albums use "1-01.", "1.01 -", "01_01_" as their ordinary naming
#     convention. The leading number is a constant 1 (or 0 as a placeholder) and
#     the second number is simply the track. Single disc.
#   * 27 albums merely contain a digit pair inside ONE track's title -- "07 5 2
#     9.flac", "14 333bit.flac", "01 864000sec.flac". Seven matched on the artist
#     name "2K7". In 25 of them only 1-3 files out of 6-21 matched at all.
#
# Requiring every file to match kills the second class; requiring at least two
# distinct leading values kills the first.
MIN_FILES_FOR_FILENAME_DISCS = 4
MAX_PLAUSIBLE_DISCS = 20

# --- directory-name classification -------------------------------------------
#
# Derived from a review of 1,428 audio directories across 340 albums. Measured
# accuracy of the name rules alone: 97.65% (332/340 albums), and the three
# "never a disc" families below were correct on 633 of 633 directories.
#
# The rules are ordered and first-match-wins; the order carries meaning:
#   DISC_INDEX before FORMAT  keeps "DISC2 (FLAC)"
#   BONUS      before BARE_DISC kills "Bonus Disc", "Present Disc"
#   FORMAT     before BARE_DISC kills "WAV DISC"
#
# A disc token can sit anywhere in the name, may use a letter/kanji/word index,
# fullwidth punctuation or katakana, and "Side" counts. Anchoring on
# ^(disc|cd)\d+ misses 167 real discs in this library.

DISC_INDEX = re.compile(
    r"(?:disc|disk|disque|ディスク|disc)\s*[:：._\-]?\s*(?:\d+|[a-z]\b|one|two|three|four)"
    r"|(?:^|[\s\-_（(【])side\s*[:：._\-]?\s*(?:\d+|[a-z]\b|red|white|black)"
    r"|\bfile\s*[:：]\s*[a-z0-9]\b"
    # "THVA2_ASide" / "BSide": the index letter is glued to the word, so there is
    # no word boundary before it.
    r"|(?:^|[\s\-_（(【])[a-z]?side\b"
    r"|chapter\s+of\s+",
    re.I,
)
FORMAT_TOKEN = re.compile(
    r"\b(?:mp3|wav|wave|flac|wv|m4a|aac|ogg|opus)\b|\d{2,3}\s*kbps|\b(?:16|24)\s*bit"
    r"|\b(?:44|48|88|96|192)(?:\.1)?\s*k(?:hz)?\b|hi-?res|ハイレゾ|\d{2}k[-_]\d{2}",
    re.I,
)
VARIANT_TOKEN = re.compile(
    r"\bver(?:sion)?\b|\bvar\b|web|booth|bandcamp|dizzylab|steam|pixiv"
    r"|\bDL\b|download|\bfix\b",
    re.I,
)
BONUS_TOKEN = re.compile(
    r"bonus|おまけ|オマケ|特典|extra|inst(?:rument)?|off\s*vocal|オフボーカル|カラオケ"
    r"|comment|コメント|drama|ドラマ|voice|ボイス|sample|サンプル|demo|stem|secret|隠し"
    r"|promotion|xfd|crossfade|special|postcard|その他|\bdata\b|cd\s*extra|omake"
    r"|trial|preview|試聴|仮歌|素材|present|liner|修正|追加|楽曲",
    re.I,
)
BARE_DISC = re.compile(r"disc|disk|ディスク", re.I)

# No real multi-disc album in the reviewed set had more than 5 audio directories;
# beyond that the directory is a container holding several separate releases
# (DVD-R compilations, box sets), which must be split at album level first.
MAX_AUDIO_DIRS_FOR_AUTO_DISC = 5


def looks_like_disc(dir_name: str) -> bool:
    """
    Whether a directory name denotes a disc rather than supplementary content.

    Order matters -- see the comment above the patterns.
    """
    if DISC_INDEX.search(dir_name):
        return True
    if FORMAT_TOKEN.search(dir_name):
        return False
    if VARIANT_TOKEN.search(dir_name):
        return False
    if BONUS_TOKEN.search(dir_name):
        return False
    return bool(BARE_DISC.search(dir_name))


def filename_discs(files: List[str]) -> bool:
    """
    True when the filenames themselves encode a multi-disc layout.

    Deliberately strict. Embedded disc tags are the better evidence and are
    checked first by the caller; this only runs for albums that have none.
    """
    names = [os.path.basename(f) for f in files]
    if len(names) < MIN_FILES_FOR_FILENAME_DISCS:
        return False

    matches = [DISC_TRACK_PREFIX.match(n) for n in names]
    # The prefix has to be the album's convention, not an accident in one title.
    if not all(matches):
        return False

    discs: Dict[int, List[int]] = {}
    for m in matches:
        discs.setdefault(int(m.group(1)), []).append(int(m.group(2)))

    if not (2 <= len(discs) <= MAX_PLAUSIBLE_DISCS):
        return False

    # Disc numbers should run 1..N without holes.
    if sorted(discs) != list(range(1, len(discs) + 1)):
        return False

    for tracks in discs.values():
        if len(tracks) < 2 or len(set(tracks)) != len(tracks) or min(tracks) != 1:
            return False
        # Tolerate an incompletely ripped disc (e.g. tracks 1, 3, 6, 7) rather
        # than demanding a contiguous run, which cost a real multi-disc album.
        if max(tracks) > 2 * len(tracks):
            return False

    return True


def list_dir(path: str) -> List[str]:
    """
    Entries of `path`, or an empty list if it cannot be read.

    ext4's root-owned `lost+found` sits at the root of the library and raises
    PermissionError from a bare os.listdir, which used to abort the whole scan.
    """
    try:
        return sorted(os.listdir(path))
    except OSError as e:
        print(f"Skipping unreadable directory {path}: {e}")
        return []


def recurse_search_for_tracks(path: str) -> Dict[str, List[str]]:
    def _recuse_helper(path: str, result: Dict[str, List[str]]):
        for file in list_dir(path):
            file_path = os.path.join(path, file)
            try:
                is_dir = os.path.isdir(file_path)
                is_file = os.path.isfile(file_path)
            except OSError:
                continue

            if is_dir:
                _recuse_helper(file_path, result)

            elif is_file:
                if file.endswith(ACCEPTED_AUDIO_FILE_EXTENSIONS):
                    if path not in result:
                        result[path] = [file_path]
                    else:
                        result[path].append(file_path)

    result = {}
    _recuse_helper(path, result)
    return result


def check_album_dir(album_root: str):
    result = recurse_search_for_tracks(album_root)

    # Audio in several directories: each one is a candidate disc. Whether they
    # really are discs rather than bonus/instrumental/alternate-encoding folders
    # is decided downstream by disc_man_checker.
    #
    # Audio in a single directory: the only evidence for a split is the
    # filenames, and that evidence has to be strong (see filename_discs).
    potential_disc_dirs = []
    if len(result) == 1:
        for root, files in result.items():
            if filename_discs(files):
                potential_disc_dirs.append(root)
        return potential_disc_dirs

    # More than one directory holds audio. Most of the time the extras are
    # instrumentals, alternate encodings, web-fix drops or bonus material rather
    # than discs -- across 340 reviewed albums only 24% were genuinely
    # multi-disc. Filter on the directory name before flagging anything.
    if len(result) > MAX_AUDIO_DIRS_FOR_AUTO_DISC:
        # A container holding several separate releases (DVD-R compilations,
        # box sets). These need splitting at album level first, and two of them
        # contained two different directories both named "Disc 1", which would
        # collide on disc index. Flag the whole album for review instead.
        return list(result.keys())

    named = [d for d in result if looks_like_disc(os.path.basename(d))]
    if len(named) >= 2:
        return named

    # No usable disc names. A directory can still be a real disc -- six albums
    # in the review had none -- but that needs track counts, so leave the
    # judgement to disc_man_checker and flag every candidate.
    return list(result.keys())


def scan_discs(tlmc_root: str) -> Dict[str, List[str]]:
    potentials = {}
    scanned = 0
    for artist_dir in list_dir(tlmc_root):
        artist_dir_path = os.path.join(tlmc_root, artist_dir)
        if not os.path.isdir(artist_dir_path):
            continue

        for album_dir in list_dir(artist_dir_path):
            album_dir_path = os.path.join(artist_dir_path, album_dir)
            if not os.path.isdir(album_dir_path):
                continue

            potential = check_album_dir(album_dir_path)
            scanned += 1
            if len(potential) > 0:
                potentials[album_dir_path] = potential

            if scanned % 500 == 0:
                print(f"[{scanned}] scanned, {len(potentials)} flagged", end="\r")

    print(f"[{scanned}] scanned, {len(potentials)} flagged")
    return potentials


def main():
    tlmc_root = input("Enter TLMC root: ")
    if not os.path.isdir(tlmc_root):
        print("Invalid path")
        exit(1)

    result = scan_discs(tlmc_root)
    print("Found {} potential discs".format(len(result)))
    json_dump(result, scanned_output_file)
    print(f"Wrote {scanned_output_file}")


if __name__ == "__main__":
    main()
