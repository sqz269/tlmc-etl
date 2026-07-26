"""
Turns disc_scanner output into the artifact info_scanner_ph1 consumes, without
the interactive pass, for the albums where the answer is unambiguous.

disc_man_checker asks a human about every flagged album. Most of them do not need
asking: if every audio directory carries a disc index in its name, the album is
multi-disc and the numbering is right there. This resolves those, emits the same
schema, and leaves a separate review file listing exactly what still needs eyes.

Emitted schema, matching disc_man_checker:

    {"<album path>": [{"path": <disc dir>, "disc_number": int, "disc_name": str}]}

disc_man_checker derives disc_number with `INTEGER_EXTRACTOR.search(basename)`,
which returns -1 for any directory without a digit. That marker means "a human
must fix this" (Docs/STEPS.md), and it fires on real disc names -- `DISC A`,
`DISC ONE`, `Chapter of KARIUTA`, `Side-A`. Letters, words and kanji are decoded
here instead, and ordinal position is the last resort, so -1 is never emitted.
"""

import json
import os
import re
import sys
from typing import Dict, List, Optional

import Shared.utils as utils
from Processor.InfoCollector.AlbumInfo.disc_scanner import (
    ACCEPTED_AUDIO_FILE_EXTENSIONS,
    MAX_AUDIO_DIRS_FOR_AUTO_DISC,
    looks_like_disc,
    recurse_search_for_tracks,
)
from Processor.InfoCollector.AlbumInfo.output.path_definitions import (
    DISC_MANUAL_CHECKER_OUTPUT_NAME,
    DISC_SCANNER_OUTPUT_NAME,
)
from Shared.json_utils import json_dump, json_load

output_root = utils.get_file_relative(__file__, "output")
scanned_output_file = os.path.join(output_root, DISC_SCANNER_OUTPUT_NAME)
disc_output_file = os.path.join(output_root, DISC_MANUAL_CHECKER_OUTPUT_NAME)
review_output_file = os.path.join(output_root, "disc_auto_classify.review.output.json")

_NUM = re.compile(r"(\d{1,2})(?!\d)")
_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "壱": 1, "弐": 2, "参": 3, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
}
# "Side-A"/"DISC B" and the colour/word pairs that stand in for an index.
_LETTERS = {c: i + 1 for i, c in enumerate("abcdefgh")}
_NAMED_PAIRS = {
    "red": 1, "white": 2, "black": 2, "blue": 2,
    "a": 1, "b": 2, "c": 3, "d": 4,
}


def disc_index_from_name(name: str) -> Optional[int]:
    """
    Disc number encoded in a directory name, or None.

    Tries digits, then a word or kanji numeral, then a trailing letter/colour
    index. Anything else is left to ordinal position.
    """
    low = name.lower()

    # An index sitting next to a disc token beats a bare digit elsewhere in the
    # name. "THVA2_ASide" is disc A of an album called THVA2, not disc 2.
    m = re.search(r"(?:disc|disk|ディスク|cd|side|file)\s*[:：._\-（(]?\s*(\d{1,2})(?!\d)", low)
    if m:
        value = int(m.group(1))
        if 1 <= value <= 30:
            return value

    m = re.search(
        r"(?:disc|disk|ディスク|side|file)\s*[:：._\-]?\s*([a-h]|red|white|black|blue)\b",
        low,
    )
    if m:
        return _NAMED_PAIRS.get(m.group(1))

    m = re.search(r"(?:^|[\s\-_（(【])([a-h])side\b", low)
    if m:
        return _LETTERS.get(m.group(1))

    for word, value in _WORDS.items():
        if re.search(rf"(?:^|[\s\-_（(【:：]){re.escape(word)}(?:$|[\s\-_）)】])", low):
            return value

    # Last resort: any small number in the name. Least reliable, because album
    # titles carry version and catalogue digits.
    m = _NUM.search(name)
    if m:
        value = int(m.group(1))
        if 1 <= value <= 30:
            return value

    return None


def classify_album(album: str, audio_dirs: List[str]):
    """
    Returns (discs, reason). `discs` is the artifact entry, or None when the
    album needs a human, in which case `reason` says why.
    """
    if len(audio_dirs) > MAX_AUDIO_DIRS_FOR_AUTO_DISC:
        return None, "container: more than %d audio directories, likely several releases" % MAX_AUDIO_DIRS_FOR_AUTO_DISC

    # Single directory means the split, if any, is encoded in filenames. The
    # files have to be reorganised into per-disc directories first; this stage
    # does not move anything.
    if len(audio_dirs) == 1 and audio_dirs[0] == album:
        return None, "filename-encoded discs: needs reorganising into per-disc directories"

    named = [d for d in audio_dirs if looks_like_disc(os.path.basename(d))]
    if len(named) < 2:
        return None, "no usable disc names: needs duration comparison to tell discs from bonus content"

    if len(named) != len(audio_dirs):
        skipped = [os.path.basename(d) for d in audio_dirs if d not in named]
        # The unnamed directories are bonus/instrumental/alternate encodings.
        # Confident enough to drop them, but say so.
        reason = "dropped non-disc directories: " + ", ".join(sorted(skipped)[:4])
    else:
        reason = None

    indices = [disc_index_from_name(os.path.basename(d)) for d in named]
    if len(set(i for i in indices if i is not None)) != len([i for i in indices if i is not None]):
        return None, "duplicate disc numbers derived from names"

    # Fill any gaps by sorted position rather than emitting -1.
    order = {d: n for n, d in enumerate(sorted(named), start=1)}
    resolved = [
        idx if idx is not None else order[d]
        for d, idx in zip(named, indices)
    ]
    if sorted(resolved) != list(range(1, len(resolved) + 1)):
        # Non-contiguous numbering: real (a 3-disc set ripped as 1 and 3) or a
        # misparse. Either way a human should look.
        return None, f"non-contiguous disc numbers {sorted(resolved)}"

    discs = [
        {"path": d, "disc_number": i, "disc_name": os.path.basename(d)}
        for d, i in sorted(zip(named, resolved), key=lambda x: x[1])
    ]
    return discs, reason


def main():
    if not os.path.isfile(scanned_output_file):
        print(f"Run disc_scanner.py first; {scanned_output_file} not found.")
        sys.exit(1)

    scanned: Dict[str, List[str]] = json_load(scanned_output_file)
    resolved: Dict[str, List[dict]] = {}
    review: Dict[str, dict] = {}
    notes = 0

    for album, audio_dirs in scanned.items():
        discs, reason = classify_album(album, audio_dirs)
        if discs is None:
            review[album] = {"reason": reason, "audio_dirs": audio_dirs}
        else:
            resolved[album] = discs
            if reason:
                notes += 1

    json_dump(resolved, disc_output_file)
    json_dump(review, review_output_file)

    print(f"Flagged albums      : {len(scanned)}")
    print(f"Auto-classified     : {len(resolved)}  ({notes} dropped a non-disc directory)")
    print(f"Needs review        : {len(review)}")
    by_reason: Dict[str, int] = {}
    for entry in review.values():
        key = entry["reason"].split(":")[0]
        by_reason[key] = by_reason.get(key, 0) + 1
    for key, count in sorted(by_reason.items(), key=lambda x: -x[1]):
        print(f"    {count:4d}  {key}")
    print(f"\nWrote {disc_output_file}")
    print(f"Wrote {review_output_file}")
    print("\nAlbums NOT flagged by disc_scanner are single-disc and need no entry;")
    print("info_scanner_ph1 treats a missing album as one disc.")


if __name__ == "__main__":
    main()
