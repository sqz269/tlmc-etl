import json
import re
import time
from typing import Dict, Optional
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
import ExternalInfo.ThwikiInfoProvider.cache.path_definitions as CachePathDef

import ExternalInfo.ThwikiInfoProvider.output.path_definitions as ThwikiOutput
import mwparserfromhell as mw
from mwparserfromhell.nodes.template import Template
from mwparserfromhell.wikicode import Wikicode
from ExternalInfo.CacheInfoProvider.Cache import cached

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
        

@cached("lyric_page_src", lyrics_wiki_page_cache_path, disable_parse=True)
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
    j = json.loads(quersrc)
    page = list(j["query"]["pages"].values())[0]
    if "missing" in page:
        return None
    
    try:
        page["revisions"][0]["*"]
    except KeyError:
        return None
    
    return page["revisions"][0]["*"]

def get_lyrical_line(text_line=str) -> Optional[str]:
    # Need to detect temaplates embedded in the text
    # Example ぼくらが、{{ruby-ja|歩いていく|歩く}}この道が、
    # We need to separate token into it's own string compartment
    # then call mwpaserfromhell to parse the template and insert 
    # it's content back into it's original position
    
    string_compartments = []

    start_offset = 0
    while True:
        start = text_line.find("{{", start_offset)
        if start == -1:
            string_compartments.append(text_line[start_offset:])
            break

        end = text_line.find("}}", start)
        if end == -1:
            raise Exception("Parse failed, unclosed template brackets in", text_line)
        
        string_compartments.append(text_line[start_offset:start])
        string_compartments.append(text_line[start:end+2])
        start_offset = end + 2

    result_string = ""
    for compartment in string_compartments:
        if compartment.startswith("{{"):
            template = mw.parse(compartment).filter_templates()[0]
            if template.name.strip() not in ["ruby-ja", "ruby-cn"]:
                print("Unknown template", template.name)
                input()

            result_string += template.get(1).value.strip()
        else:
            result_string += compartment

    return result_string

def get_lyrics_actual(raw_page_src: str) -> Dict[str, Dict[str, str]]:
    lyrics = {}
    is_in_lyrics_section = False
    current_timestamp = None
    lyrics_section_term = [
        "--",
        "==",
        "__",
    ]
    check_lyrics_line = r'^[A-Za-z]{2}=$'
    for line in raw_page_src.split("\n"):
        if not line.strip():
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
            lyrics[current_timestamp][lang] = text
        except ValueError:
            current_timestamp = None
            is_in_lyrics_section = False

    return lyrics

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
    
    lyrics = get_lyrics_actual(src)
    entry.lyrics = json.dumps(lyrics, ensure_ascii=False)
    entry.original_language = metadata.get("src_lang", None)
    entry.translator = metadata.get("translator", None)
    entry.process_status = LyricsProcessingStatus.PROCESSED
    entry.save()


def process():
    total = LyricsInfo.select().where(LyricsInfo.process_status == LyricsProcessingStatus.PENDING).count()
    current = 0
    for pending in LyricsInfo.select().where(LyricsInfo.process_status == LyricsProcessingStatus.PENDING):
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
