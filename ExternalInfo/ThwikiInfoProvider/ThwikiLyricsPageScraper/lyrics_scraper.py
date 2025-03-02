import json
import re
import time
from typing import Dict, List, Optional, Set
import uuid
import httpx
from Shared import utils
from Shared.json_utils import json_load, json_dump
from ExternalInfo.ThwikiInfoProvider.ThwikiAlbumPageScraper.Model.ThcSongInfoModel import (
    Track,
    Album,
)
from ExternalInfo.ThwikiInfoProvider.ThwikiLyricsPageScraper.Model.ThwikiLyricsInfoModel import (
    LyricsInfo,
    LyricsProcessingStatus,
)
import ExternalInfo.ThwikiInfoProvider.ThwikiLyricsPageScraper.Model.ThwikiLyricsModel as LyricsModel
import ExternalInfo.ThwikiInfoProvider.cache.path_definitions as CachePathDef

import ExternalInfo.ThwikiInfoProvider.output.path_definitions as ThwikiOutput
import mwparserfromhell as mw
from mwparserfromhell.nodes.template import Template
from mwparserfromhell.wikicode import Wikicode
from ExternalInfo.CacheInfoProvider.Cache import cached
from ExternalInfo.ThwikiInfoProvider.Shared import ThwikiUtils

album_formatted_output_path = utils.get_output_path(
    ThwikiOutput, ThwikiOutput.THWIKI_ALBUM_FORMAT_RESULT_OUTPUT
)
track_formatted_output_path = utils.get_output_path(
    ThwikiOutput, ThwikiOutput.THWIKI_TRACK_FORMAT_RESULT_OUTPUT
)
score_debug_output_path = utils.get_output_path(
    ThwikiOutput, ThwikiOutput.THWIKI_ALBUM_FORMAT_SCORE_DEBUG_OUTPUT
)
lyrics_wiki_page_cache_path = utils.get_output_path(
    CachePathDef, CachePathDef.THWIKI_LYRICS_WIKI_PAGE_CACHE_DIR
)

cache_dir = utils.get_output_path(CachePathDef, CachePathDef.THWIKI_LYRICS_WIKI_PAGE_CACHE_DIR)


def construct_potential_lyrics_page_title(entry: Track) -> Optional[str]:
    if (entry.lyrics_author is None) or (entry.lyrics_author == ""):
        return None

    page_title: str;

    if (entry.lyrics):
        page_title = json.loads(entry.lyrics)[0]
    else:
        page_title = json.loads(entry.title_jp)[0]

    return f'歌词:{page_title}'


def import_data():
    # load matched
    matched_tracks = json_load(track_formatted_output_path)

    # we need to go from track_id: {<Track Metadata>}
    # to thwiki_track_id: {<Track Metadata>}
    matched_tracks_ids: Dict[str, dict] = {}
    for _, t in matched_tracks.items():
        matched_tracks_ids[t["thwiki_id"]] = t

    total_tracks = Track.select().count()
    json_dump(list(matched_tracks_ids), "matched_tracks_ids.json")
    if total_tracks == 0:
        print("No tracks found in the database")
        return

    tracks_with_lyrics = Track.select().where(Track.lyrics_author.is_null(False))
    tracks_with_lyrics_count = tracks_with_lyrics.count()
    track: Track
    to_process: LyricsInfo = []
    for track in tracks_with_lyrics:
        matched_entry = matched_tracks_ids.get(track.track_id, None)

        if matched_entry is None:
            continue

        page_title = construct_potential_lyrics_page_title(track)
        if page_title is None:
            continue

        to_process.append(
            LyricsInfo(
                track_id=track.track_id,
                remote_track_id=matched_entry["remote_id"],
                lyrics_id=str(uuid.uuid4()),
                wiki_page_title_constructed=page_title,
                process_status=LyricsProcessingStatus.PENDING,
            )
        )

    print(f"Total tracks with lyrics: {tracks_with_lyrics_count}")
    print(f"Total matched tracks with lyrics: {len(to_process)}")

    BATCH_SIZE = 2000
    for i in range(0, len(to_process), BATCH_SIZE):
        print(f"Processing batch {i} to {i+BATCH_SIZE}")
        LyricsInfo.bulk_create(to_process[i:i+BATCH_SIZE])


def follow_redirect(src) -> Optional[str]:
    redirect_keywords = ["#重定向", "#redirect"]
    is_redirect = False
    for keyword in redirect_keywords:
        if keyword in src.lower():
            is_redirect = True
            break

    if not is_redirect:
        return None

    parsed = mw.parse(src)
    redirect_link = parsed.filter_wikilinks()[0]
    return redirect_link.title


@cached(
    "lyric_page_src",
    lyrics_wiki_page_cache_path,
    disable_parse=True,
    debug=True,
    # restore=True,
)
def get_page_source(page_title) -> Optional[str]:
    PAGE_SRC_URL = "https://thwiki.cc/api.php?action=query&prop=revisions&rvprop=content&format=json&titles={path}&utf8=1"
    HEADER = {
        "sec-ch-ua": '" Not A;Brand"lyrics_author;v="99", "Chromium";v="102", "Google Chrome";v="102"',
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://thwiki.cc/",
        "X-Requested-With": "XMLHttpRequest",
        "sec-ch-ua-mobile": "?0",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36",
        "sec-ch-ua-platform": '"Windows"',
    }

    url = PAGE_SRC_URL.format(path=page_title)
    response = httpx.get(url, headers=HEADER)
    if response.status_code != 200:
        print(
            "Failed to get page source for {path}. Error: {code}".format(
                path=url, code=response.status_code
            )
        )
        raise Exception(
            "Failed to get page source for {path}. Error: {code}".format(
                path=url, code=response.status_code
            )
        )

    j = response.json()
    return json.dumps(j, ensure_ascii=False, indent=4)

def get_wiki_page_source(quersrc: str) -> Optional[str]:
    if not quersrc:
        return None
    j = json.loads(quersrc)
    page = list(j["query"]["pages"].values())[0]
    if "missing" in page:
        return None

    try:
        page["revisions"][0]["*"]
    except KeyError:
        return None

    return page["revisions"][0]["*"]


def get_lyrics_actual_handle_table(full_src: str) -> LyricsModel.ThwikiLyrics:
    lyrics = LyricsModel.ThwikiLyrics(sections=[])

    # check for tabbers and sections
    parsed = mw.parse(full_src)
    tabbers = [tabber for tabber in parsed.filter_tags() if tabber.tag == 'tabber'] 
    if len(tabbers) == 0:
        lyrics.sections.append(get_lyrics_actual(full_src, None))
        return lyrics
    
    assert len(tabbers) == 1, "Multiple tabbers found in the lyrics page"

    tabber_contents = tabbers[0].contents
    l = [l for l in str(tabber_contents).split("\n") if l]
    # the first line going to be the first tab's header
    # and after that, each separate tab is splitted by `|-|` 
    # with the tab header immediately after

    tab_segments = [i for i, x in enumerate(l) if x == "|-|"]
    tab_segments.append(len(l))
    tab_segments.insert(0, 0)
    tab_segment_contents = [l[tab_segments[i]:tab_segments[i+1]] for i in range(len(tab_segments)-1)]
    # Remove the |-| lines if they exists for each segments
    tab_segment_contents = [list(filter(lambda x: x != "|-|", segment)) for segment in tab_segment_contents]
    for segment in tab_segment_contents:
        segment_title = segment[0].split("=")[0].strip()
        lyrics.sections.append(get_lyrics_actual("\n".join(segment), segment_title))

    return lyrics

def get_lyrics_actual(src_section: str, section_title: Optional[str]) -> LyricsModel.ThwikiLyricsSection:
    section = LyricsModel.ThwikiLyricsSection(section_title, time_instants={})
    lyrics = {}
    is_in_lyrics_section = False
    current_timestamp = None
    lyrics_section_term = [
        "--",
        "==",
        "__",
    ]
    check_lyrics_line = r'^[A-Za-z]{2}=$'

    # used in case there is no timestamp
    current_timestamp_default = 0

    # we need to handle original lyrics that are purely english
    # and lyrics that mixes japanese and english
    # it's weird
    # do a first pass, scanning languages
    possible_langs: Set[str] = set()
    for line in src_section.split("\n"):
        if not line.strip():
            continue

        if any([line.startswith(term) for term in lyrics_section_term]):
            is_in_lyrics_section = False
            current_timestamp = None
            continue

        if not line.strip("x"):
            continue

        if line.replace(" ", "").startswith("lyrics="):
            is_in_lyrics_section = not is_in_lyrics_section
            continue

        if not is_in_lyrics_section:
            continue

        if line.startswith("time="):
            current_timestamp = line.split("=")[1]
            if not current_timestamp:
                current_timestamp = f"<line-{current_timestamp_default}>"
                current_timestamp_default += 1
            lyrics[current_timestamp] = {}
            continue

        if line.startswith("sep="):
            sep_timestamp = line.split("=")[1]
            lyrics[sep_timestamp] = {}
            current_timestamp = None
            continue

        if current_timestamp is None:
            continue

        try:
            lang, _ = line.split("=", 1)
        except:
            pass

        possible_langs.add(lang)

    if "ja" in possible_langs:
        possible_langs.discard("en")

    for line in src_section.split("\n"):
        if not line.strip():
            continue

        if not line.strip("x"):
            continue

        if any([line.startswith(term) for term in lyrics_section_term]):
            is_in_lyrics_section = False
            current_timestamp = None
            continue

        if line.replace(" ", "").startswith("lyrics="):
            is_in_lyrics_section = not is_in_lyrics_section
            continue

        if not is_in_lyrics_section:
            continue

        if line.startswith("time="):
            current_timestamp = line.split("=")[1]
            if not current_timestamp:
                current_timestamp = f"<line-{current_timestamp_default}>"
                current_timestamp_default += 1
            lyrics[current_timestamp] = {}
            continue

        if line.startswith("sep="):
            sep_timestamp = line.split("=")[1]
            lyrics[sep_timestamp] = {}
            current_timestamp = None
            continue

        if current_timestamp is None:
            continue

        try:
            lang, text = line.split("=", 1)
            # Explicitly exclude lang: en, b/c sometimes it is in japanese lyrics
            if lang == "en" and "ja" in possible_langs:
                all_langs = lyrics.values()
                # we are making big assumptions here
                if "ja" not in lyrics[current_timestamp]:
                    lyrics[current_timestamp]["ja"] = text
                elif "zh" not in lyrics[current_timestamp]:
                    lyrics[current_timestamp]["zh"] = text
                else:
                    # terrible
                    lyrics[current_timestamp]["ja"] = (
                        lyrics[current_timestamp]["ja"] + text
                    )
                    print("wtf")
                    # breakpoint()
                continue

            lyrics[current_timestamp][lang] = text
        except ValueError:
            current_timestamp = None
            is_in_lyrics_section = False

    for timestamp, lines in lyrics.items():
        lines = [LyricsModel.ThwikiLyricsLineLang(lang, text) for lang, text in lines.items()]
        section.time_instants[timestamp] = LyricsModel.ThwikiLyricsTimeInstant(timestamp, lines)

    return section

def get_lyrics_metadata(data: Wikicode) -> Optional[Dict[str, str]]:
    lyrics_templates = list(
        filter(lambda x: x.name.strip() == "歌词信息", data.filter_templates())
    )[0]

    if lyrics_templates is None:
        return None

    metadata_mapping = {
        "语言": "src_lang",
        "译者": "translator",
    }

    metadata = {}
    for param in lyrics_templates.params:
        key = param.name.strip()
        value = param.value.strip()
        if key in metadata_mapping:
            metadata[metadata_mapping[key]] = value

    return metadata

def process_one(entry: LyricsInfo):
    page_title = entry.wiki_page_title_constructed if entry.wiki_page_title_actual is None else entry.wiki_page_title_actual

    src = get_wiki_page_source(get_page_source(page_title))
    if src is None:
        entry.process_status = LyricsProcessingStatus.NO_LYRICS_FOUND
        entry.save()
        return

    redirect = follow_redirect(src)

    if redirect is not None:
        entry.wiki_page_title_actual = redirect
        entry.save()
        return

    parsed = mw.parse(src)
    metadata = get_lyrics_metadata(parsed)
    if metadata is None:
        entry.process_status = LyricsProcessingStatus.NO_LYRICS_FOUND
        entry.save()
        return 

    lyrics = get_lyrics_actual_handle_table(src)
    entry.lyrics_src = json.dumps(lyrics.to_json(), ensure_ascii=False)
    entry.original_language = metadata.get("src_lang", None)
    entry.translator = metadata.get("translator", None)
    entry.process_status = LyricsProcessingStatus.PROCESSED
    entry.save()


def process():
    total = LyricsInfo.select().where(LyricsInfo.process_status == LyricsProcessingStatus.PENDING).count()
    current = 0
    pending: LyricsInfo
    for pending in LyricsInfo.select().where(
        LyricsInfo.process_status == LyricsProcessingStatus.PENDING
    ):
        # if pending.remote_track_id != "33a63b2b-94a6-4988-b7f1-54dba801e2f0":
        # continue
        current += 1
        print(f"Processing {current}/{total}")
        try:
            process_one(pending)
        except Exception as e:
            print(f"Failed to process {pending.track_id}. Error: {e}")
            pending.process_status = LyricsProcessingStatus.FAILED
            pending.save()

def main():
    if LyricsInfo.select().count() == 0:
        import_data()

    process()

if __name__ == '__main__':
    main()
