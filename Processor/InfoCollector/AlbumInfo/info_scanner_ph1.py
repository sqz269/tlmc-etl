import json
import os
from typing import List, Tuple

import Shared.utils as utils
from Processor.InfoCollector.AlbumInfo.output.path_definitions import (
    DISC_MANUAL_CHECKER_OUTPUT_NAME, INFO_SCANNER_FILELIST_OUTPUT_NAME,
    INFO_SCANNER_PHASE1_OUTPUT_NAME, INFO_SCANNER_PROBED_RESULT_DEBUG_NAME,
    INFO_SCANNER_PROBED_RESULT_OUTPUT_NAME,
    INFO_SCANNER_PROBED_RESULT_TMP_LINES_OUTPUT_NAME)
from Shared.json_utils import json_dump, json_load

output_root = utils.get_file_relative(__file__, "output")
os.makedirs(output_root, exist_ok=True)
disc_final_output_file = os.path.join(output_root, DISC_MANUAL_CHECKER_OUTPUT_NAME)
probed_results_path = os.path.join(output_root, INFO_SCANNER_PROBED_RESULT_OUTPUT_NAME)
probed_results_path_tmp_lines = os.path.join(
    output_root, INFO_SCANNER_PROBED_RESULT_TMP_LINES_OUTPUT_NAME
)
probed_results_path_debug = os.path.join(
    output_root, INFO_SCANNER_PROBED_RESULT_DEBUG_NAME
)
filelist_output_path = os.path.join(output_root, INFO_SCANNER_FILELIST_OUTPUT_NAME)
phase1_output_path = os.path.join(output_root, INFO_SCANNER_PHASE1_OUTPUT_NAME)

ACCEPTED_AUDIO_FILE_EXTENSIONS = {"flac", "mp3", "wav", "wv", "m4a"}
THUMBNAIL_FILE_NAMES = {"folder", "cover"}
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "bmp", "svg", "webp", "ico", "tif"}
# Video, DVD, and other media of interest
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
# IGNORED_ALBUMS = (
#     "[クロネコラウンジ]/.mp3",
#     "[サウンドカタログ推進委員会]/2009.10.11 [PSSC-001] Sound Catalog 001 [M3-24]",
#     "[R-note] あ～るの～と/2014.10.12 [RNCD-0009] 東方M-1ぐらんぷり～Sound Collection～ [東方紅楼夢10]",
#     "Various Artists/project-SIGMA - Sound Catalog 001 (2009 Autumn Version)",
# )


def filter_probe_list(file_list):
    """
    Filter file list to only include files that needs to be probed, makes a copy of the file list
    Probe criteria:
        - Extension is in ACCEPTED_AUDIO_FILE_EXTENSIONS
    """
    to_probe = []

    for dir_path, dir_info in file_list.items():
        flat = flatten_dir_from_path(file_list, dir_path)
        for path, files in flat.items():
            for file in files:
                file_ext = file[file.rfind(".") + 1 :].lower()
                if file_ext in ACCEPTED_AUDIO_FILE_EXTENSIONS:
                    to_probe.append(join_paths(path, file))

    return to_probe


def _flatten_help(dir_path, dir_struct, flat):
    for dir in dir_struct["dirs"]:
        for path, dir_info in dir.items():
            _flatten_help(path, dir_info, flat)

    flat[dir_path] = dir_struct["files"]


def flatten_dir_from_path(file_list, target) -> dict:
    if target is None:
        raise ValueError("Target cannot be None")

    if target not in file_list:
        raise ValueError("Target not found in file list")

    dir_info = file_list[target]
    flat = {}
    _flatten_help(target, dir_info, flat)
    return flat


def flatten_dir_from_info_struct(dir_path, dir_struct) -> dict:
    flat = {}
    _flatten_help(dir_path, dir_struct, flat)
    return flat


def reformat_probed(probe_results):
    reformatted = {}
    for entry in probe_results:
        path = entry["format"]["filename"]
        reformatted[path] = entry["format"]

    return reformatted


def reformat_discs_info(discs_info):
    reformatted = {}
    for disc in discs_info:
        for path, info in disc.items():
            reformatted[path] = info

    return reformatted


def join_paths(*paths):
    """
    Join multiple paths using the separator detected from the first path argument.
    If no separator is detected, use os.sep as the separator.
    """
    sep = os.sep
    if len(paths) > 0:
        first_path = paths[0]
        if "/" in first_path:
            sep = "/"
        elif "\\" in first_path:
            sep = "\\"

    # strip all separators from the end of each path
    paths = [path.rstrip(sep) for path in paths]
    return sep.join(paths)


class Phase01:
    def __init__(self, file_list, discs_info) -> None:
        self.file_list = file_list
        self.discs_info = discs_info

    def gen_track_list(self, dir_path, dir_info: dict):
        track_list = []
        for file_name in dir_info["files"]:
            # check extension
            file_ext = file_name[file_name.rfind(".") + 1 :].lower()
            if file_ext in ACCEPTED_AUDIO_FILE_EXTENSIONS:
                track_list.append(join_paths(dir_path, file_name))
        return track_list

    def gen_asset_and_unid_track_list(
        self, dir_path, dir_info: dict, known_tracks
    ) -> Tuple[List[str], List[str]]:
        """
        Generates lists of asset paths and unidentified track paths from a directory path, directory information, and known tracks.

        Args:
            dir_path (str): The directory path.
            dir_info (dict): The directory information.
            known_tracks (list): A list of known track paths.

        Returns:
            Tuple[List[str], List[str]]: A tuple containing the asset list and the unidentified track list.

        """
        flat = flatten_dir_from_info_struct(dir_path, dir_info)
        asset_list = []
        unid_track_list = []
        for dir, files in flat.items():
            for file in files:
                file_ext = file[file.rfind(".") + 1 :].lower()
                if file_ext in ACCEPTED_AUDIO_FILE_EXTENSIONS:
                    fp = join_paths(dir, file)
                    if fp in known_tracks:
                        continue
                    unid_track_list.append(fp)
                    continue
                asset_list.append(join_paths(dir, file))

        return (asset_list, unid_track_list)

    def identify_thumbnail(self, asset_list):
        """
        Identifies a thumbnail asset path from a list of asset paths.

        Args:
            asset_list (list): A list of asset paths.

        Returns:
            str: The thumbnail asset path, or None if no thumbnail is found.

        """
        for asset in asset_list:
            file_name = os.path.basename(asset).lower()

            file_ext = file_name[file_name.rfind(".") + 1 :].lower()
            file_name_no_ext = file_name[: file_name.rfind(".")].lower()
            if (
                file_ext in IMAGE_EXTENSIONS
                and file_name_no_ext in THUMBNAIL_FILE_NAMES
            ):
                return asset
        return None

    def has_asset_of_interest(self, asset_list):
        """
        Checks if a list of asset paths contains an asset of interest.

        Args:
            asset_list (list): A list of asset paths.

        Returns:
            bool: True if an asset of interest is found, False otherwise.

        """
        for asset in asset_list:
            file_name = os.path.basename(asset).lower()
            file_ext = file_name[file_name.rfind(".") + 1 :].lower()
            if file_ext in ASSET_OF_INTEREST_EXTENSIONS:
                return True
        return False

    def process_one(self, dir_path: str, dir_info: dict):
        """
        Processes a single directory and returns the generated information.

        Args:
            dir_path (str): The directory path.
            dir_info (dict): The directory information.

        Returns:
            dict: The generated information.

        """
        track_list = self.gen_track_list(dir_path, dir_info)
        asset_list, unid_track_list = self.gen_asset_and_unid_track_list(
            dir_path, dir_info, track_list
        )
        thumbnail = self.identify_thumbnail(asset_list)

        if len(track_list) == 0:
            dirpath = [os.path.dirname(track) for track in unid_track_list]
            unique_dirpaths = set(dirpath)
            if len(unique_dirpaths) == 1:
                track_list = unid_track_list
                unid_track_list = []

        needs_manual_review = (
            len(unid_track_list) > 0
            or len(asset_list) == 0
            or thumbnail is None
            or len(track_list) == 0
        )
        needs_manual_review_reason = []
        if len(unid_track_list) > 0:
            needs_manual_review_reason.append("Unidentified Tracks")
        if len(asset_list) == 0:
            needs_manual_review_reason.append("No Asset Files")
        if thumbnail is None:
            needs_manual_review_reason.append("No Thumbnail")
        if len(track_list) == 0:
            needs_manual_review_reason.append("No Tracks")

        return {
            "AlbumRoot": dir_path,
            "Discs": {
                dir_path: {
                    "DiscNumber": 0,
                    "DiscName": "",
                    "Tracks": [
                        {
                            "TrackPath": track,
                        }
                        for track in track_list
                    ],
                }
            },
            "Assets": [
                {
                    "AssetPath": asset,
                    "AssetName": os.path.basename(asset),
                }
                for asset in asset_list
            ],
            "Thumbnail": thumbnail,
            "UnidentifiedTracks": [
                {
                    "TrackPath": track,
                }
                for track in unid_track_list
            ],
            "HasAssetOfInterest": self.has_asset_of_interest(asset_list),
            "NeedsManualReview": needs_manual_review,
            "NeedsManualReviewReason": needs_manual_review_reason,
        }

    def gen_track_list_from_discs(self, dir_path: str, flatten: dict):
        """
        Generates a list of track paths from a directory path and flattened directory structure.

        Args:
            dir_path (str): The directory path.
            flatten (dict): The flattened directory structure.

        Returns:
            List[str]: A list of track paths.

        """
        track_list = []
        files = flatten[dir_path]
        for file in files:
            file_ext = file[file.rfind(".") + 1 :]
            if file_ext in ACCEPTED_AUDIO_FILE_EXTENSIONS:
                track_list.append(join_paths(dir_path, file))
        return track_list

    def gen_asset_and_unid_track_list_for_discs(
        self, flatten: dict, all_tracks: list
    ) -> Tuple[List[str], List[str]]:
        """
        Generates lists of asset paths and unidentified track paths from a flattened directory structure and all tracks.

        Args:
            flatten (dict): The flattened directory structure.
            all_tracks (list): A list of all track paths.

        Returns:
            Tuple[List[str], List[str]]: A tuple containing the asset list and the unidentified track list.

        """
        all_tracks_set = set(all_tracks)
        asset_list = []
        unid_track_list = []
        for dir, files in flatten.items():
            for file in files:
                fp = join_paths(dir, file)
                if fp in all_tracks_set:
                    continue

                file_ext = file[file.rfind(".") + 1 :]
                if file_ext in ACCEPTED_AUDIO_FILE_EXTENSIONS:
                    unid_track_list.append(fp)
                    continue

                asset_list.append(fp)

        return (asset_list, unid_track_list)

    def process_discs(self, dir_path: str, dir_info: dict):
        """
        Processes a directory with multiple discs and returns the generated information.

        Args:
            dir_path (str): The directory path.
            dir_info (dict): The directory information.

        Returns:
            dict: The generated information.

        """
        flatten = flatten_dir_from_path(self.file_list, dir_path)
        discs_info = self.discs_info[dir_path]

        new_discs_info = {}

        all_tracks = []
        for discs in discs_info:
            discs_path = discs["path"]
            track_list = self.gen_track_list_from_discs(discs_path, flatten)
            all_tracks.extend(track_list)
            new_discs_info[discs_path] = {
                "DiscNumber": discs["disc_number"],
                "DiscName": discs["disc_name"],
                "Tracks": [{"TrackPath": track} for track in track_list],
            }

        asset_list, unid_track_list = self.gen_asset_and_unid_track_list_for_discs(
            flatten, all_tracks
        )
        thumbnail = self.identify_thumbnail(asset_list)

        has_tracks = all([len(disc["Tracks"]) > 0 for disc in new_discs_info.values()])
        needs_manual_review = (
            len(unid_track_list) > 0
            or len(asset_list) == 0
            or thumbnail is None
            or not has_tracks
        )
        needs_manual_review_reason = []
        if len(unid_track_list) > 0:
            needs_manual_review_reason.append("Unidentified Tracks")
        if len(asset_list) == 0:
            needs_manual_review_reason.append("No Asset Files")
        if thumbnail is None:
            needs_manual_review_reason.append("No Thumbnail")
        if not has_tracks:
            needs_manual_review_reason.append("No Tracks")

        return {
            "AlbumRoot": dir_path,
            "Discs": {
                disc_path: disc_info for disc_path, disc_info in new_discs_info.items()
            },
            "Assets": [
                {
                    "AssetPath": asset,
                    "AssetName": os.path.basename(asset),
                }
                for asset in asset_list
            ],
            "Thumbnail": thumbnail,
            "UnidentifiedTracks": [
                {
                    "TrackPath": track,
                }
                for track in unid_track_list
            ],
            "NeedsManualReview": needs_manual_review,
            "NeedsManualReviewReason": needs_manual_review_reason,
        }

    def generate(self):
        """
        Generates the track and asset information for all directories in the file list.

        Returns:
            list: A list of generated information for each directory.

        """
        results = []
        for dir_path, dir_info in self.file_list.items():
            # if dir_path.endswith(IGNORED_ALBUMS):
            #     print(f"Skipping {dir_path}")
            #     continue
            if dir_path in self.discs_info:
                results.append(self.process_discs(dir_path, dir_info))
                continue
            results.append(self.process_one(dir_path, dir_info))
        return results


def _gen_directory_tree_help(path: str, relative_depth: int) -> dict:
    files = [
        file for file in os.listdir(path) if os.path.isfile(join_paths(path, file))
    ]

    dirs = [dir for dir in os.listdir(path) if os.path.isdir(join_paths(path, dir))]

    return {
        path: {
            "relative_depth": relative_depth,
            "files": files,
            "dirs": [
                _gen_directory_tree_help(join_paths(path, dir), relative_depth + 1)
                for dir in dirs
            ],
        }
    }


def gen_directory_tree(path: str):
    return _gen_directory_tree_help(path, 2)


def gen_file_list(root):
    circles = [
        full_path
        for name in os.listdir(root)
        if (full_path := join_paths(root, name)) and os.path.isdir(full_path)
    ]
    albums = [
        full_path
        for circle in circles
        for name in os.listdir(circle)
        if (full_path := join_paths(circle, name)) and os.path.isdir(full_path)
    ]

    directory_tree = {}
    for album in albums:
        directory_tree.update(gen_directory_tree(album))

    return directory_tree


def gen_probe_results(file_list):
    probe_results = []
    filtered = filter_probe_list(file_list)
    for index, file_path in enumerate(filtered):
        file_name = os.path.basename(file_path)
        print(f"[{index}/{len(filtered)}] Probing: {file_name}", end="\r")
        result = utils.probe_flac("ffprobe", file_path)
        if result:
            json_result = json.loads(result)
            utils.append_file(
                probed_results_path_tmp_lines,
                json.dumps(json_result, ensure_ascii=False) + "\n",
            )
            utils.append_file(
                probed_results_path_debug,
                json.dumps(
                    {
                        "index": index,
                        "path": file_path,
                        "format": json_result.get("format"),
                    },
                    ensure_ascii=False,
                )
                + "\n",
            )
            probe_results.append(json_result)
    return probe_results


def main():
    if not os.path.exists(disc_final_output_file):
        raise FileNotFoundError(
            f"Disc scanner output file not found: {disc_final_output_file}"
        )

    if not os.path.exists(filelist_output_path):
        tlmc_root = input("Enter TLMC root: ")
        print("Generating file list...")
        file_list = gen_file_list(tlmc_root)
        json_dump(file_list, filelist_output_path)

    if not os.path.exists(probed_results_path):
        print("Generating probe results...")
        probe_results = gen_probe_results(file_list)
        reformat_probed_results = reformat_probed(probe_results)
        json_dump(reformat_probed_results, probed_results_path)

    file_list = json_load(filelist_output_path)
    reformat_probed_results = json_load(probed_results_path)

    print("Loading discs info...")
    discs_info = json_load(disc_final_output_file)

    print("Starting phase 1...")
    phase1 = Phase01(file_list, discs_info)
    phase1_results = phase1.generate()

    print("Dumping phase 1 results...")
    json_dump(phase1_results, phase1_output_path)


if __name__ == "__main__":
    main()
