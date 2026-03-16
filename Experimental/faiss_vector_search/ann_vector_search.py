import faiss
import pickle
import numpy as np
import time

import torch

# CONFIG
INDEX_FILE = "chunk_6s_index.faiss"
KEY_MAP_FILE = "chunk_6s_keymap.pkl"
USE_GPU = False  # Set to True to use your 5090 for super-fast search

def load_resources():
  print(f"Loading Metadata from {KEY_MAP_FILE}...")
  with open(KEY_MAP_FILE, "rb") as f:
    key_map = pickle.load(f)

  print(f"Loading Index from {INDEX_FILE}...")
  index = faiss.read_index(INDEX_FILE)

  # 1. Extract the underlying IVF index from the OPQ wrapper
  ivf_index = faiss.extract_index_ivf(index)
  
  # 2. Now you can set nprobe on the extracted part
  ivf_index.nprobe = 64  
  
  print(f"Index loaded. Total vectors: {index.ntotal}")
  print(f"Search depth (nprobe): {ivf_index.nprobe}") # Print from the extracted part
  # --- FIX ENDS HERE ---
  if USE_GPU:
    print("Moving index to GPU...")
    # Standard GPU resource object
    res = faiss.StandardGpuResources()
    # Move index
    index = faiss.index_cpu_to_gpu(res, 0, index)
    print("Index is now on GPU.")

  return index, key_map

def search_index(index, key_map, query_vector, k=5):
  """
  args:
    index: The FAISS index
    key_map: The dictionary mapping IDs to filenames
    query_vector: A numpy array of shape (1, 1024)
    k: How many results to return
  """
  # 1. Sanity Check
  if query_vector.shape != (1, 1024):
    print(f"Reshaping vector from {query_vector.shape} to (1, 1024)...")
    query_vector = query_vector.reshape(1, 1024)

  # 2. Run Search
  # D = Distances (Lower is better for L2, Higher is better for Inner Product)
  # I = Indices (The internal IDs we mapped earlier)
  start_time = time.time()
  D, I = index.search(query_vector, k)
  elapsed = time.time() - start_time

  print(f"\n--- Search Results (Found in {elapsed:.4f}s) ---")
  
  # 3. Decode Results
  # The results are arrays of shape (1, k)
  found_indices = I[0]
  found_distances = D[0]

  results = []
  for rank, (internal_id, distance) in enumerate(zip(found_indices, found_distances)):
    if internal_id == -1:
      continue # No result found
      
    # Retrieve real metadata
    uuid, chunk_idx = key_map[internal_id]
    
    # Calculate timestamp (assuming 6s chunks)
    start_time_str = f"{chunk_idx * 6}s"
    
    print(f"Rank {rank+1}: [{uuid}] @ {start_time_str} | Dist: {distance:.4f}")
    results.append({
      "uuid": uuid,
      "timestamp": chunk_idx * 6,
      "distance": distance
    })
    
  return results

if __name__ == "__main__":
  # 1. Load everything once
  index, key_map = load_resources()

  # 2. Create a Dummy Vector (Random Noise) for testing
  # In reality, you would generate this using your embedding model
  # fake_query = np.random.rand(1, 1024).astype('float32')
  query_vector_path = "embeddings/chunked_6seconds/chunks_6s_ars/[2011.05.01 [ARS-002] Ariabl'eyeS — 蒼い瞳のアリア [M3-27]] - 01. Cathy — 蒼い瞳のアリア.allchunks.pt"
  query_vector = torch.load(query_vector_path, map_location='cpu')
  
  for vector in query_vector:
    search_index(index, key_map, vector, k=5)
