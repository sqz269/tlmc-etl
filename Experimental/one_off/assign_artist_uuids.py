import os
import sys
from pathlib import Path
# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import uuid
import torch
from tqdm import tqdm
import umap
import numpy as np
import pandas as pd
import plotly.express as px
from typing import Dict, List, Literal

from utils import utils
from utils.utils import load_tensor

TENSOR_DIRECTORY = "embeddings/chunks_30s_ars"
OUTPUT_DIRECTORY = "embeddings/uuid_embeddings/test_embeddings"
POOLING_POLICY: List[Literal["mean", "max", "mean+max"]] = ["mean", "mean+max"]

METADATA_CSV_FILE = "embeddings/id_metadata.csv"

def main():
  tensors = load_tensor(TENSOR_DIRECTORY)
  if not tensors:
    print("No .pt files found in the directory. Exiting.")
    return
  
  os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)
  
  metadata_df = pd.read_csv(METADATA_CSV_FILE)
  
  metadata_dict = {}
  for name in tqdm(tensors.keys()):
    # tag_part, filename_part = utils.get_tag_and_filename(name)
    filename_part = name.split("/")[-1]
        
    # if tag_part != "artist_arsmagna":
    #   continue
    
    album_uuid = "00000000-0000-0000-0000-000000000000"
    track_uuid = str(uuid.uuid4())
    
    new_name = f"{OUTPUT_DIRECTORY}/{track_uuid}.allchunks.pt"
    print(f"Saving tensor to {new_name}")
    torch.save(tensors[name], new_name)

    metadata_dict[track_uuid] = {
      "AlbumID": album_uuid,
      "AlbumName": "<TESTING DO NOT USE>",
      "TrackID": track_uuid,
      "TrackName": filename_part,
      "ArtistName": "artist_arsmagna",
    }

  # add metadata_dict to metadata_df
  metadata_dict_df = pd.DataFrame.from_dict(metadata_dict, orient="index")
  combined = pd.concat([metadata_df, metadata_dict_df])
  combined.to_csv("embeddings/id_metadata_arsmagna_test.csv", index=False)

if __name__ == "__main__":
  main()
