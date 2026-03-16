import os, sys
import torch
from tqdm import tqdm
import pandas as pd
from typing import List, Literal, Dict

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from utils import utils
from utils.utils import load_tensor
from annoy import AnnoyIndex

METADATA_CSV_FILE = "embeddings/id_metadata.csv"
TENSOR_DIRECTORY = "embeddings/uuid_embeddings/embeddings/"

VECTOR_INDEX_DIR = "vector_index"

POOLING_POLICY: List[Literal["mean", "max", "mean+max"]] = ["mean", "mean+max"]

def main():

  # -------------------------------------
  # Load CSV metadata
  # -------------------------------------
  # CSV columns: AlbumID,AlbumName,TrackID,TrackName,ArtistName
  metadata_df = pd.read_csv(METADATA_CSV_FILE)
  print(f"Loaded metadata for {len(metadata_df)} items.")

  # Build fast lookup by TrackID
  metadata_df["TrackID"] = metadata_df["TrackID"].astype(str)
  metadata_lookup = metadata_df.set_index("TrackID")

  # -------------------------------------
  # Load embeddings (.pt)
  # -------------------------------------
  tensors = load_tensor(TENSOR_DIRECTORY, num_workers=os.cpu_count() or 4)
  if not tensors:
    print("No .pt files found in the directory. Exiting.")
    return

  for pooling_policy in POOLING_POLICY:
    pooled_tensors = utils.pool_loaded_tensor_dict(
      tensors=tensors, mode=pooling_policy
    )

    # Extract Track IDs from filenames
    track_ids: List[str] = []
    for name in tqdm(pooled_tensors.keys()):
      track_ids.append(utils.get_uuid_from_filename(name))

    embeddings = torch.stack(list(pooled_tensors.values())).numpy()
    embedding_dim = embeddings.shape[1]
    print(f"Building Annoy index with pooling policy '{pooling_policy}' and embedding dimension {embedding_dim}...")
    annoy_index = AnnoyIndex(embedding_dim, "angular")
    
    vector_id_to_key: Dict[int, str] = {}
    for i, vector in enumerate(tqdm(embeddings, desc="Adding vectors to Annoy index")):
      annoy_index.add_item(i, vector)
      vector_id_to_key[i] = track_ids[i]

    print("Building Annoy index (this may take a while)...")
    annoy_index.build(200)
    index_path = f"{VECTOR_INDEX_DIR}/annoy_index_{pooling_policy}.ann"
    vector_id_to_key_path = f"{VECTOR_INDEX_DIR}/annoy_int_index_to_uuid_{pooling_policy}.csv"
    os.makedirs(VECTOR_INDEX_DIR, exist_ok=True)
    
    pd.DataFrame.from_dict(vector_id_to_key, orient="index", columns=["TrackID"]).to_csv(
      vector_id_to_key_path
    )
    annoy_index.save(index_path)
    print(f"Saved Annoy index to {index_path}")

if __name__ == "__main__":
  main()
