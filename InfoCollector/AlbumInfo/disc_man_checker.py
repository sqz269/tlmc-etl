from pprint import pprint
import re
import os
from typing import Dict, List, Tuple

import Shared.utils as utils
from Shared.json_utils import json_dump, json_load
import Shared.cache_utils as cache
from InfoCollector.AlbumInfo.output.path_definitions import (
    DISC_SCANNER_OUTPUT_NAME,
    DISC_MANUAL_CHECKER_OUTPUT_NAME,
)

output_root = utils.get_file_relative(__file__, "output")
os.makedirs(output_root, exist_ok=True)
scanned_output_file = os.path.join(output_root, DISC_SCANNER_OUTPUT_NAME)
disc_man_cached_file = os.path.join(output_root, "man_verf.cached.output.json")
disc_man_output_file = os.path.join(output_root, DISC_MANUAL_CHECKER_OUTPUT_NAME)


ACCEPTED_AUDIO_FILE_EXTENSIONS = (".flac", ".mp3", ".wav", ".wv")
INTEGER_EXTRACTOR = re.compile(r"(\d+)")


def manual_group(path):
    audio_files = []
    for file in os.listdir(path):
        file_path = os.path.join(path, file)
        if os.path.isfile(file_path):
            if file.endswith(ACCEPTED_AUDIO_FILE_EXTENSIONS):
                audio_files.append(file)

    audio_files.sort()

    for idx, name in enumerate(audio_files):
        print(f"[{idx}]", name)

    def ask_is_disc() -> bool:
        while True:
            is_disc = input("Does this album contain multiple discs? [y/n]: ")
            if is_disc.lower() == "y":
                return True
            elif is_disc.lower() == "n":
                return False
            else:
                print("Invalid input")

    is_disc = ask_is_disc()

    def ask_disc_assignment(audio_files):
        print("Please assign disc number to each file.")
        print("You can use spaces to separate file indexes.")
        print("And use '-' to indicate a range of file indexes.")
        print("For example: 1 2 3-5 6")

        def parse_input() -> List[int]:
            def _parse_input(input: str) -> List[int]:
                result = []
                for part in input.split(" "):
                    if "-" in part:
                        start, end = part.split("-")

                        interop = range(int(start), int(end) + 1)
                        result.extend(interop)
                    else:
                        result.append(int(part))
                return result

            while True:
                assignment = input("Assignment: ")
                try:
                    result = _parse_input(assignment)
                    if not result:
                        print("Invalid input")
                    else:
                        return result
                except Exception as e:
                    print("Invalid input")

        disc_index = 1
        disc_assignments = {}
        while len(audio_files) != 0:
            print(f"Assign tracks for Disc {disc_index}")
            print("Remaining tracks:")
            for idx, name in enumerate(audio_files):
                print(f"[{idx}]", name)
            disc_assignment = parse_input()
            paths = [audio_files[i] for i in disc_assignment]
            disc_assignments[disc_index] = paths

            for path in paths:
                audio_files.remove(path)

            disc_index += 1
        return disc_assignments

    if is_disc:
        return ask_disc_assignment(audio_files)
    else:
        return {}


def man_verf(album_path):
    while True:
        result = manual_group(album_path)
        print("Assignment Result:")
        pprint(result)
        confirm = input("Confirm? [Y/n]: ") or "y"
        if confirm.lower() == "y":
            return result

        print("Assignment not confirmed, please try again")


def finalize_format(disc_dirs: Dict[str, List[str]]):
    full_struct = {}
    for path, disc_dir in disc_dirs.items():
        full_struct[path] = []
        for disc in disc_dir:
            disc_index = INTEGER_EXTRACTOR.search(os.path.basename(disc))

            if disc == path:
                disc_index = 1
            elif disc_index:
                disc_index = int(disc_index.group(1))
            else:
                disc_index = -1

            full_struct[path].append(
                {"path": disc, "disc_number": disc_index, "disc_name": ""}
            )

    return full_struct


def main():
    potential_list = json_load(scanned_output_file)
    single_items = []
    multi_items = {}
    for path, disc_dirs in potential_list.items():
        if len(disc_dirs) == 1:
            single_items.append((path, disc_dirs))
        else:
            multi_items[path] = disc_dirs

    all_results = {}
    for idx, (path, _) in enumerate(single_items):
        result = None
        if cache.check_cache(path, disc_man_cached_file):
            print("Loading from cache for ", path)
            result = cache.load_cache(path, disc_man_cached_file)
        else:
            print(f"Processing {idx}/{len(single_items)}: ", path)
            result = man_verf(path)
            cache.store_cache(path, result, disc_man_cached_file)
        if not result:
            continue
        all_results[path] = result

    print("All ambiguous albums are tagged")
    input("Press enter to automatically reorganize the discs into directories")

    updated_paths = {}
    for path, result in all_results.items():
        for disc_index, disc_assignment in result.items():
            disc_path = os.path.join(path, f"Disc {disc_index}")
            print("Creating disc directory for ", disc_path)
            os.makedirs(disc_path, exist_ok=True)

            if path not in updated_paths:
                updated_paths[path] = [disc_path]
            else:
                updated_paths[path].append(disc_path)

            for file in disc_assignment:
                file_path = os.path.join(path, file)
                print("\tMoving ", file_path, " to ", disc_path)
                # os.rename(file_path, os.path.join(disc_path, file))

    print("Reorganization complete. Generating output")
    multi_items.update(updated_paths)

    final_result = finalize_format(multi_items)

    json_dump(final_result, disc_man_output_file)


if __name__ == "__main__":
    main()
