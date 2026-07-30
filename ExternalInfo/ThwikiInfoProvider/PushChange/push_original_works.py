"""Pushes the original work/song vocabulary to the v6 backend.

Replaces commit_origina_album_and_track.py. Reads the filled abbreviation CSV
(work identity + names) and the original_track_map.db (songs per work), then
upserts via:

  POST api/source/work                  {external_key, work_type, full_name, short_name, external_ref}
  POST api/source/work/{workId}/song    {external_key, title, track_index, external_ref}

Both upsert on external_key, so the script is safe to re-run. Work external_key
is the CSV abbreviation (e.g. "FW"); song external_key is "{abbriv}-{index}" —
exactly the keys the stage 4 matcher emits into track_format_result.
"""

import csv
import sys
import unicodedata

from ExternalInfo.ThwikiInfoProvider.PushChange.api_client import make_session, send
from ExternalInfo.ThwikiInfoProvider.ThwikiOriginalTrackMapper.Model.OriginalTrackMapModel import (
    OriginalTrack,
)
from ExternalInfo.ThwikiInfoProvider.ThwikiOriginalTrackMapper.original_track_map import (
    non_offical_works,
)

DEFAULT_CSV = "ExternalInfo/ThwikiInfoProvider/OriginalAlbums_v6_filled.csv"

MISMATCH = "<MISMATCH>"


def nfkc(value: str):
    value = (value or "").strip()
    if not value or value == MISMATCH:
        return None
    return unicodedata.normalize("NFKC", value)


def localized(default, en, zh, jp):
    # Default falls back down the jp > en > zh chain; the field is required.
    default = nfkc(default) or nfkc(jp) or nfkc(en) or nfkc(zh)
    return {
        "default": default,
        "en": nfkc(en),
        "zh": nfkc(zh),
        "jp": nfkc(jp),
    }


def load_works(csv_path):
    works = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)
        for line in reader:
            # Id,Type,Abbriv,Full En,Full Zh,Full Jp,Short En,Short Zh,Short Jp
            source_id, work_type, abbriv = line[0], line[1], line[2]
            works[source_id] = {
                "external_key": abbriv,
                "work_type": work_type,
                "full_name": localized(line[5], line[3], line[4], line[5]),
                "short_name": localized(line[8], line[6], line[7], line[8]),
                "external_ref": source_id,
            }
    return works


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    works = load_works(csv_path)
    session = make_session()

    # Only push works that actually carry songs; alias relics (憑依華) and
    # blacklisted fan works have no OriginalTrack rows and stay local.
    pushed_songs = 0
    failures = []
    for source_id, work in works.items():
        if source_id in non_offical_works:
            continue

        tracks = list(
            OriginalTrack.select().where(OriginalTrack.source == source_id)
        )
        if not tracks:
            continue

        resp = send(session, "POST", "/api/source/work", work)
        if resp.status_code != 200:
            failures.append(f"work {work['external_key']} ({source_id}): {resp.status_code} {resp.text[:200]}")
            print(f"FAILED work {work['external_key']}: {resp.status_code}")
            continue
        work_id = resp.json()["id"]
        print(f"work {work['external_key']} -> {work_id} ({len(tracks)} songs)")

        for track in tracks:
            index = (track.index or "").strip()
            song = {
                "external_key": f"{work['external_key']}-{index}",
                "title": localized(track.title_jp, track.title_en, track.title_zh, track.title_jp),
                "track_index": int(index) if index.isdigit() else None,
                "external_ref": f"{source_id}/{index}",
            }
            resp = send(session, "POST", f"/api/source/work/{work_id}/song", song)
            if resp.status_code != 200:
                failures.append(f"song {song['external_key']}: {resp.status_code} {resp.text[:200]}")
                print(f"  FAILED song {song['external_key']}: {resp.status_code}")
                continue
            pushed_songs += 1

    print(f"\nPushed {pushed_songs} songs. {len(failures)} failures.")
    if failures:
        with open("push_original_works_failures.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(failures) + "\n")
        print("See push_original_works_failures.txt")


if __name__ == "__main__":
    main()
