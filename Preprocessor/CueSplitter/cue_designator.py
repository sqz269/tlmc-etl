import json
import os
from uuid import uuid4

from pythonnet import load, set_runtime

import Shared.cache_utils as cache_utils
from Shared.json_utils import json_dump
from Shared.utils import (
    check_cuesheet_attr,
    get_cuesheet_attr,
    get_file_relative,
    max_common_prefix,
    recurse_search,
)

set_runtime("coreclr")
load("coreclr")

import sys

import clr

# TODO: NEED TO FIX SUCH THAT RESTUCTURED DIRECTORY STRUCTURE IS UPDATED
# COMMENT STEPS.MD: PREPROCESSING -> SECTION 3 -> EXECUTION -> 2 REVIEW
# "There's no need to manually update `potential.json` after reorganizing the directories."
# THERE IS NO CODE CURRENTLY HANDLING THIS. THE ONLY THING THAT MAKING IT WORK IS
# OUR GUESSED AUDIO PATH IN DESIGNATOR IS CORRECT.

# find CueSplitInfoProvider.dll
cue_info_provider_path = recurse_search(os.getcwd(), "CueSplitInfoProvider.dll")
utf_unknown_path = recurse_search(os.getcwd(), "UtfUnknown.dll")

if cue_info_provider_path is None:
    print("CueSplitInfoProvider.dll not found. Compile CueSplitter project first.")
    exit(1)

if utf_unknown_path is None:
    print("UtfUnknown.dll not found. Compile CueSplitter project first.")
    exit(1)

print("Found CueSplitInfoProvider.dll at " + cue_info_provider_path)
print("Found UtfUnknown.dll at " + utf_unknown_path)

# sys.path.append(os.path.dirname(cue_info_provider_path))

# add reference to CueSplitInfoProvider.dll
print("Loading DLL and Directory Context from " + cue_info_provider_path)
clr.AddReference(cue_info_provider_path)
clr.AddReference(utf_unknown_path)
print("DLL loaded.")

from Preprocessor.CueSplitter.output.path_definitions import (
    CUE_DESIGNATER_OUTPUT_NAME,
    CUE_DESIGNATER_USER_PAIR_CACHE_NAME,
    CUE_SCANNER_OUTPUT_NAME,
    CUE_SPLIT_PLAN_OUTPUT_NAME,
)

output_root = get_file_relative(__file__, "output")
input_potential = os.path.join(output_root, CUE_SCANNER_OUTPUT_NAME)
input_split_plan = os.path.join(output_root, CUE_SPLIT_PLAN_OUTPUT_NAME)
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
        response = input("Do you want to use the cached pairs? [Y/n] ") or "y"
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
    # A cue's FILE reference is relative to the cue's OWN directory, not the
    # album root. Multi-disc rips keep each cue beside its image in a "Disc N/"
    # subdirectory, and passing the album root there resolved FILE against the
    # wrong directory: the profile came back Invalid with a non-existent
    # AudioFilePath, and the tracks would have been written to the album root
    # instead of alongside their disc.
    result = CueSplit.SplitCue(os.path.dirname(cue_path) or root, cue_path)
    result = json.loads(result)
    return result


def gen_full_profile_from_cue(flac_file, cuesheet):
    """
    :param flac_file: path to flac file
    :param cuesheet: cuesheet string NOT path
    """
    result = CueSplit.SplitCueWithEmbedCueSheet(flac_file, cuesheet)
    result = json.loads(result)
    return result


def rescan_and_probe(potential: dict) -> dict:
    # find all cue and audio files in a directory
    root = potential["root"]
    cues = []
    audio = []
    for rt, dirs, files in os.walk(root):
        for file in files:
            if file.lower().endswith(".cue"):
                cues.append(os.path.join(rt, file))
            elif file.lower().endswith(TARGET_TYPES):
                audio.append(os.path.join(rt, file))

    # flac with cuesheet attribute
    cuesheet_attr = []
    for file in audio:
        if check_cuesheet_attr(file):
            cuesheet_attr.append(file)

    profiles = []
    if len(cuesheet_attr) >= len(cues):
        for file in cuesheet_attr:
            print(f"Designating using embedded cue sheet {file}")
            cuesheet = get_cuesheet_attr(file)
            profile = gen_full_profile_from_cue(file, cuesheet)
            profiles.append(profile)

        return profiles

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
        target_pairs = manual_designate(root, cues, audio)

    for pair in target_pairs:
        print(f"Designating {pair[0]} and {pair[1]}")
        profile = gen_full_profile(root, pair[0])
        profiles.append(profile)

    return profiles


def load_split_plan():
    """
    Roots the cue analysis decided actually need splitting.

    Returns None when no plan is present, in which case every scanner hit is
    designated (the original behaviour). Set CUE_SPLIT_PLAN to point at a subset
    of the plan, which is how a trial run is scoped.
    """
    path = os.environ.get("CUE_SPLIT_PLAN", input_split_plan)
    if not os.path.isfile(path):
        return None

    with open(path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    return {
        entry["root"]
        for entry in plan
        if str(entry.get("verdict", "")).startswith("SPLIT")
    }


def main():
    with open(input_potential, "r") as f:
        potential = json.load(f)

    split_roots = load_split_plan()
    if split_roots is None:
        print(f"No split plan at {input_split_plan}; designating every scanner hit.")
        print("This includes albums that are already split. Review before running")
        print("the splitter, which deletes the source audio it splits from.")
    else:
        before = len(potential)
        potential = [t for t in potential if t["root"] in split_roots]
        print(f"Split plan: {len(potential)} of {before} scanner hits need splitting")

    profiles = {}
    for idx, target in enumerate(potential):
        print(f"[{idx + 1}/{len(potential)}] Generating Full Profile " + target["root"])
        try:
            profilez = rescan_and_probe(target)
        except Exception as e:
            # One unparseable album should not lose the whole designation run.
            print(f"  FAILED to designate {target['root']}: {e}")
            continue

        for profile in profilez:
            id = str(uuid4())
            profile["id"] = id
            profiles[id] = profile

    json_dump(profiles, output_designated)
    print(f"\nWrote {len(profiles)} profiles to {output_designated}")


if __name__ == "__main__":
    if not os.path.exists(input_potential):
        print(f"Input file {input_potential} does not exist.")
        exit(1)

    main()
