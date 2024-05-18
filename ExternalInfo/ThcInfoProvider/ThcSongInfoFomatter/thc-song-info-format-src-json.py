import os
from typing import Dict, Union
import unicodedata
from Processor.ExternalInfoCollector.ThcInfoProvider.ThcOriginalTrackMapper.SongQuery import (
    SongQuery,
    get_original_song_query_params,
)
from Processor.ExternalInfoCollector.ThcInfoProvider.ThcSongInfoProvider.Model.ThcSongInfoModel import (
    Track,
    Album,
    ProcessStatus,
)
from Processor.ExternalInfoCollector.ThcInfoProvider.ThcSongInfoFomatter.Model.InfoFormattedModel import (
    AlbumFormatted,
    TrackFormatted,
    ProcessStatusFormatted,
)
from Processor.ExternalInfoCollector.ThcInfoProvider.ThcSongInfoFomatter.thc_song_info_format import (
    load_original_song_map,
    resolve_original_tracks,
    load_original_song_map,
)
import json

ID_ASSIGNMENT_JSON = R"D:\PROG\TlmcTagger\InfoProviderMk4\DbPush\id-assignment.json"


def normalize_text(text):
    # Normalize text
    # 1. Convert to NFKC
    # 2. Remove all spaces
    # 3. Keep chars whose category is L
    # 4. Convert to lowercase
    return "".join(
        [
            c
            for c in unicodedata.normalize("NFKC", text)
            if c.isspace() or unicodedata.category(c).startswith("L")
        ]
    ).lower()


def get_album_id(entry):
    if len(entry["Discs"]) == 1:
        return entry["Discs"][list(entry["Discs"].keys())[0]]["DiscId"]
    else:
        return entry["AlbumInfo"]["AlbumId"]


def collect_tracks(entry):
    all_tracks = []
    for _, disc in entry["Discs"].items():
        for track in disc["Tracks"]:
            all_tracks.append(track)

    return all_tracks


def match_src_thw_tracks(src_tracks, thc_tracks) -> Union[Dict[str, dict], None]:
    title_map = {
        normalize_text(json.loads(track.title_jp)[0]): track for track in thc_tracks
    }
    if len(title_map) != len(thc_tracks):
        # do we really care about track with same title?
        pass

    mapped_entry = {}
    for tracks in src_tracks:
        title = normalize_text(tracks["title"].replace(".flac", ""))  # #
        track_id = tracks["TrackId"]
        if title in title_map:
            thc_track = title_map[title]
            mapped_entry[track_id] = thc_track
        else:
            return None

    return mapped_entry


def generate_track_formatted(mapped_tracks, abbriv_map: Dict[str, str]):
    track: Track

    fmt = {}
    for remote_id, track in mapped_tracks.items():

        track_fmt_map = {}

        # original
        if not track.original:
            track_fmt_map["original"] = None
        else:
            track_fmt_map["original"] = json.loads(
                resolve_original_tracks(track, abbriv_map)
            )

        track_fmt_map["vocal"] = json.loads(track.vocal) if track.vocal else None
        track_fmt_map["arrangement"] = (
            json.loads(track.arrangement) if track.arrangement else None
        )
        track_fmt_map["lyricist"] = (
            json.loads(track.lyrics_author) if track.lyrics_author else None
        )

        fmt[remote_id] = track_fmt_map

    return fmt


def generate_album_formatted(album: Album, remote_id: str):
    fmt = {}
    fmt["catalog"] = album.catalogno
    fmt["website"] = album.website
    fmt["data_source"] = album.data_source

    return fmt


def main():
    with open(ID_ASSIGNMENT_JSON, "r", encoding="utf-8") as f:
        id_assignment = json.load(f)

    abbriv_map = load_original_song_map()

    coll_trk_fmt = {}
    coll_alb_fmt = {}
    for entry in id_assignment:
        album_id = get_album_id(entry)

        thc_album = Album.get_or_none(Album.album_id == album_id)
        if thc_album is None:
            print("Album {} not found".format(album_id), end="\r")
            continue

        src_tracks = collect_tracks(entry)
        thc_tracks = list(Track.select().where(Track.album == thc_album))

        if len(src_tracks) > len(thc_tracks):
            # if (len(src_tracks) != len(thc_tracks)):
            print(
                "Album {} track count mismatch: {} != {}".format(
                    album_id, len(src_tracks), len(thc_tracks)
                ),
                end="\r",
            )
            continue

        mapped_tracks = match_src_thw_tracks(src_tracks, thc_tracks)
        if mapped_tracks is None:
            print("Album {} no match".format(album_id), end="\r")
            continue
        else:
            print("Album {} matched".format(album_id), end="\r")
            trk_fmt = generate_track_formatted(mapped_tracks, abbriv_map)
            alb_fmt = generate_album_formatted(thc_album, album_id)
            coll_trk_fmt.update(trk_fmt)
            coll_alb_fmt[album_id] = alb_fmt

    with open("thc-song-info-format-src.json", "w", encoding="utf-8") as f:
        json.dump(coll_trk_fmt, f, indent=4, ensure_ascii=False)

    print()
    print(len(coll_trk_fmt))

    with open("thc-album-info-format-src.json", "w", encoding="utf-8") as f:
        json.dump(coll_alb_fmt, f, indent=4, ensure_ascii=False)


if __name__ == "__main__":
    main()
