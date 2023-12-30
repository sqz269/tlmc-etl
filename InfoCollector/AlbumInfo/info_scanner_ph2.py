from collections import Counter
import os
import json
import re
from typing import Iterable, List, Tuple

import Shared.utils as utils
from Shared.json_utils import json_dump, json_load

from InfoCollector.AlbumInfo.output.path_definitions import (
    INFO_SCANNER_PROBED_RESULT_OUTPUT_NAME,
    INFO_SCANNER_PHASE1_OUTPUT_NAME,
    INFO_SCANNER_PHASE2_ALBUMINFO_OUTPUT_NAME,
    INFO_SCANNER_PHASE2_TRACKINFO_OUTPUT_NAME,
)

TRACK_INFO_EXTRACTOR_V2 = re.compile(
    r"\((\d{2})\) \[([^]]+)\] (.+)\.flac", re.IGNORECASE
)
TRACK_INFO_VALIDATION_V2 = re.compile(r"^\(\d{2}\) \[[^]]+\] .+\.flac$", re.IGNORECASE)

ALBUM_DATE_VALIDATOR = re.compile(r"(\d{4}\.(?:\d|x){2}\.(?:\d|x){2}).?", re.IGNORECASE)

CIRCLE_INFO_EXTRACTOR = re.compile(r"\[(.+)\]")

ALBUM_DATE_VALIDATOR = re.compile(
    r"(\d{4}(?:\.(?:\d{2}|x{2}))?(?:\.(?:\d{2}|x{2}))?)", re.IGNORECASE
)


output_root = utils.get_file_relative(__file__, "output")
os.makedirs(output_root, exist_ok=True)
probed_results_path = os.path.join(output_root, INFO_SCANNER_PROBED_RESULT_OUTPUT_NAME)
phase1_output_path = os.path.join(output_root, INFO_SCANNER_PHASE1_OUTPUT_NAME)
phase2_trackinfo_output_path = os.path.join(
    output_root, INFO_SCANNER_PHASE2_TRACKINFO_OUTPUT_NAME
)
phase2_albuminfo_output_path = os.path.join(
    output_root, INFO_SCANNER_PHASE2_ALBUMINFO_OUTPUT_NAME
)


def get_all_tracks(album) -> List[str]:
    tracks = []
    for disc in album["Discs"].values():
        for track in disc["Tracks"]:
            tracks.append(track["TrackPath"])
    return tracks


def extract_bracket_content(s) -> List[str]:
    brackets = {
        # "(": ")",
        "[": "]",
        "{": "}",
    }

    # find the starting position of all brackets (first occurace) and sort them by their positions
    bracket_positions = {}
    for k, v in brackets.items():
        pos = s.find(k)
        if pos != -1:
            bracket_positions[pos] = k

    bracket_positions = sorted(bracket_positions.items(), key=lambda x: x[0])
    # get the most outer bracket
    if len(bracket_positions) == 0:
        return []

    outer_bracket = bracket_positions[0]
    outer_bracket_start = outer_bracket[0]
    outer_bracket_end = s.find(brackets[outer_bracket[1]], outer_bracket_start)
    if outer_bracket_end == -1:
        print("Invalid string: Unterminated bracket. Faulty string: " + s)
        return []

    # include the brackets itself
    outer_bracket_content = s[outer_bracket_start + 1 : outer_bracket_end]
    return [outer_bracket_content] + extract_bracket_content(s[outer_bracket_end + 1 :])


def str_rm_substrings(s, sub: Iterable[str]):
    for sub_str in sub:
        s = s.replace(sub_str, "")
    return s


class Phase02TrackExtractor:
    KEYS = {"track", "artist", "title"}

    def __init__(self, phase_1_result, probe_result) -> None:
        self.phase_1_result = phase_1_result
        self.probe_result = probe_result

    def try_extract_track_info_from_path(self, track_path):
        filename = os.path.basename(track_path)
        is_valid = TRACK_INFO_VALIDATION_V2.match(filename)
        if not is_valid:
            return None

        match = TRACK_INFO_EXTRACTOR_V2.match(filename)
        if not match:
            return None

        track_number = match.group(1)
        track_artist = match.group(2)
        track_title = match.group(3)
        return {
            "track": int(track_number),
            "artist": track_artist,
            "title": track_title,
        }

    def extract_track_info_from_probed_results(self, track_path):
        keys = Phase02TrackExtractor.KEYS
        probed_data = self.probe_result[track_path].get("tags", {})

        # convert all keys to lower case
        probed_data = {k.lower(): v for k, v in probed_data.items()}
        # filter out keys that are not in the keys set
        probed_data = {k: v for k, v in probed_data.items() if k in keys}
        if len(probed_data) != len(keys):
            # add the missing keys
            for k in keys:
                if k not in probed_data:
                    probed_data[k] = ""

        if type(probed_data["track"]) == str and not probed_data["track"].isdecimal():
            probed_data["track"] = -1
        # turn track number into integer
        else:
            probed_data["track"] = int(probed_data["track"])
        return probed_data

    def extract_and_merge_track_info(self, track_path):
        probed_data = self.extract_track_info_from_probed_results(track_path)
        path_data = self.try_extract_track_info_from_path(track_path)

        # merge the two data, prioritize probed data
        if path_data is not None:
            for k in Phase02TrackExtractor.KEYS:
                if probed_data[k] == "" or probed_data[k] == -1:
                    probed_data[k] = path_data[k]

        needs_manual_check = False
        needs_manual_check_reason = []
        if probed_data["track"] == -1:
            needs_manual_check = True
            needs_manual_check_reason.append("Track number is empty")

        if probed_data["title"] == "":
            needs_manual_check = True
            needs_manual_check_reason.append("Track title is empty")

        probed_data["NeedsManualCheck"] = needs_manual_check
        probed_data["NeedsManualCheckReason"] = needs_manual_check_reason

        return probed_data

    def process(self):
        probed_info = {}
        for album in self.phase_1_result:
            tracks = get_all_tracks(album)
            for track in tracks:
                pi = self.extract_and_merge_track_info(track)
                probed_info[track] = pi

        return probed_info


class Phase02AlbumExtractor:
    def __init__(self, phase_1_result, probe_result) -> None:
        self.phase_1_result = phase_1_result
        self.probe_result = probe_result

    # STATIC METHODS
    def try_extract_date(album_name, brackets):
        date_potential = album_name[0:10]
        date_match = ALBUM_DATE_VALIDATOR.match(date_potential)
        if date_match:
            return date_match.group(1)
        else:
            # try match date from brackets
            for bracket in brackets:
                date_match = ALBUM_DATE_VALIDATOR.match(bracket)
                if date_match:
                    return date_match.group(1)
        return ""

    def try_extract_album_name(album_name, brackets):
        # remove all brackets from dirname
        # may be inaccurate if the album name contains brackets
        album_name = str_rm_substrings(album_name, brackets)
        album_name = album_name.strip()
        return album_name

    def try_extract_catalog_number(album_name, brackets):
        # find brackets with a dash and at least 2 digits and 2 letters no
        for bracket in brackets:
            if "-" in bracket and len(bracket) >= 5 and len(bracket) <= 15:
                digits = [c for c in bracket if c.isdigit()]
                letters = [c for c in bracket if c.isalpha()]

                if len(digits) >= 2 and len(letters) >= 2:
                    return bracket
        return ""

    def try_extract_event_number(album_name, brackets):
        other_numerals = {
            "一": 1,
            "二": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
        }
        catalog = Phase02AlbumExtractor.try_extract_catalog_number(album_name, brackets)
        # thing that is not a catalog and contains at least one digit and one letter (unicode included)
        for bracket in brackets:
            if bracket != catalog and len(bracket) >= 5 and len(bracket) <= 15:
                digits = [c for c in bracket if c.isdigit() or c in other_numerals]
                letters = [c for c in bracket if c.isalpha()]

                if len(digits) >= 1 and len(letters) >= 1:
                    return bracket

        return ""

    def remove_auxiliary_info(brackets):
        suff = ["%", "log", "flac", "dvd"]
        brackets = [b for b in brackets if not b.lower().endswith(tuple(suff))]

        return brackets

    def extract_album_info_from_probed_results(self, album):
        keys = {"album", "album_artist", "event", "date"}
        # get all tracks from album
        tracks = get_all_tracks(album)
        aggr_tags = {}
        for track in tracks:
            probe_data = self.probe_result[track]
            tags = probe_data.get("tags", {})
            tags = {k.lower(): v for k, v in tags.items()}
            tags = {k: v for k, v in tags.items() if k in keys}
            for k, v in tags.items():
                if k not in aggr_tags:
                    aggr_tags[k] = []
                aggr_tags[k].append(v)

        result = {}
        for k, v in aggr_tags.items():
            # count frequency of each value in the list, and only keep the most frequent one
            counter = Counter(v)
            result[k] = counter.most_common(1)[0][0]

        return {
            "AlbumName": result.get("album", ""),
            "AlbumArtist": result.get("album_artist", ""),
            "ReleaseDate": result.get("date", ""),
            "CatalogNumber": "",
            "ReleaseConvention": result.get("event", ""),
        }

    def extract_album_info_from_file_path(self, album_path):
        # extract everything between brackets [], {}, or ()
        data = {
            "AlbumName": "",
            "AlbumArtist": "",
            "ReleaseDate": "",
            "CatalogNumber": "",
            "ReleaseConvention": "",
        }
        brackets = []
        dirname = os.path.basename(album_path)
        brackets = extract_bracket_content(dirname)
        brackets = Phase02AlbumExtractor.remove_auxiliary_info(brackets)

        # get circle part of the path. (parent of album dir)
        dirname = os.path.basename(os.path.dirname(album_path))
        artist = CIRCLE_INFO_EXTRACTOR.findall(dirname)
        if len(artist) == 1:
            data["AlbumArtist"] = artist[0]

        if len(brackets) == 0:
            return data

        data["ReleaseDate"] = Phase02AlbumExtractor.try_extract_date(dirname, brackets)
        data["AlbumName"] = Phase02AlbumExtractor.try_extract_album_name(
            dirname, brackets
        )
        data["CatalogNumber"] = Phase02AlbumExtractor.try_extract_catalog_number(
            dirname, brackets
        )
        data["ReleaseConvention"] = Phase02AlbumExtractor.try_extract_event_number(
            dirname, brackets
        )

        return data

    def extract_and_merge_album_info(self, album_struct):
        probed_data = self.extract_album_info_from_probed_results(album_struct)
        path_data = self.extract_album_info_from_file_path(album_struct["AlbumRoot"])

        # merge the two data, prioritize probed data, unless it is ReleaseDate, or AlbumArtist
        for k in probed_data.keys():
            if probed_data[k] == "":
                probed_data[k] = path_data.get(k, "")

        if path_data.get("ReleaseDate", ""):
            probed_data["ReleaseDate"] = path_data["ReleaseDate"]

        if path_data.get("AlbumArtist", ""):
            probed_data["AlbumArtist"] = path_data["AlbumArtist"]

        needs_manual_check = False
        manul_check_reason = []
        if probed_data["AlbumName"] == "":
            needs_manual_check = True
            manul_check_reason.append("AlbumName is empty")

        probed_data["NeedsManualCheck"] = needs_manual_check
        probed_data["NeedsManualCheckReason"] = manul_check_reason

        return probed_data

    def process(self):
        info = {}
        for album in self.phase_1_result:
            album_root = album["AlbumRoot"]
            pi = self.extract_and_merge_album_info(album)
            info[album_root] = pi

        return info


def main():
    phase_1_result = json_load(phase1_output_path)
    probe_result = json_load(probed_results_path)

    album_extractor = Phase02AlbumExtractor(phase_1_result, probe_result)
    result = album_extractor.process()
    json_dump(result, phase2_albuminfo_output_path)

    track_extractor = Phase02TrackExtractor(phase_1_result, probe_result)
    result = track_extractor.process()
    json_dump(result, phase2_trackinfo_output_path)


if __name__ == "__main__":
    main()
