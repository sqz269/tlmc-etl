import numpy as np
import cupy as cp
import os, sys
import torch
from tqdm import tqdm
import pandas as pd
from typing import List, Literal, Dict

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from utils import utils
from utils.utils import load_tensor, load_vlad_tensors
from annoy import AnnoyIndex

from cuml.decomposition import PCA

METADATA_CSV_FILE = "embeddings/id_metadata_arsmagna_test.csv"
VLAD_TENSOR_DIRECTORY = "embeddings/"
TENSOR_DIRECTORY = "embeddings/uuid_embeddings/"

VECTOR_INDEX_DIR = "vector_index"

POOLING_POLICY: List[Literal["mean", "max", "mean+max"]] = ["mean", "mean+max"]

N_PCA_COMPONENTS = 2048

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
  # tensors = load_tensor(TENSOR_DIRECTORY, num_workers=os.cpu_count() or 4)
  # if not tensors:
  #   print("No .pt files found in the directory. Exiting.")
  #   return

  # # for pooling_policy in POOLING_POLICY:
  # pooled_tensors = utils.pool_loaded_tensor_dict(
  #   tensors=tensors, mode=pooling_policy
  # )

  vlad_tensors = load_vlad_tensors(VLAD_TENSOR_DIRECTORY, max_workers=16)

  # Extract Track IDs from filenames
  track_ids: List[str] = []
  for name in tqdm(vlad_tensors.keys()):
    track_ids.append(utils.get_uuid_from_filename(name))

  embeddings = cp.asarray(np.stack(list(vlad_tensors.values())))

  del vlad_tensors

  pca = PCA(n_components=N_PCA_COMPONENTS, whiten=False)
  pca.fit(embeddings)
  vlad_reduced_embeddings = pca.transform(embeddings)
  dim = vlad_reduced_embeddings.shape[1]

  del embeddings

  print(f"Building Annoy index with pooling policy 'VLAD_PCA_{N_PCA_COMPONENTS}' and embedding dimension {dim}...")
  annoy_index = AnnoyIndex(dim, "angular")
  
  vector_id_to_key: Dict[int, str] = {}
  for i, vector in enumerate(tqdm(vlad_reduced_embeddings, desc="Adding vectors to Annoy index")):
    annoy_index.add_item(i, vector)
    vector_id_to_key[i] = track_ids[i]

  print("Building Annoy index (this may take a while)...")
  annoy_index.build(200)
  index_path = f"{VECTOR_INDEX_DIR}/annoy_index_vlad_pca_{N_PCA_COMPONENTS}.ann"
  vector_id_to_key_path = f"{VECTOR_INDEX_DIR}/annoy_int_index_to_uuid_vlad_pca_{N_PCA_COMPONENTS}.csv"
  os.makedirs(VECTOR_INDEX_DIR, exist_ok=True)
  
  pd.DataFrame.from_dict(vector_id_to_key, orient="index", columns=["TrackID"]).to_csv(
    vector_id_to_key_path
  )
  annoy_index.save(index_path)
  print(f"Saved Annoy index to {index_path}")

if __name__ == "__main__":
  main()
