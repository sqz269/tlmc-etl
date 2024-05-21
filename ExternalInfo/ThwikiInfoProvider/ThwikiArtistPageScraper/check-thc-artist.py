import json
import unicodedata

from ExternalInfo.ThwikiInfoProvider.ThwikiAlbumPageScraper.Model.ThcSongInfoModel import (
    Album,
)


def remove_non_content_letters(text):
    normalized = unicodedata.normalize("NFKD", text)
    for char in normalized:
        if not unicodedata.category(char).startswith("L"):
            normalized = normalized.replace(char, "")
    return normalized


def load_circles() -> set:
    circles: set = set()
    circles_check = []
    circle: BasicCircle
    for circle in BasicCircle.select():
        name_norm = remove_non_content_letters(circle.name).lower()
        alias_norm = [
            remove_non_content_letters(alias).lower()
            for alias in json.loads(circle.alias)
        ]

        circles.add(name_norm)
        circles_check.append(name_norm)

        for alias in alias_norm:
            circles.add(alias)
            circles_check.append(alias)

    return circles


if __name__ == "__main__":
    circles = load_circles()
    miss = {}
    album: Album
    for album in Album.select():
        if album.album_artist is None:
            continue

        artists = json.loads(album.album_artist)
        artist_norm = [remove_non_content_letters(artist).lower() for artist in artists]
        for artist in artist_norm:
            if artist not in circles:
                print("Artist {} not found in circles".format(artist))
                print("Album: {}".format(album.album_id))
                miss[artist] = album.album_id

    print(json.dumps(miss, indent=4, ensure_ascii=False))
