import annoy
from typing import List, Literal, Dict
import pandas as pd
import os

METADATA_CSV_FILE = "embeddings/id_metadata_arsmagna_test.csv"
TENSOR_DIRECTORY = "embeddings/embeddings/"

VECTOR_INDEX_DIR = "vector_index/chunked_6seconds"

# template
ANN_TEMPLATE = f"{VECTOR_INDEX_DIR}/annoy_index_chunked_6seconds_{{pooling_policy}}.ann"
VECTOR_ID_TO_KEY_TEMPLATE = f"{VECTOR_INDEX_DIR}/annoy_int_index_to_uuid_{{pooling_policy}}.csv"

POOLING_POLICY: List[Literal["mean", "max", "mean+max", "VLAD_PCA_64", "VLAD_PCA_512", "VLAD_PCA_1024", "VLAD_PCA_2048"]] = ["mean", "mean+max", "VLAD_PCA_64", "VLAD_PCA_512", "VLAD_PCA_1024", "VLAD_PCA_2048"]

POOLING_POLICY_DIM: Dict[str, int] = {
  "mean": 1024,
  "mean+max": 2048,
  "VLAD_PCA_64": 64,
  "VLAD_PCA_512": 512,
  "VLAD_PCA_1024": 1024,
  "VLAD_PCA_2048": 2048,
}

def main():
  # detect ANN index
  if not os.path.exists(VECTOR_INDEX_DIR):
    print(f"Vector index directory '{VECTOR_INDEX_DIR}' does not exist.")
    return
  
  available_indices = []
  for pooling_policy in POOLING_POLICY:
    if os.path.exists(ANN_TEMPLATE.format(pooling_policy=pooling_policy)):
      available_indices.append(pooling_policy)
      
  if not available_indices:
    print("No ANN indices found.")
    return
  
  print("Available ANN indices:")
  for pooling_policy in available_indices:
    print(f"- Pooling policy: {pooling_policy}")
    print(f"  ANN index file: {ANN_TEMPLATE.format(pooling_policy=pooling_policy)}")
    print(f"  ID to Key mapping file: {VECTOR_ID_TO_KEY_TEMPLATE.format(pooling_policy=pooling_policy)}")
    
  choice = input("Enter the pooling policy to load (e.g., 'mean', 'mean+max'): ").strip()

  print(f"Loading ANN index for pooling policy '{choice}'...")
  if choice not in available_indices:
    print(f"Pooling policy '{choice}' is not available.")
    return
  ann_index_path = ANN_TEMPLATE.format(pooling_policy=choice)
  vector_id_to_key_path = VECTOR_ID_TO_KEY_TEMPLATE.format(pooling_policy=choice)
  embedding_dim = POOLING_POLICY_DIM[choice]
  annoy_index = annoy.AnnoyIndex(embedding_dim, "angular")
  annoy_index.load(ann_index_path)
  print(f"Loaded ANN index from {ann_index_path} with embedding dimension {embedding_dim}.")
  
  # Load vector ID to key mapping
  id_to_key_df = pd.read_csv(vector_id_to_key_path, index_col=0)
  metadata_df = pd.read_csv(METADATA_CSV_FILE)
  joined_df = id_to_key_df.join(metadata_df.set_index("TrackID"), on="TrackID")
  joined_df = joined_df.set_index("TrackID")

  print(f"Loaded metadata for {len(joined_df)} items.")
  
  while True:
    # search by a TrackID
    query_id = input("Enter a TrackID to search (or 'exit' to quit): ").strip()
    if query_id.lower() == "exit":
      break
    
    if query_id not in joined_df.index:
      print(f"TrackID '{query_id}' not found in metadata.")
      continue
    
    item = joined_df.loc[query_id]
    print(f"NN for {item.TrackName} by {item.ArtistName}:")
    vector_id = joined_df.index.get_loc(query_id)
    query_vector = annoy_index.get_item_vector(vector_id)
    nearest_ids, distances = annoy_index.get_nns_by_vector(query_vector, 100, search_k=10_000, include_distances=True)
    print(f"Nearest neighbors for TrackID '{query_id}':")
    for neighbor_id, distance in zip(nearest_ids, distances):
      neighbor_key = joined_df.index[neighbor_id]
      neighbor_info = joined_df.loc[neighbor_key]
      print(f"- TrackID: {neighbor_key}, TrackName: {neighbor_info['TrackName']}, ArtistName: {neighbor_info['ArtistName']}, Distance: {distance:.4f}")

if __name__ == "__main__":
  main()
