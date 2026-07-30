"""Pushes formatted lyrics to the v6 backend.

Replaces Finalizer/ApiPushToDb/ExternalInfo/lyrics_push.py (the generated
OpenAPI client is gone — plain requests against the snake_case wire). Reads
LyricsInfo rows in PARSE_PROCESSED state (stage 8 formatter output) and calls

  PUT api/internal/track/{remote_track_id}/lyrics  {variants, reference_url}

The endpoint replaces the whole lyrics document, so the script is re-runnable.
The variants document shape mirrors the backend's jsonb contract:
  [{variant, lines: [{index, time, blocks: [{lang, text, ruby: [{index, length, text}]}]}]}]
"""

import json
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from ExternalInfo.ThwikiInfoProvider.PushChange.api_client import (
    make_session,
    send,
    track_typeid,
)
from ExternalInfo.ThwikiInfoProvider.ThwikiLyricsPageScraper.lyrics_formatter import (
    LyricsAnnotatedLine,
)
from ExternalInfo.ThwikiInfoProvider.ThwikiLyricsPageScraper.Model.ThwikiLyricsInfoModel import (
    LyricsInfo,
    LyricsProcessingStatus,
)

THWIKI_BASE_URL = "https://thwiki.cc/"


def pad_timespan(timespan: Optional[str]) -> Optional[str]:
    if timespan is None:
        return None

    # "mm:ss.SSS" (missing hours) -> "00:mm:ss.SSS", carrying second overflow
    match = re.match(r"^(\d{2}):(\d{2,3})\.(\d+)$", timespan)
    if match:
        minutes, seconds, milliseconds = match.groups()
        total_seconds = int(seconds)
        corrected_minutes = int(minutes) + total_seconds // 60
        corrected_seconds = total_seconds % 60
        return f"00:{corrected_minutes:02}:{corrected_seconds:02}.{milliseconds}"

    # "mm:ss." -> "00:mm:ss.00"
    match = re.match(r"^(\d{2}):(\d{2})[.,]$", timespan)
    if match:
        minutes, seconds = match.groups()
        return f"00:{minutes}:{seconds}.00"

    # "mm.ss" -> "00:mm:ss.00"
    match = re.match(r"^(\d{2})\.(\d{2})$", timespan)
    if match:
        minutes, seconds = match.groups()
        return f"00:{minutes}:{seconds}.00"

    return timespan


def fix_mistyped_timestamp(timespan: Optional[str]) -> Optional[str]:
    if not timespan:
        return timespan
    timespan = timespan.strip().strip("[]{}()qwertyuiopasdfghjklzxcvbnm")
    timespan = timespan.replace(",", ".")

    # "hh:mm:ss" where the tail is really decimal seconds
    match = re.match(r"^(\d{2}):(\d{2}):(\d+)$", timespan)
    if match:
        hours, minutes, seconds = match.groups()
        return f"{hours}:{minutes}.{seconds}"

    # "mm.ss.SSS" -> "00:mm:ss.SSS"
    match = re.match(r"^(\d{2})\.(\d{2})\.(\d+)$", timespan)
    if match:
        minutes, seconds, milliseconds = match.groups()
        return f"00:{minutes}:{seconds}.{milliseconds}"

    return timespan


def normalize_time(timespan: Optional[str]) -> Optional[str]:
    return pad_timespan(fix_mistyped_timestamp(timespan))


def json_to_variants(lyrics_info: LyricsInfo) -> Optional[List[dict]]:
    """The v5 transform, emitting plain dicts. Returns None when empty."""
    if not lyrics_info.lyrics:
        return None

    data: Dict[str, Dict[str, Any]] = json.loads(lyrics_info.lyrics)

    # Drop the need_review flag and languages with no non-empty line.
    cleaned: Dict[Optional[str], Dict[str, list]] = {}
    for variant, lang_lyrics in data.items():
        if variant == "need_review":
            continue
        if variant == "null":
            variant = None

        for lang, lines in lang_lyrics.items():
            if any(line["text"] for line in lines):
                cleaned.setdefault(variant, {})[lang] = lines

    variants: List[dict] = []
    for variant, lang_lyrics in cleaned.items():
        # Lines merge across languages by list position: index N of every
        # language forms one line's blocks (the v5 alignment convention).
        index_lines: Dict[int, dict] = {}
        for lang, lines in lang_lyrics.items():
            for idx, raw_line in enumerate(lines):
                annotated = LyricsAnnotatedLine.from_json(raw_line)

                block = {
                    "lang": lang,
                    "text": annotated.text,
                    "ruby": [
                        {
                            "index": ann.index,
                            "length": ann.length,
                            "text": ann.text,
                        }
                        for ann in annotated.annotations
                        if ann.text is not None
                    ],
                }

                line = index_lines.get(idx)
                if line is None:
                    index_lines[idx] = {
                        "index": idx,
                        "time": normalize_time(annotated.time),
                        "blocks": [block],
                    }
                else:
                    line["blocks"].append(block)

        variants.append({
            "variant": variant,
            "lines": [index_lines[i] for i in sorted(index_lines)],
        })

    return variants or None


def main():
    session = make_session()

    entries = list(
        LyricsInfo.select().where(
            LyricsInfo.process_status == LyricsProcessingStatus.PARSE_PROCESSED
        )
    )
    print(f"{len(entries)} formatted lyrics entries")

    pushed = empty = 0
    failures = []
    for i, entry in enumerate(entries, 1):
        variants = json_to_variants(entry)
        if not variants:
            empty += 1
            continue

        reference_title = entry.wiki_page_title_actual or entry.wiki_page_title_constructed
        payload = {
            "variants": variants,
            "reference_url": THWIKI_BASE_URL + reference_title if reference_title else None,
        }

        resp = send(
            session,
            "PUT",
            f"/api/internal/track/{track_typeid(entry.remote_track_id)}/lyrics",
            payload,
        )
        if resp.status_code == 200:
            pushed += 1
        else:
            failures.append(
                f"{entry.remote_track_id} ({entry.track_id}): {resp.status_code} {resp.text[:200]}"
            )

        if i % 200 == 0 or i == len(entries):
            print(f"[{i}/{len(entries)}] pushed {pushed}, empty {empty}, failures {len(failures)}", end="\r")

    print()
    print(f"Done: {pushed} pushed, {empty} empty, {len(failures)} failures.")
    if failures:
        with open("push_lyrics_failures.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(failures) + "\n")
        print("See push_lyrics_failures.txt")


if __name__ == "__main__":
    main()
