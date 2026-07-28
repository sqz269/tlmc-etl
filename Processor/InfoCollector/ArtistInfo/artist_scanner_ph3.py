import os
import re
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
os.makedirs(output_root, exist_ok=True)
artist_existing_name_dump_output = os.path.join(
    output_root, EXISTING_ARTIST_NAME_DUMP_OUTPUT_PATH
)
artist_new_name_dump_output = os.path.join(
    output_root, ARTIST_DISCOVERY_NEW_ARTISTS_OUTPUT_PATH
)
artist_merged_name_dump_output = os.path.join(
    output_root, ARTIST_DISCOVERY_MERGED_ARTISTS_OUTPUT_PATH
)


def main():
    artist_existing = {}
    if os.path.exists(artist_existing_name_dump_output):
        print("Loading existing artist dump")
        artist_existing = json_load(artist_existing_name_dump_output)
    else:
        artist_existing = {}
    artist_new = json_load(artist_new_name_dump_output)

    artist_aggr = {}

    artist_existing = {k.lower(): v for k, v in artist_existing.items()}
    print("Assigning id to new standalone entries")
    for raw, struct in artist_new.items():
        if struct["linked"]:
            continue

        struct["known_id"] = [str(uuid.uuid4())]
        struct["new"] = True
        artist_aggr[raw] = struct

    print("Assigning id to new linked entries")
    for raw, struct in artist_new.items():
        if not struct["linked"]:
            continue

        linked_ids = []
        for linked in struct["linked"]:
            linked_lower = linked.lower()
            if linked_lower in artist_existing:
                print(
                    f"\t\tFound {linked_lower} in existing. Using that id instead of creating new"
                )
                linked_ids.extend(artist_existing[linked_lower])
            elif linked_lower in artist_aggr:
                print(
                    f"\t\tFound {linked_lower} in new standalone. Using that id instead of creating new"
                )
                linked_ids.extend(artist_aggr[linked_lower]["known_id"])
            else:
                print(
                    f"[REVIEW] Failed to find {linked_lower} in existing or new standalone. Creating new id"
                )
                new_uuid = str(uuid.uuid4())
                # Keyed lowercase, like every other entry. artist_scanner_ph2
                # keys on raw.lower() and id_assign_and_merge looks up
                # album_artist.lower(), so a raw-cased key here is unreachable:
                # 40 of them on this release. Harmless only while these circles
                # have no releases of their own -- the moment one does, the
                # lookup either raises or mints a second circle for it.
                parsed = CIRCLE_INFO_EXTRACTOR.match(linked)
                name = parsed.group(1) if parsed else linked
                alias = parsed.group(2) if parsed else None
                artist_aggr[linked.lower()] = {
                    "raw": linked,
                    "name": name,
                    # A list, matching phase 2. group(2) is a string, and
                    # `or []` only substitutes when it is empty -- so a
                    # collaborator written "[Name] Alias" produced a bare
                    # string where every other entry has a list.
                    "alias": [alias.strip()] if alias and alias.strip() else [],
                    "known_id": [new_uuid],
                    "new": True,
                }

                linked_ids.append(new_uuid)

        struct["known_id"] = linked_ids
        struct["new"] = True
        artist_aggr[raw] = struct

    print("Restoring existing entries")
    for raw, struct in artist_existing.items():
        if raw in artist_aggr:
            print(f"Found existing {raw} in new standalone. Skipping")
            continue

        artist_aggr[raw] = {
            "raw": raw,
            "name": "",
            "alias": "",
            "known_id": struct,
            "new": False,
        }

    print("Dumping output")
    json_dump(artist_aggr, artist_merged_name_dump_output)


if __name__ == "__main__":
    main()
