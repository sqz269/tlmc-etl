import os
import torch
import numpy as np
import faiss
from tqdm import tqdm
import pickle
import time

# --- CONFIG ---
TENSOR_DIR = "embeddings/chunked_6seconds/chunked_6s"  # Point this to your data
INDEX_FILE = "chunk_6s_index.faiss"
KEY_MAP_FILE = "chunk_6s_keymap.pkl"
VECTOR_DIM = 1024

# FAISS Hyperparameters
# Strategy: Pre-rotate (OPQ) -> Cluster (IVF) -> Quantize (PQ)
# Memory: ~640MB for 10M vectors.
INDEX_STRING = "OPQ64_1024,IVF16384,PQ64x8"
TRAIN_SIZE = 650_000       # Vectors needed to train centroids (39 * nlist is a safe rule)
BATCH_SIZE = 50_000        # How many vectors to add to GPU at once

# Only enable if you have enough VRAM and faiss-gpu is installed correctly
USE_GPU = False

print(f"Using GPU: {USE_GPU}")
print(f"Index String: {INDEX_STRING}")
print(f"Train Size: {TRAIN_SIZE}")
print(f"Batch Size: {BATCH_SIZE}")
print(f"Vector Dim: {VECTOR_DIM}")
print(f"Tensor Dir: {TENSOR_DIR}")
print(f"Index File: {INDEX_FILE}")
print(f"Key Map File: {KEY_MAP_FILE}")

def tensor_stream_generator(root_dir: str):
  """
  Recursively finds .pt files and yields vectors one by one.
  Crucial: Never holds more than 1 file in memory.
  """
  # 1. Discovery Phase
  pt_files = []
  for root, _, files in os.walk(root_dir):
    for file in files:
      if file.endswith(".pt"):
        pt_files.append(os.path.join(root, file))

  print(f"Found {len(pt_files)} files.")

  # 2. Streaming Phase
  for filepath in pt_files:
    try:
      # Load to CPU
      content = torch.load(filepath, map_location='cpu')
      
      filename = os.path.basename(filepath)
      uuid = filename.split(".")[0]

      # Normalize input to list of vectors
      vectors_to_yield = []
      
      if isinstance(content, list):
        vectors_to_yield = content
      elif isinstance(content, torch.Tensor):
        if content.dim() == 2:
          vectors_to_yield = [v for v in content]
        elif content.dim() == 1:
          vectors_to_yield = [content]
      
      # Yield loop
      for idx, vector in enumerate(vectors_to_yield):
        # Ensure float32 numpy array
        if isinstance(vector, torch.Tensor):
          yield uuid, idx, vector.float().numpy()
        else:
          yield uuid, idx, np.array(vector, dtype=np.float32)

      del content
      
    except Exception as e:
      print(f"Error reading {filepath}: {e}")
      continue

def get_training_data(stream_gen):
  """
  Consumes the start of the stream to get vectors for training.
  """
  print(f"Gathering {TRAIN_SIZE} vectors for training...")
  train_vectors = []
  
  # We use a limited tqdm just for the training gathering
  pbar = tqdm(total=TRAIN_SIZE, desc="Buffering Train Data")
  
  for _, _, vector in stream_gen:
    train_vectors.append(vector)
    pbar.update(1)
    if len(train_vectors) >= TRAIN_SIZE:
      break
      
  pbar.close()
  
  # Convert list of arrays to one big (N, 1024) matrix
  return np.stack(train_vectors)

def build_faiss_index():
  if os.path.exists(INDEX_FILE):
    print(f"Index {INDEX_FILE} already exists. Delete it to rebuild.")
    return

  # --- 1. Setup & GPU Resources ---
  if USE_GPU:
    res = faiss.StandardGpuResources()
  else:
    res = None
  
  print(f"Initializing Index: {INDEX_STRING}")
  # Build on CPU first
  index_cpu = faiss.index_factory(VECTOR_DIM, INDEX_STRING)
  index_cpu.verbose = True
  
  faiss.omp_set_num_threads(16)

  # Move to GPU for Training & Indexing
  if USE_GPU:
    print("Moving index to GPU...")
    co = faiss.GpuClonerOptions()
    co.useFloat16LookupTables = True   # <-- fixes 48KB shared-mem issue for PQ64
    co.useFloat16 = True               # optional: faster / less GPU mem in some ops
    co.indicesOptions = faiss.INDICES_32_BIT  # good for <2^31 vectors

    index = faiss.index_cpu_to_gpu(res, 0, index_cpu, co)
    print(f"Index on GPU: {index}")
  else:
    index = index_cpu

  # --- 2. Training Phase ---
  # We need to restart the generator to get data for training
  stream = tensor_stream_generator(TENSOR_DIR)
  
  xt = get_training_data(stream)
  
  print("Training Index (calculating centroids)...")
  t0 = time.time()
  print(f"Training data shape: {xt.shape} | Training index: {index}")
  index.train(xt)
  print(f"Training completed in {time.time() - t0:.2f}s")
  
  # Free memory
  del xt

  # --- 3. Indexing Phase ---
  # We must restart the stream from the beginning to index EVERYTHING
  # (including the data we used for training)
  print("Restarting stream for full indexing...")
  stream = tensor_stream_generator(TENSOR_DIR)
  
  key_map = {}
  current_id = 0
  
  # Buffers for batching
  vec_buffer = []
  meta_buffer = [] # Holds (uuid, chunk_idx)

  for uuid, chunk_idx, vector in tqdm(stream, desc="Indexing Batches"):
    vec_buffer.append(vector)
    meta_buffer.append((uuid, chunk_idx))
    
    # When buffer hits batch size, flush to GPU
    if len(vec_buffer) >= BATCH_SIZE:
      # 1. Add to FAISS
      batch_np = np.stack(vec_buffer)
      index.add(batch_np)
      
      # 2. Update Metadata Map
      # The IDs in FAISS will be sequential: current_id to current_id + batch_len
      for i, meta in enumerate(meta_buffer):
        key_map[current_id + i] = meta
      
      current_id += len(vec_buffer)
      
      # 3. Clear buffers
      vec_buffer = []
      meta_buffer = []

  # --- 4. Flush Remaining Buffer ---
  if vec_buffer:
    print(f"Flushing final batch of {len(vec_buffer)}...")
    batch_np = np.stack(vec_buffer)
    index.add(batch_np)
    for i, meta in enumerate(meta_buffer):
      key_map[current_id + i] = meta
    current_id += len(vec_buffer)

  print(f"Total vectors indexed: {index.ntotal}")

  # --- 5. Save to Disk ---
  if USE_GPU:
    print("Moving index to CPU for saving...")
    index_cpu_final = faiss.index_gpu_to_cpu(index)
    print(f"Writing {INDEX_FILE}...")
    faiss.write_index(index_cpu_final, INDEX_FILE)
  else:
    print(f"Writing {INDEX_FILE}...")
    faiss.write_index(index, INDEX_FILE)

if __name__ == "__main__":
  build_faiss_index()