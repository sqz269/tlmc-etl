# Data to add
# Albums
#   album_artist
#   data_source
# Tracks
#   arrangements
#   lyrics_author
#   vocal
#   original
from contextlib import nullcontext
import json
from pprint import pprint
from re import M
from string import punctuation
import time
from typing import Dict, List
import unicodedata
from urllib import request
from InfoProviders.ThcInfoProvider.ThcSongInfoProvider.Model.ThcSongInfoModel import Album, Track, ProcessStatus
from InfoProviders.ThcInfoProvider.ThcOriginalTrackMapper.Model.OriginalTrackMapModel import OriginalTrack
from InfoProviders.ThcInfoProvider.ThcOriginalTrackMapper.SongQuery import SongQuery, get_original_song_query_params
from InfoProviders.ThcInfoProvider.ExternalData.commit_org_alb_trk import load_original_album_map

import requests

HOST = "http://localhost:5217"

FETCH_ALBUM_BY_ID = HOST + "/api/music/album/{id}"

FETCH_TRACK_BY_ID = HOST + "/api/music/track/{id}"

PATCH_ALBUM = HOST + "/api/internal/album/{albumId}"
PATCH_TRACK = HOST + "/api/internal/track/{trackId}"

def fetch_album(alb_id):
    r = requests.get(FETCH_ALBUM_BY_ID.format(id=alb_id))
    return r.json()

def filter():
    f = open(".dt.json", "w")

    mp = []
    album: Album;
    count = Album.select().where(Album.process_status == ProcessStatus.PROCESSED).count()
    i = 0
    for album in Album.select().where(Album.process_status == ProcessStatus.PROCESSED):
        print(f"[{i}/{count}] {album.album_id}")
        i += 1
        tracks: List[Track]
        tracks = Track.select().where(Track.album == album)
        remote_album = fetch_album(album.album_id)

        if not remote_album:
            print("Remote album not found: {}".format(album.album_id))
            album.process_status = ProcessStatus.DB_REMOTE_NOT_FOUND
            album.save()
            continue

        remote_album_track_name = [ track["name"]['default'] for track in remote_album['tracks'] ]
        local_track_name = [ json.loads(track.title_jp)[0] if track.title_jp else "" for track in tracks ]

        if (len(remote_album_track_name) != len(local_track_name)):
            print("Album {album_id} has {remote_album_track_name} tracks, but local have {local_track_name} tracks".format(album_id=album.album_id, remote_album_track_name=len(remote_album_track_name), local_track_name=len(local_track_name)))
            album.process_status = ProcessStatus.DB_ABORTED_TRACK_MISMATCH
            album.save()
            continue

        mp.append({
            "album_id": album.album_id,
            "mismatch": set(remote_album_track_name) == set(local_track_name)
        })

    json.dump(mp, f)
    f.close()

def normalize(str):
    punctuation = '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~'
    str = unicodedata.normalize("NFKC", str)
    str = str.replace(" ", "")
    str = str.strip()
    # remove punctuation
    for p in punctuation:
        str = str.replace(p, "")
    str = str.lower()
    return str

def comp():
    mm = []
    count = Album.select().where(Album.process_status == ProcessStatus.PROCESSED).count()
    album: Album
    i = 0
    m = 0
    for album in Album.select().where(Album.process_status == ProcessStatus.PROCESSED):
        print(f"[{i}/{count}] {album.album_id} [{m}]")
        i += 1
        tracks: List[Track]
        tracks = Track.select().where(Track.album == album)
        remote_album = fetch_album(album.album_id)

        remote_album_track_name = [ normalize(track["name"]['default']) for track in remote_album['tracks'] ]
        local_track_name = [ normalize(json.loads(track.title_jp)[0]) if track.title_jp else "" for track in tracks ]

        if (set(remote_album_track_name) != set(local_track_name)):
            album.process_status = ProcessStatus.DB_ABORTED_TRACK_NAME_MISMATCH
            album.save()
            mm.append({
                "album_id": album.album_id,
                "local": local_track_name,
                "remote": remote_album_track_name
            })
            m += 1
        else:
            album.process_status = ProcessStatus.DB_ALL_VALID
            album.save()

    with open(".mm.json", "w", encoding="utf-8") as f:
        json.dump(mm, f, ensure_ascii=False, indent=4)

def parse_original_tracks(track_original: str, album_id_map: dict):
    if (not track_original or not track_original.strip()):
        return []

    org_ignore = {"Cradle音乐名", "东方音焰火音乐名", "东方魔宝城音乐名", "かごめかごめ", "地灵殿PH音乐名", "东方夏夜祭音乐名", "地灵殿PH音乐名", "东方夏夜祭音乐名", "Cradle音乐名", "东方音焰火音乐名", "东方魔宝城音乐名", "8MPF音乐名"}

    parsed = json.loads(track_original)
    ps = []
    for k in parsed:
        ps.extend([l.strip() for l in k.split(",") if l and l not in org_ignore])

    qp = get_original_song_query_params(ps)

    # End results, array of Id like AoCF-1, HSiFS-13
    ret = []
    for q in qp:
        if (q[0] in org_ignore):
            continue
        result = SongQuery.query(q[0], q[1])
        # print(album_id_map.keys())
        alb_id = album_id_map[result.source.id]["id"]
        track_id = f"{alb_id}-{result.index}"
        ret.append(track_id)

    return ret

def mk_track_patch(track_data: Track, album_id_map: dict):
    data = {
        "genre": [],
        "arrangement": [],
        "vocalist": [],
        "lyricist": [],
        "original": [],
        "originalNonTouhou": False
    }

    arragement = json.loads(track_data.arrangement or "[]")
    vocal = json.loads(track_data.vocal or "[]")
    lyrics = json.loads(track_data.lyrics_author or "[]")
    
    originals = parse_original_tracks(track_data.original, album_id_map)

    data["arrangement"] = arragement
    data["vocalist"] = vocal
    data["lyricist"] = lyrics
    data["original"] = originals
    data["originalNonTouhou"] = bool(track_data.src_album_not_th) or bool(track_data.src_track_not_th)

    return data

def repatch_track(track_data: Track, remote_track, album_id_map):
    originals = parse_original_tracks(track_data.original, album_id_map)

def mk_album_patch(album_data: Album):
    data_src_add = [
        {
            "value": album_data.data_source,
            "path": "/DataSource/-",
            "op": "add",
        }
    ]

    if (album_data.website):
        websites = [i for i in album_data.website.split("，") if i]

        for website in websites:
            data_src_add.append({
                "value": website,
                "path": "/Website/-",
                "op": "add",
            })
    
    return data_src_add

def gt_track(trk_list, name):
    for trk in trk_list:
        # print(f"Matching [{normalize(trk['name']['default'])}] with [{normalize(name)}]")
        if normalize(trk["name"]['default']) == normalize(name):
            return trk
    return None

def fetch_track(trackId):
    r = requests.get(FETCH_TRACK_BY_ID.format(id=trackId))
    return r.json()

patch_alb_count = 0
patch_trk_count = 0
def patch(alb_patch, trk_patch) -> bool:
    global patch_alb_count
    global patch_trk_count
    # Push Album
    alb_id, alb_data = list(alb_patch.items())[0]
    alb_url = PATCH_ALBUM.format(albumId=alb_id)

    patch_alb_count += 1
    print(f"[{patch_alb_count}] Patching album {alb_id}")
    r = requests.patch(alb_url, json=alb_data)
    if (r.status_code != 200):
        print("\nFailed to patch album", alb_id, r.status_code, "\n")
        print(alb_patch)
        return False

    for trk_id, trk_data in trk_patch.items():
        print(f"[{patch_trk_count}] [{alb_id}] Patching track {trk_id}")
        patch_trk_count += 1
        trk_url = PATCH_TRACK.format(trackId=trk_id)
        r = requests.patch(trk_url, json=trk_data)
        print(trk_url)
        if (r.status_code != 200):
            print("\nFailed to patch track", trk_id, r.status_code, r.content, "\n")
            return False

    return True

def push():
    album_id_map = load_original_album_map()

    count = Album.select().where(Album.process_status == ProcessStatus.DB_ALL_VALID).count()
    album: Album
    i = 0
    m = 0
    for album in Album.select().where(Album.process_status == ProcessStatus.DB_ALL_VALID):
    # for album in Album.select().where(Album.album_id == '0081486b-68cb-4121-9e4d-8821dbbbb213'):
        i += 1
        tracks: List[Track]
        tracks = Track.select().where(Track.album == album)
        remote_album = fetch_album(album.album_id)

        remote_album_track_name = [ normalize(track["name"]['default']) for track in remote_album['tracks'] ]
        local_track_name = [ normalize(json.loads(track.title_jp)[0]) if track.title_jp else "" for track in tracks ]

        if (set(remote_album_track_name) != set(local_track_name)):
            album.process_status = ProcessStatus.DB_ABORTED_TRACK_NAME_MISMATCH
            album.save()
            continue

        local_track_map = { normalize(json.loads(track.title_jp)[0]): track for track in tracks }


        album_update = mk_album_patch(album)
        album_update = {album.album_id: album_update}
        track_updates = {}
        # normalized_track_names = [ normalize(track["name"]['default']) for track in remote_album['tracks'] ]
        for track_name, track_data in local_track_map.items():
            remote_track = gt_track(remote_album["tracks"], track_name)
            track_update = mk_track_patch(track_data, album_id_map)
            # pprint(normalized_track_names)
            # print(normalize(track_name))
            track_updates.update({remote_track["id"]: track_update})

        # pprint(track_updates)
        # print(album_update)
        # input()

        success = patch(album_update, track_updates)
        # time.sleep(1)
        if (success):
            album.process_status = ProcessStatus.DB_PATCH_OK
            album.save()
            m += 1
        else:
            album.process_status = ProcessStatus.DB_PATCH_FAILED
            album.save()
        # pprint(track_updates)
        # pprint(album_update)
        # input()

def check_push():
    album_id_map = load_original_album_map()
    album: Album
    i = 0
    m = 0
    for album in Album.select().where(Album.process_status == ProcessStatus.DB_PATCH_OK):
        i += 1
        tracks: List[Track]
        tracks = Track.select().where(Track.album == album)
        remote_album = fetch_album(album.album_id)

        remote_album_track_name = [ normalize(track["name"]['default']) for track in remote_album['tracks'] ]
        local_track_name = [ normalize(json.loads(track.title_jp)[0]) if track.title_jp else "" for track in tracks ]

        if (set(remote_album_track_name) != set(local_track_name)):
            album.process_status = ProcessStatus.DB_ABORTED_TRACK_NAME_MISMATCH
            album.save()
            continue

        local_track_map = { normalize(json.loads(track.title_jp)[0]): track for track in tracks }

        for track_name, track_data in local_track_map.items():
            remote_track = gt_track(remote_album["tracks"], track_name)
            # print(remote_track)
            # input()

if (__name__ == '__main__'):
    # filter()
    # comp()
    push()
    check_push()
