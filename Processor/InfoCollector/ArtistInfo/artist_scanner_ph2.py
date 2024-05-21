import os
import re

import Shared.utils as utils
from Processor.InfoCollector.ArtistInfo.output.path_definitions import (
    ARTIST_DISCOVERY_NEW_ARTISTS_OUTPUT_PATH,
    EXISTING_ARTIST_NAME_DUMP_OUTPUT_PATH,
)
from Shared.json_utils import json_dump, json_load

output_root = utils.get_file_relative(__file__, "output")
os.makedirs(output_root, exist_ok=True)
artist_existing_name_dump_output = os.path.join(
    output_root, EXISTING_ARTIST_NAME_DUMP_OUTPUT_PATH
)
artist_new_name_dump_output = os.path.join(
    output_root, ARTIST_DISCOVERY_NEW_ARTISTS_OUTPUT_PATH
)

CIRCLE_INFO_EXTRACTOR = re.compile(r"\[(.+)\](.+)?")


def main():
    tlmc_root = input("Enter the root directory of the TLMC: ")
    artist_list = []
    for dir in os.listdir(tlmc_root):
        if not os.path.isdir(os.path.join(tlmc_root, dir)):
            continue

        artist_list.append(dir)

    circles = []
    for entry in artist_list:
        circle_data = CIRCLE_INFO_EXTRACTOR.match(entry)
        if not circle_data:
            print(f"Failed to parse {entry} Using complete entry as name.")
            name = entry
            alias = ""

            circle_json = {
                "raw": entry,
                "name": name,
                "alias": [] if not alias else [alias.strip()],
                "linked": [],
            }
            circles.append(circle_json)

            continue
        name = circle_data.group(1)
        alias = circle_data.group(2)

        circle_json = {
            "raw": entry,
            "name": name,
            "alias": [] if not alias else [alias.strip()],
            "linked": [],
        }
        circles.append(circle_json)

    new_names = {}
    if os.path.exists(artist_existing_name_dump_output):
        print("Loading existing names...")
        existing_names = json_load(artist_existing_name_dump_output)
        # make sure all existing names key are lowercase
        existing_names = {k.lower(): v for k, v in existing_names.items()}
        matched = 0
        for circle in circles:
            raw_lower = circle["raw"].lower()
            if raw_lower in existing_names:
                print(f"Matched {raw_lower}. Ids: {existing_names[raw_lower]}")
                circle["known_id"] = existing_names[raw_lower]
                matched += 1
            else:
                new_names[raw_lower] = circle
                new_names[raw_lower]["known_id"] = []

        print(f"Matched {matched} names out of {len(circles)} circles")
    else:
        new_names = {circle["raw"].lower(): circle for circle in circles}
    json_dump(new_names, artist_new_name_dump_output)


if __name__ == "__main__":
    main()
