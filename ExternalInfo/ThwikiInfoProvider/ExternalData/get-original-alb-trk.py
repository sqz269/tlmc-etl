import json

from ExternalInfo.ThwikiInfoProvider.ThcOriginalTrackMapper.Model.OriginalTrackMapModel import (
    OriginalTrack,
    TrackSource,
)
from ExternalInfo.ThwikiInfoProvider.ThcOriginalTrackMapper.SongQuery import (
    SongQuery,
    get_original_song_query_params,
)
from ExternalInfo.ThwikiInfoProvider.ThcSongInfoProvider.Model.ThcSongInfoModel import (
    Track,
)

exc = {"かごめかごめ"}

non_offical_works = {
    "地灵殿PH音乐名",
    "东方夏夜祭音乐名",
    "Cradle音乐名",
    "东方音焰火音乐名",
    "东方魔宝城音乐名",
    "8MPF音乐名",
    "东方梦旧市音乐名",
    "神魔讨绮传音乐名",
    "风神录PH音乐名",
    "TLM音乐名",
    "かごめかごめ",
}


def strict_split(str, sep=",", brackets={"(": ")", "{": "}", "[": "]"}):
    stack = []
    parts = []
    part = ""
    for c in str:
        if c in brackets.keys():
            stack.append(c)
        elif c in brackets.values():
            stack.pop()
        elif c == sep and not stack:
            parts.append(part)
            part = ""
            continue
        part += c
    parts.append(part)
    return parts


def discover():

    print("Discovering original album and tracks...")
    track: Track = None
    count = 0
    original_songs = 0
    for track in Track.select():
        if not track.original:
            continue

        parse = json.loads(track.original)

        ps = []
        for k in parse:
            ps.extend([l.strip() for l in strict_split(k) if l and l not in exc])

        qp = get_original_song_query_params(ps)

        for q in qp:
            count += 1
            original_songs += len(qp)
            print(
                f"Queried {count} tracks, {original_songs} Original songs [{len(qp)}]",
                end="\r",
            )

            if q[0] in non_offical_works:
                continue

            SongQuery.query(
                q[0],
                q[1],
            ).title_en


def load_existing(path):
    print("Loading existing...")
    with open(path, "r", encoding="utf-8") as f:
        # skip header
        f.readline()
        existing = {}
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = line.split(",")
            id = data[0]
            existing[id] = data
    return existing


def create_blank_sheet(existing):
    print("Creating blank sheet...")
    exist = {}
    if existing:
        exist = load_existing(existing)
    col_names = "Id,Type,Abbriv,Full Name En,Full Name Zh,Full Name Jp,Short Name En,Short Name Zh,Short Name Jp"

    lines = []
    ids = set([source.id for source in TrackSource.select(TrackSource.id).distinct()])
    existing_ids = set(exist.keys())
    missing_ids = ids - existing_ids

    for id in missing_ids:
        lines.append(id + "," * col_names.count(","))

    for ex in exist.values():
        lines.append(",".join(ex))

    print('Created csv sheet at "OriginalAlbums_Blank.csv"')
    with open("OriginalAlbums_Blank.csv", "w", encoding="utf-8") as f:
        f.write(col_names + "\n")
        f.write("\n".join(lines))


if __name__ == "__main__":
    if Track.select().count() == 0:
        print("No tracks found. Please run ThcSongInfoProvider first.")
        exit(0)

    if OriginalTrack.select().count() == 0:
        discover()
    else:
        print("Original tracks found. Do you want to discover again? (y/n)")
        if input() == "y":
            discover()

    import_data = input("\nEnter Existing Csv Path (If needed): ")
    create_blank_sheet(import_data)
