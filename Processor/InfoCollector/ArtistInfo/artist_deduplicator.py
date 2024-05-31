from collections import defaultdict
import json
import os
import pprint
import re
from typing import Dict, List
import uuid

import Shared.utils as utils
from Processor.InfoCollector.ArtistInfo.output.path_definitions import (
    ARTIST_DISCOVERY_MERGED_ARTISTS_OUTPUT_PATH,
    ARTIST_DISCOVERY_NEW_ARTISTS_OUTPUT_PATH,
    EXISTING_ARTIST_NAME_DUMP_OUTPUT_PATH,
)
from Shared.json_utils import json_dump, json_load

CIRCLE_INFO_EXTRACTOR = re.compile(r"\[(.+)\](.+)?")

output_root = utils.get_file_relative(__file__, "output")

artist_merged_name_dump_output = os.path.join(
    output_root, ARTIST_DISCOVERY_MERGED_ARTISTS_OUTPUT_PATH
)

dedupled = os.path.join(
    output_root, "deduplicated." + ARTIST_DISCOVERY_MERGED_ARTISTS_OUTPUT_PATH
)

def check_and_resolve():
    arists_merged = json_load(artist_merged_name_dump_output)

    # We are going to find duplicates by artists name
    # if there are more than one artist with the same name, we will resolve them

    # detect duplicates
    # the circle dir's raw name, and the list of names that are the same
    # "Liz Triangle" -> ["[Liz Triangle]", "[Liz Triangle] りすとら"]
    name_to_raws: Dict[str, List[str]] = defaultdict(list)
    for raw, struct in arists_merged.items():
        linked = struct.get("linked", None)
        if linked:
            # skip linked entries
            continue

        name = struct["name"]
        name_to_raws[name].append(raw)

    # resolve duplicates
    for name, raws in name_to_raws.items():
        if len(raws) <= 1:
            continue

        print(f"Potential duplicates for {name}")
        for raw in raws:
            pprint.pprint(arists_merged[raw])
            print()

        print("Resolving duplicates")
        perferred_id = None
        for raw in raws:
            struct = arists_merged[raw]
            if not struct.get("new", False):
                perferred_id = struct["known_id"][0]
                break

        if perferred_id is None:
            perferred_id = arists_merged[raws[0]]["known_id"][0]

        for raw in raws:
            arists_merged[raw]["known_id"] = [perferred_id]

    json_dump(arists_merged, dedupled)

def main():
    check_and_resolve()

if __name__ == '__main__':
    main()
