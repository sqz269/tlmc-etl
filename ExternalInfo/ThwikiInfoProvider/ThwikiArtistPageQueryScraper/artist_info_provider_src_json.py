from collections import defaultdict
import os
import re
from typing import List, Set
import uuid

import Shared.utils as utils
from ExternalInfo.ThwikiInfoProvider.ThwikiArtistPageQueryScraper.Model.CircleData import (
    CircleData,
    CircleStatus,
    QueryStatus,
)
import Processor.InfoCollector.ArtistInfo.output.path_definitions as ArtistInfoPathDef
from Shared.json_utils import json_dump, json_load


artist_merged_name_dump_output = utils.get_output_path(
    ArtistInfoPathDef, 
    # ArtistInfoPathDef.ARTIST_DISCOVERY_MERGED_ARTISTS_OUTPUT_PATH
    "deduplicated.artist_scanner.discovery.merged_artists.output.json"
)


def import_data():
    # import data from merged output
    artists_merged = json_load(artist_merged_name_dump_output)
    entry: List[CircleData] = []

    _dbg_keyed_name = defaultdict(list)
    tracking_ids: Set[str] = set()
    for raw, struct in artists_merged.items():
        linked = struct.get("linked", None)
        # Skip circles that are made up of other circles
        if linked:
            continue

        if not struct["known_id"]:
            continue

        id = struct["known_id"][0]
        if id in tracking_ids:
            print(f"Duplicate ID: {id}, {struct['name']}")
            continue

        name = struct["name"]
        _dbg_keyed_name[name].append(id)
        tracking_ids.add(id)

        entry.append(
            CircleData(
                circle_remote_id=id,
                circle_name=name,
                circle_query_status=QueryStatus.PENDING,
            )
        )

    BULK_SIZE = 2000
    for i in range(0, len(entry), BULK_SIZE):
        print(f"Inserting {i} to {i + BULK_SIZE}")
        CircleData.bulk_create(entry[i : i + BULK_SIZE], batch_size=BULK_SIZE)

def main():
    if not os.path.exists(artist_merged_name_dump_output):
        print("Merged artist dump not found, follow the steps in the README to generate it")
        return
    
    if CircleData.select().count() == 0:
        print("Importing data")
        import_data()

    print("Done")

if __name__ == '__main__':
    main()
