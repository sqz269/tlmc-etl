from collections import Counter
import os
import json
import re
from typing import Iterable, List, Tuple

import Shared.utils as utils
from Shared.json_utils import json_dump, json_load

from Processor.InfoCollector.AlbumInfo.output.path_definitions import (
    INFO_SCANNER_PHASE1_OUTPUT_NAME,
    INFO_SCANNER_PHASE2_ALBUMINFO_OUTPUT_NAME,
    INFO_SCANNER_PHASE2_TRACKINFO_OUTPUT_NAME,
    INFO_SCANNER_PHASE3_OUTPUT_NAME,
)

output_root = utils.get_file_relative(__file__, "output")
os.makedirs(output_root, exist_ok=True)
phase1_output_path = os.path.join(output_root, INFO_SCANNER_PHASE1_OUTPUT_NAME)
phase2_trackinfo_output_path = os.path.join(
    output_root, INFO_SCANNER_PHASE2_TRACKINFO_OUTPUT_NAME
)
phase2_albuminfo_output_path = os.path.join(
    output_root, INFO_SCANNER_PHASE2_ALBUMINFO_OUTPUT_NAME
)
phase3_output_path = os.path.join(output_root, INFO_SCANNER_PHASE3_OUTPUT_NAME)


def rm_man_check_props(dict: dict) -> dict:
    """Remove properties that are needed for manual check"""
    dict.pop("NeedsManualCheck", None)
    dict.pop("NeedsManualCheckReason", None)


def merge(ph1, ph2_track, ph2_album):
    for album in ph1:
        album_root = album["AlbumRoot"]
        album_metadata = ph2_album[album_root]
        rm_man_check_props(album_metadata)
        album.update({"AlbumMetadata": album_metadata})

        for disc in album["Discs"]:
            tracks = album["Discs"][disc]["Tracks"]
            # sort tracks by their track path basename
            tracks.sort(key=lambda track: os.path.basename(track["TrackPath"]))

            for idx, track in enumerate(tracks):
                track_metadata = ph2_track[track["TrackPath"]]
                rm_man_check_props(track_metadata)
                track["TrackMetadata"] = track_metadata
                if track["TrackMetadata"]["title"] == "":
                    print(
                        f"Empty title for track [{track['TrackPath']}], assigning basename (without extension)"
                    )
                    track["TrackMetadata"]["title"] = os.path.splitext(
                        os.path.basename(track["TrackPath"])
                    )[0]

                if track["TrackMetadata"]["track"] == -1:
                    print(
                        f"Sequentially assigned track number [{idx + 1}] for",
                        track["TrackPath"],
                    )
                    track["TrackMetadata"]["track"] = idx + 1


def main():
    phase1_output = json_load(phase1_output_path)
    phase2_trackinfo_output = json_load(phase2_trackinfo_output_path)
    phase2_albuminfo_output = json_load(phase2_albuminfo_output_path)

    # merge phase1 and phase2
    merge(phase1_output, phase2_trackinfo_output, phase2_albuminfo_output)
    json_dump(phase1_output, phase3_output_path)


if __name__ == "__main__":
    main()
