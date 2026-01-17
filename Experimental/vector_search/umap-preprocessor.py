from pathlib import Path
import os
import sys

import pandas as pd
import torch
import umap
from torch._tensor import Tensor
from tqdm import tqdm

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
RESULTS_DIR = ROOT_DIR / "results" / "umap"

from utils import utils
from utils.utils import load_tensor

# Configuration
METADATA_CSV_FILE = str(ROOT_DIR / "embeddings" / "id_metadata.csv")
TENSOR_DIRECTORY = str(ROOT_DIR / "embeddings" / "uuid_embeddings" / "embeddings")
POOLING_POLICY = "mean" # Pick one policy for the CSV to keep it simple

def main():
  print(f"--- Generating UMAP CSV for policy: {POOLING_POLICY} ---")
  RESULTS_DIR.mkdir(parents=True, exist_ok=True)
  
  # 1. Load Metadata
  metadata_df = pd.read_csv(METADATA_CSV_FILE)
  metadata_df["TrackID"] = metadata_df["TrackID"].astype(str)
  metadata_lookup = metadata_df.set_index("TrackID")

  # 2. Load Tensors
  tensors = load_tensor(TENSOR_DIRECTORY, num_workers=os.cpu_count() or 4)
  if not tensors: 
    print("No tensors found.")
    return

  # 3. Pool Tensors
  pooled_tensors = utils.pool_loaded_tensor_dict(tensors=tensors, mode=POOLING_POLICY)
  track_ids = [utils.get_uuid_from_filename(name) for name in pooled_tensors.keys()]
  embeddings = torch.stack(list[Tensor](pooled_tensors.values())).numpy()

  # 4. Run UMAP
  print("Running UMAP (this may take a while)...")
  reducer = umap.UMAP(n_components=3, n_neighbors=100, min_dist=0.3, metric="cosine")
  umap_embeddings = reducer.fit_transform(embeddings)

  # 5. Create DataFrame
  df_out = pd.DataFrame(umap_embeddings, columns=["x", "y", "z"])
  df_out["TrackID"] = track_ids
  
  # 6. Join Metadata
  df_out = df_out.join(metadata_lookup, on="TrackID", how="left")
  
  # 7. Save to CSV for the App
  output_filename = RESULTS_DIR / f"umap_data_{POOLING_POLICY}.csv"
  df_out.to_csv(output_filename, index=False)
  print(f"Done! Saved to {output_filename}")

if __name__ == "__main__":
  main()