"""
Separates real discs from bonus content by comparing durations, for albums whose
directory names give no answer.

disc_auto_classify resolves an album when every audio directory carries a disc
index in its name. When they do not, the directories still have to be told apart:
an instrumental mirror, an mp3 re-encode of the same disc and a genuine second
disc all look alike from the name alone. Durations distinguish them.

Two guards, both from measuring this library:

  DEDUPE   Two directories whose track durations line up are the same content in
           another form -- an instrumental disc, a lower-bitrate copy, a "web fix"
           re-drop. The mirror is not a disc. Matching is on the multiset of
           durations rather than order, because re-encodes reorder freely.

  PROMOTE  A directory with no disc-like name is still a disc if it carries a
           real programme: at least MIN_TRACKS tracks and MIN_MINUTES of audio.
           Bonus folders are typically one or two files, or a handful of short
           extras. Six albums in the review had genuine discs with no disc token
           anywhere in the name and are only findable this way.

Writes the same artifact schema as disc_auto_classify and merges into it, so the
two stages together produce one file for info_scanner_ph1.
"""

import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import Shared.utils as utils
from Processor.InfoCollector.AlbumInfo.disc_auto_classify import disc_index_from_name
from Processor.InfoCollector.AlbumInfo.disc_scanner import (
    ACCEPTED_AUDIO_FILE_EXTENSIONS,
    looks_like_disc,
    never_a_disc,
)
from Processor.InfoCollector.AlbumInfo.output.path_definitions import (
    DISC_MANUAL_CHECKER_OUTPUT_NAME,
)
from Shared.json_utils import json_dump, json_load

# A directory has to carry a real programme to count as a disc on measurement
# alone. The smallest genuine disc in the reviewed set was 3 tracks / 15:42, and
# the largest bonus folder that is not a disc was 2 files.
MIN_TRACKS = 3
MIN_MINUTES = 12.0

# Two directories are the same content when their duration multisets align.
# 8s tolerance absorbs lossy re-encode drift and differing pregap handling.
DEDUPE_TOLERANCE_S = 8.0
DEDUPE_MATCH_RATIO = 0.85

MAX_WORKERS = max(1, (os.cpu_count() or 4) - 2)

output_root = utils.get_file_relative(__file__, "output")
disc_output_file = os.path.join(output_root, DISC_MANUAL_CHECKER_OUTPUT_NAME)
review_file = os.path.join(output_root, "disc_auto_classify.review.output.json")
guard_review_file = os.path.join(output_root, "disc_duration_guard.review.output.json")

_lock = threading.Lock()


def durations(directory: str) -> List[float]:
    """Track durations in a directory, non-recursive. Unreadable files are skipped."""
    out = []
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return out

    for name in names:
        if not name.lower().endswith(ACCEPTED_AUDIO_FILE_EXTENSIONS):
            continue
        path = os.path.join(directory, name)
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True,
        )
        try:
            out.append(float(proc.stdout.decode("utf-8", "replace").strip()))
        except ValueError:
            continue
    return out


def is_mirror(a: List[float], b: List[float]) -> bool:
    """
    Whether two duration lists describe the same content.

    Greedy multiset match rather than positional: a re-encode or instrumental
    version keeps the runtimes but not necessarily the order.
    """
    if not a or not b:
        return False
    if abs(len(a) - len(b)) > max(1, 0.2 * max(len(a), len(b))):
        return False

    remaining = sorted(b)
    matched = 0
    for value in sorted(a):
        for i, candidate in enumerate(remaining):
            if abs(candidate - value) <= DEDUPE_TOLERANCE_S:
                remaining.pop(i)
                matched += 1
                break
    return matched / max(len(a), len(b)) >= DEDUPE_MATCH_RATIO


def relative(album: str, directory: str) -> str:
    return directory[len(album) + 1:] if directory.startswith(album) else directory


def classify(album: str, audio_dirs: List[str]):
    """Returns (discs, reason) in disc_auto_classify's contract."""
    # Production material is excluded before anything is measured. Promotion
    # rests on track count and duration, and a stem folder or a DAW project's
    # media directory outscores the album it belongs to.
    excluded = {d: why for d in audio_dirs
                if (why := never_a_disc(relative(album, d))) is not None}
    audio_dirs = [d for d in audio_dirs if d not in excluded]
    if not audio_dirs:
        return None, {"verdict": "no candidate directories after exclusions",
                      "excluded": {os.path.basename(k): v
                                   for k, v in excluded.items()}}

    measured = {d: durations(d) for d in audio_dirs}

    # DEDUPE: drop any directory that mirrors an earlier one. The earlier one in
    # sorted order is kept, which favours "Disc 1" over "Disc 1 (mp3)".
    ordered = sorted(audio_dirs)
    kept: List[str] = []
    dropped: Dict[str, str] = {}
    for d in ordered:
        mirror_of = next((k for k in kept if is_mirror(measured[d], measured[k])), None)
        if mirror_of is None:
            kept.append(d)
        else:
            dropped[d] = mirror_of

    # PROMOTE: what survives has to look like a programme, not an extra -- unless
    # its name already says it is a disc. The size test exists to judge
    # directories whose names carry no information; applying it to a named disc
    # discards evidence in favour of a guess. A 2-track, 6:48 "CD1" is a short
    # disc, not a bonus folder, and dropping it renumbered CD2 to disc 1.
    discs = [
        d for d in kept
        if looks_like_disc(os.path.basename(d))
        or (len(measured[d]) >= MIN_TRACKS
            and sum(measured[d]) / 60.0 >= MIN_MINUTES)
    ]
    rejected = [d for d in kept if d not in discs]

    # A single disc that is NOT the album root still has to be written out.
    # info_scanner_ph1 falls back to process_one() for any album missing from the
    # artifact, and that only reads audio sitting directly in the album root; it
    # promotes subdirectory tracks solely when they all share one directory,
    # which a surviving mirror prevents. Leaving these out yields an album with
    # zero tracks -- 12 of them here. Where the disc IS the album root, ph1 finds
    # it unaided and no entry is needed.
    if len(discs) == 1 and discs[0] != album:
        return [{"path": discs[0], "disc_number": 1,
                 "disc_name": os.path.basename(discs[0])}], {
            "dropped_as_mirror": {os.path.basename(k): os.path.basename(v)
                                  for k, v in dropped.items()},
            "dropped_as_small": [os.path.basename(d) for d in rejected],
            "note": "single disc, held in a subdirectory rather than the album root",
            "excluded": {os.path.basename(k): v for k, v in excluded.items()},
        }

    if len(discs) < 2:
        return None, {
            "verdict": "single disc after guards",
            "dropped_as_mirror": {os.path.basename(k): os.path.basename(v)
                                  for k, v in dropped.items()},
            "too_small": [
                f"{os.path.basename(d)} ({len(measured[d])} trk, "
                f"{sum(measured[d])/60:.1f} min)" for d in rejected
            ],
            "excluded": {os.path.basename(k): v for k, v in excluded.items()},
        }

    indices = [disc_index_from_name(os.path.basename(d)) for d in discs]
    order = {d: n for n, d in enumerate(sorted(discs), start=1)}
    resolved = [i if i is not None else order[d] for d, i in zip(discs, indices)]
    if sorted(resolved) != list(range(1, len(resolved) + 1)):
        resolved = [order[d] for d in discs]  # names disagreed; use position

    entry = [
        {"path": d, "disc_number": i, "disc_name": os.path.basename(d)}
        for d, i in sorted(zip(discs, resolved), key=lambda x: x[1])
    ]
    note = {
        "dropped_as_mirror": {os.path.basename(k): os.path.basename(v)
                              for k, v in dropped.items()},
        "dropped_as_small": [os.path.basename(d) for d in rejected],
        "excluded": {os.path.basename(k): v for k, v in excluded.items()},
    }
    return entry, note


def main():
    if not os.path.isfile(review_file):
        print(f"Run disc_auto_classify.py first; {review_file} not found.")
        sys.exit(1)

    review = json_load(review_file)
    targets = {
        album: info["audio_dirs"]
        for album, info in review.items()
        if info["reason"].startswith("no usable disc names")
    }
    print(f"Albums to resolve by duration: {len(targets)}")
    if not targets:
        return

    resolved: Dict[str, List[dict]] = {}
    still_review: Dict[str, dict] = {}
    notes: Dict[str, dict] = {}
    state = {"n": 0}

    def work(item):
        album, dirs = item
        entry, note = classify(album, dirs)
        with _lock:
            state["n"] += 1
            if entry is None:
                still_review[album] = {"reason": "duration guard: " + note["verdict"],
                                       "detail": note, "audio_dirs": dirs}
            else:
                resolved[album] = entry
                notes[album] = note
            if state["n"] % 25 == 0:
                print(f"  [{state['n']}/{len(targets)}]", end="\r")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        list(executor.map(work, targets.items()))

    print(f"  [{state['n']}/{len(targets)}]     ")

    # Merge into the artifact produced by disc_auto_classify.
    artifact = json_load(disc_output_file) if os.path.isfile(disc_output_file) else {}
    before = len(artifact)
    artifact.update(resolved)
    json_dump(artifact, disc_output_file)

    # Anything still unresolved joins the remaining review reasons.
    remaining = {a: i for a, i in review.items()
                 if not i["reason"].startswith("no usable disc names")}
    remaining.update(still_review)
    json_dump(remaining, review_file)
    json_dump(notes, guard_review_file)

    print(f"\nResolved by duration : {len(resolved)}")
    print(f"Still needs review   : {len(still_review)}")
    print(f"Artifact albums      : {before} -> {len(artifact)}")
    mirrors = sum(len(n['dropped_as_mirror']) for n in notes.values())
    smalls = sum(len(n['dropped_as_small']) for n in notes.values())
    print(f"Directories dropped  : {mirrors} as mirrors, {smalls} as too small")
    print(f"\nWrote {disc_output_file}")
    print(f"Wrote {guard_review_file}  (what each album dropped and why)")


if __name__ == "__main__":
    main()
