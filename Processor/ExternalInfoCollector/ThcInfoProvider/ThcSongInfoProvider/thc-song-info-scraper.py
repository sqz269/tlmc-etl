import json
from multiprocessing.dummy import Process
from pprint import pprint
from re import template
import re
from typing import Any, Dict, List
from urllib.parse import urlparse
import uuid

import httpx
import mwparserfromhell as mw
from bs4 import BeautifulSoup
from mwparserfromhell.nodes.template import Template
from mwparserfromhell.wikicode import Wikicode

from Processor.ExternalInfoCollector.ThcInfoProvider.ThcSongInfoProvider.Model.ThcSongInfoModel import (
    Track,
    Album,
    SaleSource,
    ProcessStatus,
    ThccDb,
)
from Processor.ExternalInfoCollector.ThcInfoProvider.ThcQueryProvider.Model.QueryModel import (
    QueryStatus,
    QueryData,
)
from Processor.ExternalInfoCollector.CacheInfoProvider.Cache import cached


class ThWikiCc:
    PAGE_SRC_URL = "https://thwiki.cc/index.php?title={path}&action=edit&viewsource=1"
    # Full Width Comma
    FW_COMMA = "，"
    HEADER = {
        "sec-ch-ua": '" Not A;Brand"lyrics_author;v="99", "Chromium";v="102", "Google Chrome";v="102"',
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://thwiki.cc/",
        "X-Requested-With": "XMLHttpRequest",
        "sec-ch-ua-mobile": "?0",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36",
        "sec-ch-ua-platform": '"Windows"',
    }

    ALBUM_INFO_PRELIM_ARGS = {
        "封面": "cover_image",
        "封面角色": "cover_char",
        "名称": "title",
        "译名": "title_zh",
        "制作方": "album_artist",
        "首发日期": "release_date",
        "展会": "convention",
        "编号": "catalogno",
        "音轨数": "track_count",
        "类型": None,
        "风格类型": "genre",
        "会场售价": None,
        "通贩售价": None,
        "通贩售价补充": None,
        "官网页面": "website",
        "备注": None,
    }

    ALBUM_INFO_ARGS_ARRAY = ["cover_char", "album_artist", "genre"]

    ALBUM_INFO_ARGS_NO_RESOLVE = ["展会"]

    SELLER_INFO_ARGS = {"类型": "type", "编号": "path", "标题": None}

    TRACK_KNOWN_ARGS = {
        "名称": "title_jp",
        "时长": "duration",
        "编曲": "arrangement",
        "再编曲": "arrangement",
        "作曲": "composer",
        "伴唱": "vocal",
        "演唱": "vocal",
        "演奏": "instrument",
        "原专辑": "original_release_album",
        "原名称": "original_release_title",
        "社团": "circle",
        "歌词": "lyrics",
        "作词": "lyrics_author",
        "原曲": "original",
        "非东方原曲": "src_track_not_th",
        "非东方来源": "src_album_not_th",
    }

    TRACK_KNOWN_ARGS_NO_RESOLVE = ["original"]

    TRACK_NO_TRANSFORM = ["index"]

    TRACK_KNOWN_ARGS_IGNORE = ["乐器", "演奏阵列"]

    TRACK_VALUE_SINGLE_ITEM = ["duration", "title"]

    DISC_SCAN = re.compile("={3}\s?Disc\s?(\d+)\s?={3}", re.IGNORECASE)

    @staticmethod
    def get_title_from_url(url):
        parsed = urlparse(url)
        return parsed.path.split("/")[-1]

    @staticmethod
    @cached(
        cache_id="thc",
        cache_dir="./InfoProviders/ThcInfoProvider/ThcSongInfoProvider/Cached",
    )
    def get_source(url):
        url = ThWikiCc.PAGE_SRC_URL.format(path=ThWikiCc.get_title_from_url(url))
        response = httpx.get(url, headers=ThWikiCc.HEADER)
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

        bs = BeautifulSoup(response.text, "lxml")
        src = bs.find("textarea", {"id": "wpTextbox1"})
        return mw.parse(src.text)

    @staticmethod
    def _fmt_album_metadata(data: Dict[str, str]):
        album_metadata = {}
        for key, value in data.items():
            if key in ThWikiCc.ALBUM_INFO_PRELIM_ARGS:
                album_metadata[ThWikiCc.ALBUM_INFO_PRELIM_ARGS[key]] = value
            elif key in ThWikiCc.ALBUM_INFO_ARGS_NO_RESOLVE:
                album_metadata[key] = value
            else:
                if key in ThWikiCc.ALBUM_INFO_ARGS_ARRAY:
                    album_metadata[key] = list(
                        filter(lambda x: x, value.split(ThWikiCc.FW_COMMA))
                    )
                else:
                    album_metadata[key] = value

        if album_metadata["title"].isascii():
            if not (album_metadata["title_zh"]):
                album_metadata["title_zh"] = album_metadata["title"]
            album_metadata["title_jp"] = album_metadata["title"]
            album_metadata["title_en"] = album_metadata["title"]
            del album_metadata["title"]
        else:
            album_metadata["title_zh"] = ""
            album_metadata["title_jp"] = album_metadata["title"]
            album_metadata["title_en"] = ""
            del album_metadata["title"]

        return album_metadata

    @staticmethod
    def parse_album_info(data: Wikicode):
        template: Template = list(
            filter(lambda x: x.name == "同人专辑信息", data.filter_templates())
        )[0]
        if template is None:
            raise Exception("No album info template found")

        album_info = {}
        for param in template.params:
            if (name := str(param.name).strip()) in ThWikiCc.ALBUM_INFO_PRELIM_ARGS:
                if ThWikiCc.ALBUM_INFO_PRELIM_ARGS[name] is not None:
                    album_info[ThWikiCc.ALBUM_INFO_PRELIM_ARGS[name]] = str(
                        param.value
                    ).strip()
            else:
                # Digits are positional args and useless for us, so we skip them
                if not name.isdigit():
                    print(f"Unknown album info param: {name}")

            for value in ThWikiCc.ALBUM_INFO_PRELIM_ARGS.values():
                if value not in album_info and value is not None:
                    album_info[value] = ""

        return ThWikiCc._fmt_album_metadata(album_info)

    @staticmethod
    def _fmt_track_info(data: List[Dict[str, str]]):
        new_data = []

        transformer = lambda x: x.strip(f" {ThWikiCc.FW_COMMA},")
        for track in data:
            fmt_track_info = {}
            for k, v in track.items():
                if k in ThWikiCc.TRACK_NO_TRANSFORM:
                    fmt_track_info[k] = v
                    continue
                if k in ThWikiCc.TRACK_VALUE_SINGLE_ITEM:
                    fmt_track_info[k] = map(transformer, v)[0]
                    continue

                fmt_track_info[k] = map(
                    transformer, [r for i in v for r in i.split(ThWikiCc.FW_COMMA) if r]
                )
            new_data.append(fmt_track_info)

        return new_data

    @staticmethod
    def get_track_info(data: Wikicode):
        source = str(data).split("\n")

        track_list = {}
        curr_disc = 1
        curr_disc_source = []
        for line in source:
            if match := ThWikiCc.DISC_SCAN.match(line):
                track_list[curr_disc] = "\n".join(curr_disc_source)
                curr_disc = int(match.group(1))
                continue

            curr_disc_source.append(line)

        track_list[curr_disc] = "\n".join(curr_disc_source)

        return track_list

    @staticmethod
    def _parse_track_info(data: str):
        data = mw.parse(data)
        track_templates = list(
            filter(lambda x: x.name.strip() == "同人曲目信息", data.filter_templates())
        )

        print(f"Found {len(track_templates)} track templates")

        tracks = []
        for idx, template in enumerate(track_templates, 1):
            track = {"index": idx}
            for param in template.params:
                if (name := str(param.name).strip()) in ThWikiCc.TRACK_KNOWN_ARGS:
                    if (
                        trans_name := ThWikiCc.TRACK_KNOWN_ARGS[name]
                    ) is not None and track.get(trans_name) is not None:
                        track[trans_name].append(str(param.value).strip())
                    else:
                        track[trans_name] = [str(param.value).strip()]
                else:
                    if not name.isdigit() and not (
                        name in ThWikiCc.TRACK_KNOWN_ARGS_IGNORE
                    ):
                        print(
                            f"Unknown track info param: {name} in track info: {track}"
                        )

            if "title_jp" not in track:
                continue

            tracks.append(track)

        return ThWikiCc._fmt_track_info(tracks)

    @staticmethod
    def parse_seller(data: Wikicode):
        seller = list(
            filter(lambda x: x.name.strip() == "通贩网址", data.filter_templates())
        )

        sellers = []
        for template in seller:
            seller_info = {}
            for param in template.params:
                if (name := (str(param.name).strip())) in ThWikiCc.SELLER_INFO_ARGS:
                    key = ThWikiCc.SELLER_INFO_ARGS[name]
                    if key is not None:
                        seller_info[key] = str(param.value).strip()
                else:
                    if not name.isdigit():
                        print(
                            f"Unknown seller info param: {name} in seller info: {seller_info}"
                        )

            sellers.append(seller_info)

        return sellers

    @staticmethod
    def process(url):
        src = ThWikiCc.get_source(url)
        album_info = ThWikiCc.parse_album_info(src)
        # pprint(album_info)
        track_list = ThWikiCc.get_track_info(src)
        parsed_tracklist = {}
        for disc, track_info in track_list.items():
            parsed_tracklist[disc] = ThWikiCc._parse_track_info(track_info)

        # pprint(parsed_tracklist)
        seller_info = ThWikiCc.parse_seller(src)

        return (album_info, parsed_tracklist, seller_info)

    @staticmethod
    def serialize(data: Dict[str, Any], remove_empty_fields: bool = True):
        serialized = {}
        for key, value in data.items():
            if remove_empty_fields and not value:
                continue

            if isinstance(value, list):
                serialized[key] = json.dumps(value, ensure_ascii=False)
            else:
                serialized[key] = value
        return serialized


def import_data():
    total_exact = QueryData.select().where(QueryData.query_exact_result != None).count()
    print("Importing a total of {} exact results".format(total_exact))
    imported_album = []
    for query in QueryData.select().where(QueryData.query_exact_result != None):
        print(f"Importing {query.album_id}", end="\r")
        url, desc = json.loads(query.query_exact_result)
        album = Album(
            album_id=query.album_id,
            data_source=url,
            process_status=ProcessStatus.PENDING,
        )
        imported_album.append(album)

    BATCH_SIZE = 1000
    for i in range(0, total_exact, BATCH_SIZE):
        print(f"\nWriting Album {i}-{i+BATCH_SIZE}", end="\r")
        Album.bulk_create(imported_album[i : i + BATCH_SIZE])

    print("\nImport complete")


def process_album(album: Album):
    if album.album_id == "68edbb0e-27ef-4d6d-a939-e03eb8369ab9":
        pass
    try:
        album_info, track_info, seller_info = ThWikiCc.process(album.data_source)
    except:
        print(f"Error processing {album.album_id}")
        album.process_status = ProcessStatus.FAILED
        album.save()
        return

    album_info = ThWikiCc.serialize(album_info)
    album_info["number_of_disc"] = max(track_info.keys())

    created_tracks = []
    for disc_no, track in track_info.items():
        for ti in track:
            ti = ThWikiCc.serialize(ti)
            ti["track_id"] = str(uuid.uuid4())
            ti["album"] = album
            ti["disc_no"] = disc_no
            created_tracks += [Track(**ti)]

    created_sellers = []
    if seller_info:
        for seller in seller_info:
            seller = ThWikiCc.serialize(seller)
            seller["sell_id"] = str(uuid.uuid4())
            seller["album"] = album
            s = SaleSource(**seller)
            created_sellers += [s]

    print("Writing Album {}".format(album.album_id))
    with ThccDb.transaction() as txn:
        album.process_status = ProcessStatus.PROCESSED

        for k, v in album_info.items():
            setattr(album, k, v)

        album.save()
        Track.bulk_create(created_tracks)
        SaleSource.bulk_create(created_sellers)


def process():
    total = Album.select().where(Album.process_status == ProcessStatus.PENDING).count()
    current = 0
    for album in Album.select().where(Album.process_status == ProcessStatus.PENDING):
        current += 1
        print(f"[{current}/{total}] Processing {album.album_id}")
        process_album(album)


if __name__ == "__main__":
    if Album.select().count() == 0:
        import_data()

    process()
