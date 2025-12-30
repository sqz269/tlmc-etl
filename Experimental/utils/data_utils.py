import json
import numpy as np
import pandas as pd
from collections import defaultdict
from typing import Dict, List, Tuple, Any

def load_metadata_and_map(metadata_path: str, tensors: Dict[str, Any]) -> Tuple[pd.DataFrame, Dict[str, List[int]]]:
  """
  Loads metadata and maps Artist IDs to Tensor Indices.
  Returns:
    1. A clean DataFrame with TensorIdx columns.
    2. A dictionary mapping artist_id -> list of tensor indices.
  """
  print(f"Loading metadata from {metadata_path}...")
  with open(metadata_path, "r", encoding="utf-8") as f:
    metadata_dict = json.load(f)
  
  # Create DataFrame and lookup dict
  df = pd.DataFrame(metadata_dict)
  meta_lookup = df.set_index("TrackID").to_dict(orient="index")
  
  # Map UUIDs (filenames) to metadata entries
  missing_count = 0
  for idx, key in enumerate(tensors.keys()):
    uuid = key.split(".")[0]
    if uuid in meta_lookup:
      meta_lookup[uuid]["TensorIdx"] = idx
    else:
      missing_count += 1
      
  if missing_count > 0:
    print(f"Warning: {missing_count} tensors could not be matched to metadata.")

  # Re-build DataFrame to include TensorIdx
  emb_idx_df = pd.DataFrame.from_dict(meta_lookup, orient='index')
  # Drop tracks where we have metadata but no tensor file
  emb_idx_df.dropna(subset=['TensorIdx'], inplace=True)
  emb_idx_df['TensorIdx'] = emb_idx_df['TensorIdx'].astype(int)
  emb_idx_df = emb_idx_df.reset_index().rename(columns={'index': 'TrackID'})
  
  # Precompute Artist ID lists
  emb_idx_df['ArtistIDList'] = emb_idx_df['Artists'].apply(lambda x: [artist['id'] for artist in x])

  # Build Artist -> Track Indices map
  print("Building Artist to Track Index map...")
  artist_to_track_indices = defaultdict(list)
  
  # Efficiently zip columns to avoid repeated DF lookups
  for artists_payload, tensor_idx in zip(emb_idx_df['Artists'], emb_idx_df['TensorIdx']):
    for artist in artists_payload:
      artist_to_track_indices[artist['id']].append(tensor_idx)

  return emb_idx_df, artist_to_track_indices

def get_artist_name(df: pd.DataFrame, artist_id: str) -> str:
  """Retrieves the artist name from the dataframe given an ID."""
  # Find the first row containing this artist_id
  # Note: For production, this should be cached in a dict, but this preserves your original logic
  try:
    row = df[df['ArtistIDList'].apply(lambda x: artist_id in x)].iloc[0]
    for artist in row['Artists']:
      if artist['id'] == artist_id:
        return artist['name']
  except IndexError:
    return "Unknown Artist"
  return "Unknown Artist"

def knn_search(vectors: Dict[str, Any], query_vector: Any, k: int, backend=np) -> List[str]:
  """
  Generic KNN search. 
  Args:
    backend: Pass 'numpy' (CPU) or 'cupy' (GPU).
  """
  # Ensure consistent ordering
  keys = list(vectors.keys())
  
  # Create matrix from dict values
  # If backend is cupy, this stacks the arrays on GPU
  matrix = backend.array(list(vectors.values()))
  
  # Compute L2 distance
  distances = backend.linalg.norm(matrix - query_vector, axis=1)
  
  # Get top K indices (smallest distance)
  top_k_indices = backend.argsort(distances)[:k]
  
  # If using GPU, move indices to CPU for list access
  if backend != np:
    top_k_indices = top_k_indices.get()
    
  return [keys[i] for i in top_k_indices]