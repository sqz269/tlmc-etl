import Processor.InfoCollector.AlbumInfo.output.path_definitions as AlbumInfoOutputPaths
import Processor.InfoCollector.ArtistInfo.output.path_definitions as ArtistInfoOutputPaths
import Postprocessor.HlsTranscode.output.path_definitions as HlsTranscodeOutputPaths
import Postprocessor.DbCommit.output.path_definitions as DbCommitOutputPaths
from Shared.utils import get_output_path
from Shared.json_utils import json_load, json_dump

import re
import os
from pathlib import Path
import uuid

album_info_ph3 = get_output_path(
    AlbumInfoOutputPaths, AlbumInfoOutputPaths.INFO_SCANNER_PHASE3_OUTPUT_NAME
)
trancode_filelist_output = get_output_path(
    HlsTranscodeOutputPaths, HlsTranscodeOutputPaths.HLS_TRANSCODE_FILELIST_OUTPUT_NAME
)
artist_list_output = get_output_path(
    ArtistInfoOutputPaths,
    ArtistInfoOutputPaths.ARTIST_DISCOVERY_MERGED_ARTISTS_OUTPUT_PATH,
)
db_commit_output = get_output_path(
    DbCommitOutputPaths, DbCommitOutputPaths.FINALIZED_FILELIST_OUTPUT_NAME
)

def scan_hls_result_files(target_root):
    pass

def scan_hls_master_playlist()

def transform_transcode_filelist_to_fp_key(transcode_filelist) -> dict:
    result = {}
    for k, entry in transcode_filelist.items():
        src = entry[list(entry.keys())[0]]['src']
        
        for quality, target_info in entry.items():
            dst = target_info["dst_root"]


def generate_track_hls_assets(track_path, transcode_filelist):
    # generate HLS directory structure
    dst_dir = transcode_filelist[track_path]["dst_dir"]
    master = transcode_filelist[track_path]["dst_master_playlist"]

    struct = {
        "MasterPlaylist": {
            "Path": master,
            "Id": str(uuid.uuid4()),
        },
        "Variants": {},  # bitrate: { "playlist": <path>, "segments": [<path>], "init": <path> }
    }

    hls_dir = os.path.join(dst_dir, "hls")
    for dir in os.listdir(hls_dir):
        dir_path = os.path.join(hls_dir, dir)
        if not os.path.isdir(os.path.join(hls_dir, dir)):
            continue

        bitrate = re.search(r"(\d+)k", dir)
        if bitrate is None:
            print(f"Invalid bitrate directory {dir}. Aborting")
            exit(1)

        bitrate = int(bitrate.group(1))
        struct["Variants"][bitrate] = {
            "Playlist": {
                "Path": os.path.join(dir_path, "playlist.m3u8"),
                "Id": str(uuid.uuid4()),
            },
            "Init": {
                "Path": os.path.join(dir_path, "init.mp4"),
                "Id": str(uuid.uuid4()),
            },
            "Segments": [],
        }

        for file in os.listdir(dir_path):
            if file.endswith(".m4s"):
                struct["Variants"][bitrate]["Segments"].append(
                    {
                        "Path": os.path.join(dir_path, file),
                        "Id": str(uuid.uuid4()),
                    }
                )

    return struct


def generate(album_info, artist_info, transcode_filelist):
    for album in album_info:
        # assign each album an UUID
        album["Id"] = str(uuid.uuid4())

        # match the album artist with the artist list
        artist = album["AlbumMetadata"]["AlbumArtist"].lower()

        artists_data = artist_info.get(artist, None)
        # should not happen
        if artists_data is None:
            print(f"Artist {artist} not found in artist list. Aborting")
            exit(1)
            continue

        album["AlbumMetadata"]["ArtistIds"] = artists_data["known_id"]

        # assign additional assets id
        for asset in album["Assets"]:
            asset["Id"] = str(uuid.uuid4())
            if asset["AssetPath"] == album["Thumbnail"]:
                album["ThumbnailAssetId"] = asset["Id"]

        # assign each disc an UUID
        for disc_path, disc in album["Discs"].items():
            # this id won't be used unless the album have multiple discs
            disc["Id"] = str(uuid.uuid4())

            # assign each track an UUID
            for track in disc["Tracks"]:
                track["Id"] = str(uuid.uuid4())
                track["Assets"] = generate_track_hls_assets(
                    track["TrackPath"],
                    transcode_filelist,
                )

    return album_info


def main():
    album_info = json_load(album_info_ph3)
    artist_info = json_load(artist_list_output)
    transcode_filelist = json_load(trancode_filelist_output)
    result = generate(album_info, artist_info, transcode_filelist)
    json_dump(result, db_commit_output)


if __name__ == "__main__":
    main()
