from collections import defaultdict
import os
import re
from typing import List, Optional, Set, Tuple
import uuid
import time

import Shared.utils as utils
from ExternalInfo.ThwikiInfoProvider.ThwikiArtistPageQueryScraper.Model.CircleData import (
    CircleData,
    CircleStatus,
    QueryStatus,
)
from ExternalInfo.ThwikiInfoProvider.Shared import ThwikiUtils
import Processor.InfoCollector.ArtistInfo.output.path_definitions as ArtistInfoPathDef
import ExternalInfo.ThwikiInfoProvider.cache.path_definitions as CachePathDef
from Shared.json_utils import json_dump, json_load


artist_merged_name_dump_output = utils.get_output_path(
    ArtistInfoPathDef, 
    # ArtistInfoPathDef.ARTIST_DISCOVERY_MERGED_ARTISTS_OUTPUT_PATH
    "deduplicated.artist_scanner.discovery.merged_artists.output.json"
)

artist_info_query_cache_path = utils.get_output_path(
    CachePathDef, 
    CachePathDef.THWIKI_ARTIST_INFO_QUREY_CACHE_DIR
)

artist_info_page_cache_path = utils.get_output_path(
    CachePathDef, 
    CachePathDef.THWIKI_ARTIST_INFO_WIKI_PAGE_CACHE_DIR
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


def process_query():
    def find_match(query_results) -> Tuple[QueryStatus, Optional[str]]:
        kw = "同人社团"
        results = query_results["results"]
        if not results:
            return (QueryStatus.QUERY_NO_RESULTS, None)

        for title, (url, desc) in results.items():
            if kw in desc.lower():
                return (QueryStatus.QUERY_RESULT_FOUND, url)
            
        return (QueryStatus.QUERY_NO_RESULTS, None)


    circle: CircleData
    for idx, circle in enumerate(CircleData.select().where(CircleData.circle_query_status == QueryStatus.PENDING)):
        result = ThwikiUtils.query_keywords(
            circle.circle_name, 
            "thwiki_artist_info_query_cache", 
            artist_info_query_cache_path
        )
        query_status, circle_url = find_match(result)
        if query_status != QueryStatus.QUERY_RESULT_FOUND:
            print(f"Failed to find {circle.circle_name}")
            circle.circle_query_status = query_status
            circle.save()
            continue

        print(f"Found {circle.circle_name} at {circle_url}")
        circle.circle_query_status = query_status
        circle.circle_wiki_url = circle_url
        circle.save()
        print(f"Found {circle.circle_name} at {circle_url}")


def process_page():
    circle: CircleData
    for idx, circle in enumerate(CircleData.select().where(CircleData.circle_query_status == QueryStatus.QUERY_RESULT_FOUND)):
        st = time.time()
        result = ThwikiUtils.get_thwiki_page_content_after_redirects(
            ThwikiUtils.extract_title_from_url(circle.circle_wiki_url), 
            "thwiki_artist1_info_cache", 
            artist_info_page_cache_path
        )
        if not result:
            print(f"Failed to find {circle.circle_name}")
            continue
        dt = time.time() - st
        print(f"Got page content for {circle.circle_name} in {dt:.2f}s")


def main():
    if not os.path.exists(artist_merged_name_dump_output):
        print("Merged artist dump not found, follow the steps in the README to generate it")
        return
    
    if CircleData.select().count() == 0:
        print("Importing data")
        import_data()

    # process_query()
    process_page()

    print("Done")

if __name__ == '__main__':
    main()
