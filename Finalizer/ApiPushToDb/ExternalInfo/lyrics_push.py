from collections import defaultdict
import json
from itertools import chain
import re
from typing import Any, Dict, List, Optional, Tuple
import uuid
from backend_api_client import Configuration, TrackApi, InternalApi
from backend_api_client.api_client import ApiClient
from backend_api_client import Lyrics, LyricsVariant, LyricsLine, LyricsText, Ruby
from ExternalInfo.ThwikiInfoProvider.ThwikiLyricsPageScraper.lyrics_formatter import LyricsAnnotatedLine
from Shared.json_utils import json_load, json_dump
from ExternalInfo.ThwikiInfoProvider.ThwikiAlbumPageScraper.Model.ThcSongInfoModel import (
    Track,
    Album,
)
from ExternalInfo.ThwikiInfoProvider.ThwikiLyricsPageScraper.Model.ThwikiLyricsInfoModel import (
    LyricsInfo,
    LyricsProcessingStatus,
)

BACKEND_API_BASEURL = "http://192.168.88.248:5294"
THWIKI_BASE_URL = "https://thwiki.cc/"


def pad_timespan(timespan: Optional[str]) -> Optional[str]:
    if timespan is None:
        return None

    # Regular expression to match "mm:ss.SSS" or "mm:ss.S" format (missing hours)
    pattern = re.compile(r"^(\d{2}):(\d{2,3})\.(\d+)$")

    match = pattern.match(timespan)
    if match:
        minutes, seconds, milliseconds = match.groups()
        total_seconds = int(seconds)
        extra_minutes = total_seconds // 60
        corrected_seconds = total_seconds % 60
        corrected_minutes = int(minutes) + extra_minutes
        return f"00:{corrected_minutes:02}:{corrected_seconds:02}.{milliseconds}"

    # Fix format like "mm:ss." to "mm:ss.00"
    pattern_missing_ms = re.compile(r'^(\d{2}):(\d{2})[.,]$')
    match_missing_ms = pattern_missing_ms.match(timespan)
    if match_missing_ms:
        minutes, seconds = match_missing_ms.groups()
        return f"00:{minutes}:{seconds}.00"

    # Fix format like "mm.ss" to "mm:ss.00"
    pattern_alt_format = re.compile(r'^(\d{2})\.(\d{2})$')
    match_alt_format = pattern_alt_format.match(timespan)
    if match_alt_format:
        minutes, seconds = match_alt_format.groups()
        return f"00:{minutes}:{seconds}.00"

    # Return original if already correct
    return timespan

def fix_mistyped_timestamp(timespan: Optional[str]) -> Optional[str]:
    if not timespan:
        return timespan
    timespan = timespan.strip().strip("[]{}()qwertyuiopasdfghjklzxcvbnm")
    timespan = timespan.replace(",", ".")

    # Regular expression to match "hh:mm:ss" where ss can be mistyped
    pattern = re.compile(r'^(\d{2}):(\d{2}):(\d+)$')
    
    match = pattern.match(timespan)
    if match:
        hours, minutes, seconds = match.groups()
        # Assume last part is decimal seconds instead of full seconds
        return f"{hours}:{minutes}.{seconds}"
    
    pattern_alt = re.compile(r'^(\d{2})\.(\d{2})\.(\d+)$')
    match_alt = pattern_alt.match(timespan)
    if match_alt:
        minutes, seconds, milliseconds = match_alt.groups()
        return f"00:{minutes}:{seconds}.{milliseconds}"

    return timespan

def json_to_lyrics(lyrics_info: LyricsInfo) -> Lyrics:
    if not lyrics_info.lyrics:
        return None
    
    data: Dict[str, Dict[str, Any]] = json.loads(lyrics_info.lyrics)

    # Tuple of variant type, and a time indexed annotation lines
    lyrics_variants: List[LyricsVariant] = []
    for variant, lang_lyrics in data.items():
        if variant == 'need_review':
            continue

        if variant == 'null':
            variant = None

        # Map between each time stamp and language and a list of lyrics (of different languages)
        # Access TimeStr -> Lang -> List of lines
        time_mapped: Dict[str, Dict[str, List[Tuple[int, LyricsText]]]] = defaultdict(lambda: defaultdict(list))
        for lang, lyrics in lang_lyrics.items():
            for idx, line in enumerate(lyrics):
                annotated_line = LyricsAnnotatedLine.from_json(line)
                
                rubies: List[Ruby] = []
                for annotation in annotated_line.annotations:
                    if annotation.text is None:
                        continue
                    rubies.append(
                        Ruby(
                            index=annotation.index,
                            length=annotation.length,
                            text=annotation.text
                        )
                    )

                # if not annotated_line.time:
                #     continue

                text = LyricsText(
                    lang=lang,
                    text=annotated_line.text,
                    ruby=rubies
                )

                time_mapped[annotated_line.time][lang].append(
                    (idx, text)
                )
    
        # format time_mapped into lines
        index_lines: Dict[int, LyricsLine] = {}
        # lyrics_variant = LyricsVariant(variant=None, lines=lines)
        for timespan, mapped_entries in time_mapped.items():
            for lang, entries in mapped_entries.items():
                for index, text in entries:
                    if index not in index_lines:
                        index_lines[index] = LyricsLine(
                            index=index,
                            time=pad_timespan(
                                fix_mistyped_timestamp(
                                    timespan
                                )),
                            blocks=[text]
                        )
                    else:
                        index_lines[index].blocks.append(
                            text
                        )
        lyrics_variant = LyricsVariant(
            variant=variant,
            lines=list(chain(index_lines.values()))
        )

        lyrics_variants.append(lyrics_variant)
            
    return Lyrics(
        id=str(uuid.uuid4()),
        variants=lyrics_variants,
        referenceUrl=THWIKI_BASE_URL + lyrics_info.wiki_page_title_constructed
    )

def main():
    api_config = Configuration(host=BACKEND_API_BASEURL)
    # track_api = TrackApi(api_config)
    internal_api = InternalApi(api_client=ApiClient(api_config))

    all_lyrics: Dict[str, Lyrics] = {}
    entry: LyricsInfo
    for entry in LyricsInfo.select().where(
        (LyricsInfo.process_status == LyricsProcessingStatus.PARSE_PROCESSED)
    ):
        all_lyrics[entry.remote_track_id] = json_to_lyrics(entry)
    
    index = 0
    for track_id, lyrics in all_lyrics.items():
        if (not lyrics):
            continue
        index += 1
        print(f"[{index}] Pushing lyrics: {lyrics.id} | TID: {track_id}")
        internal_api.i_nternal_add_lyrics(
            track_id=track_id,
            lyrics_id=lyrics.id,
            lyrics=lyrics
        )


if __name__ == '__main__':
    main()
