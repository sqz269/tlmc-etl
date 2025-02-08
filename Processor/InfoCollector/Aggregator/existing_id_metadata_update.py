import os
from uuid import uuid4

import Processor.InfoCollector.Aggregator.output.path_definitions as AggregatorPathDef
import Processor.InfoCollector.AlbumInfo.output.path_definitions as AlbumInfoPathDef
import Processor.InfoCollector.ArtistInfo.output.path_definitions as ArtistInfoPathDef
from Shared import json_utils, utils


info_phase3_output = utils.get_output_path(
    AlbumInfoPathDef, AlbumInfoPathDef.INFO_SCANNER_PHASE3_OUTPUT_NAME
)
assigned_merged_output = utils.get_output_path(
    AggregatorPathDef, AggregatorPathDef.ID_ASSIGNED_PATH
)
assigned_metadata_update_output = utils.get_output_path(
    AggregatorPathDef, AggregatorPathDef.ID_MAINTAIN_METADATA_UPDATE_PATH
)

info_phase3 = json_utils.json_load(info_phase3_output)
assigned = json_utils.json_load(assigned_merged_output)
# transform info phase 3 to a dict with AlbumRoot as Key for easy lookup
info_phase3_dict = {entry["AlbumRoot"]: entry for entry in info_phase3}

for existing_assigned in assigned.values():
    album_root = existing_assigned["AlbumRoot"]
    if album_root not in info_phase3_dict:
        print(f"AlbumRoot {album_root} not found in InfoPhase3")
        continue

    album_metadata_fields_to_update = [
        "AlbumName",
        "AlbumArtist",
        "ReleaseDate",
        "CatalogNumber",
        "ReleaseConvention",
    ]

    update_src = info_phase3_dict[album_root]
    # update metadata fields
    for field in album_metadata_fields_to_update:
        existing_assigned["AlbumMetadata"][field] = update_src["AlbumMetadata"][field]


json_utils.json_dump(assigned, assigned_metadata_update_output)
