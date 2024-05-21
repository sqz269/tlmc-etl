import os
from uuid import uuid4

import Processor.InfoCollector.Aggregator.output.path_definitions as AggregatorPathDef
import Processor.InfoCollector.AlbumInfo.output.path_definitions as AlbumInfoPathDef
import Processor.InfoCollector.ArtistInfo.output.path_definitions as ArtistInfoPathDef
from Shared import json_utils, utils

circle_list_output = utils.get_output_path(
    ArtistInfoPathDef, ArtistInfoPathDef.ARTIST_DISCOVERY_MERGED_ARTISTS_OUTPUT_PATH
)
info_phase3_output = utils.get_output_path(
    AlbumInfoPathDef, AlbumInfoPathDef.INFO_SCANNER_PHASE3_OUTPUT_NAME
)
assigned_merged_output = utils.get_output_path(
    AggregatorPathDef, AggregatorPathDef.ID_ASSIGNED_PATH
)

ASSET_OF_INTEREST_EXTENSIONS = {
    "pdf",
    "vob",
    "ifo",
    "bup",
    "mkv",
    "vtt",
    "swf",
    "mpg",
    "avi",
    "iso",
    "zip",
    "mp4",
}


def move_unassigned_tracks_to_asset(info_phase3):
    for entry in info_phase3:
        for unid in entry["UnidentifiedTracks"]:
            print(f"Reassign unidentified track: {unid['TrackPath']}")
            entry["Assets"].append(
                {
                    "AssetPath": unid["TrackPath"],
                    "AssetName": os.path.basename(unid["TrackPath"]),
                }
            )
        entry["UnidentifiedTracks"] = []


def check_asset_of_interest(info_phase3):
    for entry in info_phase3:
        has_asset_of_interest = False
        for asset in entry["Assets"]:
            ext = os.path.splitext(asset["AssetPath"])[1].replace(".", "").lower()
            if ext in ASSET_OF_INTEREST_EXTENSIONS:
                has_asset_of_interest = True
                break

        entry["HasAssetOfInterest"] = has_asset_of_interest


def match_circle_list(info_phase3, circle_dict):
    for entry in info_phase3:
        album_artist = entry["AlbumMetadata"]["AlbumArtist"]
        album_artist = album_artist.lower()

        matched = circle_dict.get(album_artist)
        if not matched:
            raise ValueError(f"Album artist {album_artist} not found in circle list")

        entry["AlbumMetadata"]["AlbumArtistIds"] = matched["known_id"]


def assign_id(info_phase3):
    for entry in info_phase3:
        entry["AlbumMetadata"]["AlbumId"] = str(uuid4())
        for asset in entry["Assets"]:
            asset["AssetId"] = str(uuid4())

        for disc_path, disc in entry["Discs"].items():
            disc["DiscId"] = str(uuid4())
            for track in disc["Tracks"]:
                track["TrackMetadata"]["TrackId"] = str(uuid4())


def transform_with_album_id_as_key(info_phase3):
    transformed = {}
    for entry in info_phase3:
        album_id = entry["AlbumMetadata"]["AlbumId"]
        transformed[album_id] = entry

    return transformed


def main():
    circle_list = json_utils.json_load(circle_list_output)
    info_phase3 = json_utils.json_load(info_phase3_output)

    print("Assigning IDs and merging info...")

    print("Moving unidentified tracks to assets...")
    move_unassigned_tracks_to_asset(info_phase3)

    print("Checking asset of interest...")
    check_asset_of_interest(info_phase3)

    print("Matching circle list...")
    match_circle_list(info_phase3, circle_list)

    print("Assigning IDs...")
    assign_id(info_phase3)

    print("Transforming with album id as key...")
    info_phase3 = transform_with_album_id_as_key(info_phase3)

    print("Writing output...")
    json_utils.json_dump(info_phase3, assigned_merged_output)


if __name__ == "__main__":
    main()
