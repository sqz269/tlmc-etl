import requests
import json

BASE_PATH = "http://localhost:5217"

PATCH_TRACK = BASE_PATH + "/api/internal/track/{trackId}"
PATCH_ALBUM = BASE_PATH + "/api/internal/album/{albumId}"
GET_ALBUM = BASE_PATH + "/api/music/album/{albumId}"

def patch_track(track_id, data):
    data = {
        "arrangement": data["arrangement"],
        "vocalist": data["vocal"],
        "lyricist": data["lyricist"],
        "original": data["original"]
    }

    r = requests.patch(PATCH_TRACK.format(trackId=track_id), json=data)
    if (r.status_code != 200):
        print("Error patching track {}: {}".format(track_id, r.status_code))
    else:
        print("Patched track {}".format(track_id))


def get_album(album_id):
    r = requests.get(GET_ALBUM.format(albumId=album_id))
    if (r.status_code != 200):
        print("Error getting album {}: {}".format(album_id, r.status_code))
        return None
    else:
        return r.json()

def patch_album(album_id, data):
    alb = get_album(album_id)
    
    if (alb is None):
        return
    
    json_patches = []
    if (not alb["catalogNumber"] and data["catalog"]):
        json_patches.append({
            "op": "replace",
            "path": "/CatalogNumber",
            "value": data["catalog"]
        })

    json_patches.append({
        "op": "add",
        "path": "/Website/-",
        "value": data["website"]
    })

    json_patches.append({
        "op": "add",
        "path": "/DataSource/-",
        "value": data["data_source"]
    })

    r = requests.patch(PATCH_ALBUM.format(albumId=album_id), json=json_patches)
    if (r.status_code != 200):
        print("Error patching album {}: {}".format(album_id, r.status_code))
    else:
        print("Patched album {}".format(album_id))

def main():
    with open("thc-song-info-format-src.json", "r", encoding="utf-8") as f:
        trk_data = json.load(f)

    with open("thc-album-info-format-src.json", "r", encoding="utf-8") as f:
        alb_data = json.load(f)

    for album_id, album_data in alb_data.items():
        patch_album(album_id, album_data)

    # for track_id, track_data in trk_data.items():
    #     patch_track(track_id, track_data)

if __name__ == "__main__":
    main()
