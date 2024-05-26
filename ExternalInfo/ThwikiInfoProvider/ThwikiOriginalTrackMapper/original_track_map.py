import re
import uuid
from pprint import pprint
from typing import List, Tuple

import requests
from bs4 import BeautifulSoup

from ExternalInfo.ThwikiInfoProvider.ThwikiOriginalTrackMapper.Model.OriginalTrackMapModel import (
    OriginalTrack,
    TrackSource,
)


class Lang:
    JP = "日文"
    EN = "英文"
    ZH = "中文"


original_track_aliases = {
    "花映冢音乐名": "花映塚音乐名",
    "緋想天音乐名": "绯想天音乐名",
    "萃夢想音乐名": "萃梦想音乐名",
    "憑依華音乐名": "凭依华音乐名",
    "イザナギオブジェクト音乐名": "伊奘诺物质音乐名",
}

param_extr = re.compile("\{\{(.+)\|\d+\|(.+)\}\}")


def bracket_split(str: str, fail_on_char=True, brackets={"(": ")", "{": "}", "[": "]"}):
    if str.startswith("<!--") and str.endswith("-->"):
        return []
    stack = []
    splitted = []
    current = ""
    for c in str.strip():
        if brackets.get(c, None):
            if current and len(stack) == 0:
                splitted.append(current)
                current = ""
            stack.append(c)
            current += c
            continue
        if len(stack) > 0 and c == brackets[stack[-1]]:
            stack.pop()
            current += c
            continue

        if fail_on_char and len(stack) == 0 and c.strip():
            raise Exception("Invalid string: " + str)

        current += c.strip()

    if current:
        splitted.append(current)
    return splitted


def get_original_song_query_params(songs: List[str]) -> List[Tuple[str, str]]:
    querable = []
    for s in songs:
        if "原曲段落" in s:
            continue

        s = bracket_split(s.strip().replace("\n", ""))
        for k in s:
            param = param_extr.match(k)
            if not param:
                continue
            groups = list(param.groups())

            groups[0] = original_track_aliases.get(groups[0], groups[0])
            querable.append((groups[0], groups[1].strip("|")))

    return querable


class OriginalTrackMap:
    TABLE_URL = "https://thwiki.cc/特殊:管理映射方案?view={query}/{lang}"

    HEADER = {
        "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="102", "Google Chrome";v="102"',
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://thwiki.cc/",
        "X-Requested-With": "XMLHttpRequest",
        "sec-ch-ua-mobile": "?0",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36",
        "sec-ch-ua-platform": '"Windows"',
    }

    @staticmethod
    def parse_table(table_data):
        lines = list(filter(lambda ln: ln.strip(), table_data.split("\n")))

        songs = {}
        sp_ind = {}
        sp_ind_e = {}
        sp_ind_a = {}
        for line in lines:
            if line.startswith("!"):
                continue

            id: str
            id, name = line.split(" ", 1)

            if "|" in id:
                if id.count("|") == 1:
                    index, spi = id.split("|", 1)
                    songs[index] = name
                    sp_ind[index] = spi
                elif id.count("|") == 2:
                    index, spi = id.split("|", 1)
                    sp1, sp2 = spi.split("|")
                    songs[index] = name
                    sp_ind[index] = sp1
                    sp_ind_e[index] = sp2
                elif id.count("|") == 3:
                    index, spi = id.split("|", 1)
                    sp1, sp2, sp3 = spi.split("|")
                    songs[index] = name
                    sp_ind[index] = sp1
                    sp_ind_e[index] = sp2
                    sp_ind_a[index] = sp3
                else:
                    print("UNEXPECTED COUNT")
            else:
                songs[id.strip()] = name

        return (songs, sp_ind, sp_ind_e, sp_ind_a)

    @staticmethod
    def cache_data(query):
        source = TrackSource.create(id=query, query_kw=query)

        songs_all_lang = {}
        key_index = {}
        for lang in [Lang.JP, Lang.EN, Lang.ZH]:
            url = OriginalTrackMap.TABLE_URL.format(query=query, lang=lang)
            r = requests.get(url, headers=OriginalTrackMap.HEADER)
            bs = BeautifulSoup(r.text, "lxml")
            rst = bs.find("textarea", {"id": "array-0"})
            (song_info, sp_ind, sp_ind_e, sp_ind_a) = OriginalTrackMap.parse_table(
                rst.text
            )
            songs_all_lang[lang] = song_info
            if not key_index:
                key_index = set(song_info.keys())
            else:
                if key_index != set(song_info.keys()):
                    print(f"{query} {lang} KEY MISMATCH")
                    with open(f"song_map_mismatch.log", "a", encoding="utf-8") as f:
                        f.write(f"{query} {lang}\n")

        # Collapse the embedded dict into an single flat dict
        d = []
        for k in key_index:
            init_data = {
                "id": str(uuid.uuid4()),
                "source": source,
                "index": k,
            }
            for lang, key in {
                Lang.JP: "title_jp",
                Lang.EN: "title_en",
                Lang.ZH: "title_zh",
            }.items():
                init_data[key] = songs_all_lang[lang].get(k, "<MISMATCH>")
            init_data["sp_index"] = sp_ind.get(init_data["index"], "")
            init_data["sp_idx_e"] = sp_ind_e.get(init_data["index"], "")
            init_data["sp_idx_a"] = sp_ind_a.get(init_data["index"], "")
            d.append(init_data)

        for song_data in d:
            r = OriginalTrack.create(**song_data)
            r.save()

    @staticmethod
    def query(source, index, autofail: set = {}, default=None):
        # the index could be padded with leading zeros, we need to trim out the LEADING zeros to match the database
        index: str = index
        index = index.lstrip("0")

        src_query = OriginalTrack.select().where(OriginalTrack.source == source)
        query = OriginalTrack.select().where(
            (OriginalTrack.source == source)
            & (
                (OriginalTrack.index == index)
                | (OriginalTrack.sp_index == index)
                | (OriginalTrack.sp_idx_e == index)
            )
        )

        if source in autofail:
            if not default:
                raise Exception(f"No song found for source: {source} index: {index}")
            return OriginalTrack.mk_fail(source, default)
        if not src_query.exists():
            # print(source)
            print(f"No song found for source: {source}. Caching")
            OriginalTrackMap.cache_data(source)
        if not query.exists():
            print(f"No song found for source: {source} index: {index}. Aborting")
            if not default:
                raise Exception(f"No song found for source: {source} index: {index}")
            return OriginalTrack.mk_fail(source, default)
        return query.get()


if __name__ == "__main__":
    pprint(OriginalTrackMap.query("地灵殿音乐名", "E"))
    pprint(OriginalTrackMap.query("绯想天音乐名", "S"))
