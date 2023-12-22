import os
import json
from pythonnet import load, set_runtime
from Shared.utils import (
    recurse_search,
    check_cuesheet_attr,
    max_common_prefix,
    get_file_relative,
)
import Shared.cache_utils as cache_utils
from Shared.json_utils import json_dump

set_runtime("coreclr")
load("coreclr")

import clr
import sys

# find CueSplitInfoProvider.dll
cue_info_provider_path = recurse_search(os.getcwd(), "CueSplitInfoProvider.dll")
utf_unknown_path = recurse_search(os.getcwd(), "UtfUnknown.dll")
print("Found CueSplitInfoProvider.dll at " + cue_info_provider_path)
print("Found UtfUnknown.dll at " + utf_unknown_path)

# sys.path.append(os.path.dirname(cue_info_provider_path))

# add reference to CueSplitInfoProvider.dll
print("Loading DLL and Directory Context from " + cue_info_provider_path)
clr.AddReference(cue_info_provider_path)
clr.AddReference(utf_unknown_path)
print("DLL loaded.")

from Preprocessor.CueSplitter.output.path_definitions import (
    CUE_SCANNER_OUTPUT_NAME,
    CUE_DESIGNATER_OUTPUT_NAME,
    CUE_DESIGNATER_USER_PAIR_CACHE_NAME,
)

output_root = get_file_relative(__file__, "output")
input_potential = os.path.join(output_root, CUE_SCANNER_OUTPUT_NAME)
output_designated = os.path.join(output_root, CUE_DESIGNATER_OUTPUT_NAME)
cache_designated = os.path.join(output_root, CUE_DESIGNATER_USER_PAIR_CACHE_NAME)

from CueSplitter import CueSplit
from System.IO import *

TARGET_TYPES = (
    ".flac",
    ".wav",
    ".mp3",
)


def manual_designate(root, cues, audios):
    print("Manual designation required.")
    print("Cuesheets:")
    for idx, cue in enumerate(cues):
        print(f"[{idx}] {cue}")
    print("Audio files:")
    for idx, audio in enumerate(audios):
        print(f"[{idx}] {audio}")
    print('Enter pairs in the format of "cue_idx audio_idx"')
    print('Enter "done" to finish.')
    print("Your response will be cached")

    pairs = []
    if cache_utils.check_cache(root, cache_designated):
        pairs = cache_utils.load_cache(root, cache_designated)
        print("Cache found.")
        print("Cached pairs:")
        for idx, pair in enumerate(pairs):
            print(f"[{idx}] {pair[0]} {pair[1]}")
        response = input("Do you want to use the cached pairs? [y/n] ")
        if response == "y":
            return pairs
        else:
            pairs = []

    while True:
        response = input("Enter pair: ")
        if response == "done":
            break
        try:
            cue_idx, audio_idx = response.split(" ")
            cue_idx = int(cue_idx)
            audio_idx = int(audio_idx)
            pairs.append((cues[cue_idx], audios[audio_idx]))
        except Exception as e:
            print(f"Invalid input: {str(e)}")
            continue

    cache_utils.store_cache(root, pairs, cache_designated)
    return pairs


def gen_full_profile(root, cue_path):
    result = CueSplit.SplitCue(root, cue_path)
    result = json.loads(result)
    return result


def rescan_and_probe(potential: dict) -> dict:
    # find all cue and audio files in a directory
    root = potential["root"]
    cues = []
    audio = []
    for root, dirs, files in os.walk(root):
        for file in files:
            if file.lower().endswith(".cue"):
                cues.append(os.path.join(root, file))
            elif file.lower().endswith(TARGET_TYPES):
                audio.append(os.path.join(root, file))

    # flac with cuesheet attribute
    cuesheet_attr = []
    for file in audio:
        if check_cuesheet_attr(file):
            cuesheet_attr.append(file)

    # if there are # of cuesheets = # of flac with cuesheet attribute
    # then designate the pairs with longest common prefix as a target
    target_pairs = None
    if len(cues) == len(cuesheet_attr):
        print("Automatically designating cuesheet and audio pairs.")
        target_pairs = max_common_prefix(cues, cuesheet_attr)
        print("Pairs:")
        for idx, pair in enumerate(target_pairs):
            print(f"[{idx}] {pair[0]} {pair[1]}")
    else:
        print("Number of cuesheets and flac with cuesheet attribute does not match.")
        print("Manually designate cuesheet and audio pairs required.")
        target_pairs = manual_designate(root, cues, cuesheet_attr)

    profiles = []
    for pair in target_pairs:
        print(f"Designating {pair[0]} and {pair[1]}")
        profile = gen_full_profile(root, pair[0])
        profiles.append(profile)

    return profiles


def main():
    with open(input_potential, "r") as f:
        potential = json.load(f)

    profiles = []
    for target in potential:
        print("Generating Full Profile " + target["root"])
        profile = rescan_and_probe(target)
        profiles.append(profile)

    json_dump(profiles, output_designated)


if __name__ == "__main__":
    if not os.path.exists(input_potential):
        print(f"Input file {input_potential} does not exist.")
        exit(1)

    main()
