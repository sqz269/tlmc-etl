import re
import os
from typing import Dict, List, Tuple

import Shared.utils as utils
from Shared.json_utils import json_dump, json_load
from InfoCollector.AlbumInfo.output.path_definitions import (
    DISC_SCANNER_OUTPUT_NAME,
)

output_root = utils.get_file_relative(__file__, "output")
os.makedirs(output_root, exist_ok=True)
scanned_output_file = os.path.join(output_root, DISC_SCANNER_OUTPUT_NAME)


ACCEPTED_AUDIO_FILE_EXTENSIONS = (".flac", ".mp3", ".wav", ".wv")

INTEGER_EXTRACTOR = re.compile(r"(\d+)")
POTENTIAL_DISC_EXTRACTOR = re.compile(r"^\d+\D\d+.+$")


def recurse_search_for_tracks(path: str) -> Dict[str, List[str]]:
    def _recuse_helper(path: str, result: Dict[str, List[str]]):
        files = os.listdir(path)
        for file in files:
            file_path = os.path.join(path, file)
            if os.path.isdir(file_path):
                _recuse_helper(file_path, result)

            elif os.path.isfile(file_path):
                if file.endswith(ACCEPTED_AUDIO_FILE_EXTENSIONS):
                    if path not in result:
                        result[path] = [file_path]
                    else:
                        result[path].append(file_path)

    result = {}
    _recuse_helper(path, result)
    return result


def check_album_dir(album_root: str):
    result = recurse_search_for_tracks(album_root)

    # if we have detected audio file in multiple directories
    # we will assume that the album is split into multiple discs

    # if we have detected audio file in a single directory
    # we need to use POTENTIAL_DISC_EXTRACTOR to check if the
    # file names may contain disc information, if so, we will
    # assume that the album is split into multiple discs based on the
    # disc information in the file names
    potential_disc_dirs = []
    if len(result) == 1:
        for root, files in result.items():
            for file in files:
                file_name = os.path.basename(file)
                if POTENTIAL_DISC_EXTRACTOR.match(file_name):
                    potential_disc_dirs.append(root)
                    break

    else:
        potential_disc_dirs = list(result.keys())
    return potential_disc_dirs


def scan_discs(tlmc_root: str) -> Dict[str, List[str]]:
    potentials = {}
    for artist_dir in os.listdir(tlmc_root):
        artist_dir_path = os.path.join(tlmc_root, artist_dir)
        if not os.path.isdir(artist_dir_path):
            continue

        for album_dir in os.listdir(artist_dir_path):
            album_dir_path = os.path.join(artist_dir_path, album_dir)
            if not os.path.isdir(album_dir_path):
                continue

            potential = check_album_dir(album_dir_path)
            if len(potential) > 0:
                potentials[album_dir_path] = potential

    return potentials


def main():
    tlmc_root = input("Enter TLMC root: ")
    result = scan_discs(tlmc_root)
    print("Found {} potential discs".format(len(result)))
    json_dump(result, scanned_output_file)


if __name__ == "__main__":
    main()
