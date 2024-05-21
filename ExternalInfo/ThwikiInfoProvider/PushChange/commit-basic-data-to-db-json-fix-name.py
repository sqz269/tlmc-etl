import json

import requests
from ExternalInfo.ThwikiInfoProvider.ThwikiBasicDataCommit.commit_basic_data_to_db_json import (
    get_album,
    patch_album,
    patch_track,
)

BASE_PATH = "http://localhost:5217"
PATCH_TRACK = BASE_PATH + "/api/internal/track/{trackId}"
GET_TRACK = BASE_PATH + "/api/music/track/{trackId}"


def get_track(track_id):
    r = requests.get(GET_TRACK.format(trackId=track_id))
    if r.status_code != 200:
        print("Error getting track {}: {}".format(track_id, r.status_code))
        return None
    else:
        return r.json()


def is_patched_track(track_data_rmt, track_data_loc):
    if track_data_loc["original"]:
        if track_data_rmt["original"]:
            return True
        else:
            return False
    else:
        return True


def is_patched_album(album_data_rmt, album_data_loc):
    return album_data_rmt["dataSource"]


def main():
    with open("thc-song-info-format-src.json", "r", encoding="utf-8") as f:
        trk_data = json.load(f)
    with open("thc-album-info-format-src.json", "r", encoding="utf-8") as f:
        alb_data = json.load(f)

    count_track = 0
    count_album = 0
    for idx, (album_id, data) in enumerate(alb_data.items()):
        rmt_album = get_album(album_id)
        if not is_patched_album(rmt_album, data):
            patch_album(album_id, data)
            count_album += 1

    for idx, (track_id, data) in enumerate(trk_data.items()):
        rmt_track = get_track(track_id)
        if not is_patched_track(rmt_track, data):
            patch_track(track_id, data)
            count_track += 1

    # print(f"Total: {count_track}")


if __name__ == "__main__":
    main()
