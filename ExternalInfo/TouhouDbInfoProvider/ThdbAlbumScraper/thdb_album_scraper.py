import json
from touhoudb_api_client.api.album_api_api import AlbumApiApi
from touhoudb_api_client.api_client import ApiClient

import Processor.InfoCollector.Aggregator.output.path_definitions as MergedOutput
from ExternalInfo.TouhouDbInfoProvider.ThdbAlbumScraper.model.QueryModel import QueryData, QueryStatus
from Shared import utils

merged_output_path = utils.get_output_path(MergedOutput, MergedOutput.ID_ASSIGNED_PATH)


def import_data_from_json(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    total_entry = len(data)
    if QueryData.select().count() == total_entry:
        print("Data already imported")
        return

    print("Importing data from JSON...")
    # Clear existing data
    QueryData.delete().execute()

    init_data = []
    for id, entry in data.items():
        album_info = entry["AlbumMetadata"]

        alb_id = album_info["AlbumId"]

        q_data_init = {
            "album_id": alb_id,
            "album_name": album_info["AlbumName"],
            "query_result": None,
            "query_exact_result": None,
            "query_status": QueryStatus.PENDING,
        }

        q_data = QueryData(**q_data_init)
        init_data.append(q_data)

    print("Saving data to Query Data Database...")
    BATCH_SIZE = 2000
    for i in range(0, len(init_data), BATCH_SIZE):
        print(f"Saving Query Data {i + BATCH_SIZE}/{len(init_data)}", end="\r")
        QueryData.bulk_create(init_data[i : i + BATCH_SIZE])
    print("\nImport complete")
    

def process_data():
    total_unprocessed = QueryData.select().where(QueryData.query_status == QueryStatus.PENDING).count()
    if total_unprocessed == 0:
        print("No unprocessed data")
        return
    
    for idx, data in enumerate(QueryData.select().where(QueryData.query_status == QueryStatus.PENDING)):
        print(f"Processing {idx + 1}/{total_unprocessed}", end="\r")
        album_id = data.album_id
        album_name = data.album_name

        api_instance = AlbumApiApi(ApiClient())
        try:
            api_response = api_instance.album_api_get_album_by_id(album_id)
            data.query_result = api_response
            data.query_status = QueryStatus.SUCCESS
        except Exception as e:
            data.query_status = QueryStatus.FAILED
            print(f"Failed to process {album_id} {album_name}")
            print(e)
        data.save()

def main():
    import_data_from_json(merged_output_path)

if __name__ == '__main__':
    main()
