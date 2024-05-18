import inspect
from itertools import count
import json
import os
import sys
import time
from typing import List, Tuple
import unicodedata

import httpx

from InfoProviders.BasicInfoProvider.Model.BasicInfoModel import (
    BasicAlbum, BasicTrack)
from InfoProviders.ThcInfoProvider.ThcQueryProvider.Model.QueryModel import (
    QueryData, QueryDataDb, QueryStatus)

def import_data():
    print("Importing data from Basic Info Provider Databse...")

    init_data = []
    for album in BasicAlbum.select():
        query_data_init = {
            "album_id": album.album_id,
            "album_name": album.album_name,
            "query_result": None,
            "query_exact_result": None,
            "query_status": QueryStatus.PENDING
        }

        query_data = QueryData(**query_data_init)
        init_data.append(query_data)
        print(f"Fetching album: {album.album_id}", end="\r")
    
    print("\nFetch complete")

    print("Saving data to Query Data Database...")
    BATCH_SIZE = 2000
    for i in range(0, len(init_data), BATCH_SIZE):
        print(f"Saving Query Data {i + BATCH_SIZE}/{len(init_data)}", end="\r")
        QueryData.bulk_create(init_data[i:i+BATCH_SIZE])
    print("\nImport complete")

def import_diff():
    pass

def query_thc(album_name):
    HEADER = {
        'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="102", "Google Chrome";v="102"',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Referer': 'https://thwiki.cc/',
        'X-Requested-With': 'XMLHttpRequest',
        'sec-ch-ua-mobile': '?0',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36',
        'sec-ch-ua-platform': '"Windows"',
    }

    params = {
        'action': 'opensearch',
        'format': 'json',
        'formatversion': '2',
        'redirects': 'display',
        'search': f'{album_name}',
        'namespace': '0|4|12|102|108|506|508|512',
        'limit': '12',
    }

    response = httpx.get('https://thwiki.cc/api.php', params=params, headers=HEADER)
    search = json.loads(response.text)
    results = {
        "query": search[0],
        "results": {kw.lower(): (link, desc) for kw, link, desc in zip(search[1], search[3], search[2])}
    }
    return results

def remove_non_content_letters(text):
    normalized = unicodedata.normalize('NFKD', text)
    for char in normalized:
        if not unicodedata.category(char).startswith('L'):
            normalized = normalized.replace(char, '')
    return normalized

def get_result_value_and_status(query, results) -> Tuple[str, List[str]]:
    sani_query = remove_non_content_letters(query).lower()

    sani_result = {}
    for k, (link, desc) in results.items():
        if not ("同人") in desc:
            continue
        sani_result[remove_non_content_letters(k).lower()] = (link, desc)

    if len(sani_result) == 0:
        return (QueryStatus.NO_RESULT, [])

    if len(sani_result) == 1:
        if (sani_result.get(sani_query)):
            return (QueryStatus.RESULT_ONE_EXACT, sani_result.get(sani_query))
        if ("同人" in list(sani_result.values())[0][1]):
            return (QueryStatus.RESULT_ONE_SUS, list(sani_result.values())[0])
        return (QueryStatus.RESULT_ONE_AMBIGUOUS, [])

    if (r := sani_result.get(sani_query)):
        return (QueryStatus.RESULT_MANY_EXACT, r)

    return (QueryStatus.RESULT_MANY_AMBIGUOUS, [])

def process_data():
    total_unprocessed = QueryData.select().where(QueryData.query_status == QueryStatus.PENDING).count()

    for idx, album in enumerate(QueryData.select().where(QueryData.query_status == QueryStatus.PENDING)):
        try:
            print(f"[{idx + 1}/{total_unprocessed}] Processing album: {album.album_id}")
            result = query_thc(album.album_name)
            album.query_result = json.dumps(result)
            if (not result['results']):
                print("Processing complete: NO_RESULT")
                album.query_status = QueryStatus.NO_RESULT
                album.save()
                time.sleep(1.5)
                continue
            
            status, result = get_result_value_and_status(result["query"], result["results"])
            album.query_status = status
            if (status == QueryStatus.RESULT_ONE_EXACT or 
                status == QueryStatus.RESULT_MANY_EXACT or 
                status == QueryStatus.RESULT_ONE_SUS):
                album.query_exact_result = json.dumps(result)
            print(f"Process Complete: {status}")
            album.save()
            time.sleep(0.5)
        except Exception as e:
            print("Error: ", e)
            continue

def quick_reprocess():
    total = QueryData.select().count()
    updated = 0
    for idx, album in enumerate(QueryData.select()):
        try:
            print(f"[{idx + 1}/{total} | {updated}] Processing album: {album.album_id}")
            result = json.loads(album.query_result)
            # print(result)
            if (not result['results']):
                # print("Processing complete: NO_RESULT")
                if (album.query_status != QueryStatus.NO_RESULT):
                    album.query_status = QueryStatus.NO_RESULT
                    album.save()
                    updated += 1
                continue
            
            status, result = get_result_value_and_status(result["query"], result["results"])
            # print(f"Process Complete: {status} | {result}")
            if (status == QueryStatus.RESULT_ONE_EXACT or 
                status == QueryStatus.RESULT_MANY_EXACT or 
                status == QueryStatus.RESULT_ONE_SUS):
                album.query_exact_result = json.dumps(result)

            if (album.query_status != status):
                album.query_status = status
                album.save()
                updated += 1
            album.save()
        except Exception as e:
            print("Error: ", e)
            continue

def import_updated():
    album: BasicAlbum
    init_data = []
    curr = 0
    exist = 0
    new = 0
    for album in BasicAlbum.select():
        query_data_init = {
            "album_id": album.album_id,
            "album_name": album.album_name,
            "query_result": None,
            "query_exact_result": None,
            "query_status": QueryStatus.PENDING
        }

        existing_query: QueryData
        existing_query = QueryData.select().where(QueryData.album_name == album.album_name).get_or_none()
        if (existing_query):
            query_data_init['query_result'] = existing_query.query_result
            query_data_init['query_exact_result'] = existing_query.query_exact_result
            query_data_init['query_status'] = existing_query.query_status
            exist += 1
        else:
            new += 1

        curr += 1

        query_data = QueryData(**query_data_init)
        init_data.append(query_data)
        print(f"[{curr}] Updating: {album.album_id} (New: {new} | Exist: {exist})", end="\r")
    
    print("\nUpdate complete")

    # need to drop the table first
    print("Dropping Query Data table...")
    QueryData.drop_table()
    print("Creating Query Data table...")
    QueryData.create_table()

    BATCH_SIZE = 2000
    for i in range(0, len(init_data), BATCH_SIZE):
        print(f"Saving Query Data {i + BATCH_SIZE}/{len(init_data)}", end="\r")
        QueryData.bulk_create(init_data[i:i+BATCH_SIZE])

    print("\nImport Diff Complete")

if (__name__ == '__main__'):
    if not QueryData.select().exists():
        import_data()
    else:
        print("Query Data already exists")
        print("Existing Query Data count: ", QueryData.select().count())
        print("Existing Basic Album count: ", BasicAlbum.select().count())
        if (QueryData.select().count() != BasicAlbum.select().count()):
            import_updated()
            # re ensure that the data is the same
            recheck = input("Recheck? (y/n)")

            if (recheck == "y"):
                mc = QueryData.select().count()
                c = 0
                for album in BasicAlbum.select():
                    existing_query: QueryData
                    existing_query = QueryData.select().where(QueryData.album_name == album.album_name).get()
                    c += 1
                    print(f"[{c}/{mc}] Checking: {album.album_id}", end="\r")
                    a = existing_query.album_id
                    if (not existing_query):
                        print(f"\nMissing: {album.album_name} ({album.album_id})")
            
            reprocess = input("Reprocess? (y/n)")
            if (reprocess == "y"):
                quick_reprocess()
                exit(0)

    process_data()
