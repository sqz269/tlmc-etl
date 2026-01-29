import os
import torch
import numpy as np
import annoy
from tqdm import tqdm
import pickle

# CONFIG
TENSOR_DIR = "embeddings/chunked_6s/"  # Point this to your data
INDEX_FILE = "chunk_6s_index.ann"
KEY_MAP_FILE = "chunk_6s_keymap.pkl"
VECTOR_DIM = 1024

def tensor_stream_generator(root_dir: str):
    """
    Recursively finds .pt files and yields vectors one by one.
    Crucial: Never holds more than 1 file in memory.
    """
    # 1. Discovery Phase (Fast, low memory)
    pt_files = []
    for root, _, files in os.walk(root_dir):
        for file in files:
            if file.endswith(".pt"):
                pt_files.append(os.path.join(root, file))

    print(f"Found {len(pt_files)} files. Starting stream...")

    # 2. Streaming Phase (Sequential)
    for filepath in pt_files:
        try:
            # Force load to CPU to avoid GPU OOM, since we just need numpy
            content = torch.load(filepath, map_location='cpu')
            
            # Extract UUID from filename (matching your logic)
            filename = os.path.basename(filepath)
            uuid = filename.split(".")[0]

            # Handle different data types (List of tensors, or single big Tensor)
            if isinstance(content, list):
                for idx, vector in enumerate(content):
                    yield uuid, idx, vector.numpy()
            
            elif isinstance(content, torch.Tensor):
                # If it's a batch tensor (N, 1024)
                if content.dim() == 2:
                    for idx, vector in enumerate(content):
                        yield uuid, idx, vector.numpy()
                # If it's a single vector (1024,)
                elif content.dim() == 1:
                    yield uuid, 0, content.numpy()
            
            # Explicitly free memory
            del content
            
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
            continue

def build_index_safely():
    if os.path.exists(INDEX_FILE):
        print(f"Index {INDEX_FILE} already exists.")
        return

    # 1. Initialize Annoy
    print(f"Creating Annoy Index (Dim: {VECTOR_DIM})...")
    index = annoy.AnnoyIndex(VECTOR_DIM, "angular")
    
    # CRITICAL: This maps the index to disk immediately. 
    # RAM usage will stay flat (approx 1-2GB) regardless of vector count.
    index.on_disk_build(INDEX_FILE)

    # 2. Stream Data
    key_map = {} # Maps internal integer ID -> (UUID, ChunkIdx)
    internal_id = 0
    
    # Using the generator defined above
    stream = tensor_stream_generator(TENSOR_DIR)
    
    # We use tqdm for progress, but we don't know total len upfront (to save time)
    for uuid, chunk_idx, vector_np in tqdm(stream, desc="Indexing Vectors"):
        index.add_item(internal_id, vector_np)
        
        # Store metadata in RAM (lightweight string/int)
        key_map[internal_id] = (uuid, chunk_idx)
        internal_id += 1

    print(f"Added {internal_id} vectors. Triggering Tree Build...")
    
    # 3. Build Trees
    # This process uses the disk as workspace. 
    # It will be slower than RAM, but it will not crash WSL.
    index.build(200) 
    
    # 4. Save Metadata
    print("Saving Metadata Map...")
    with open(KEY_MAP_FILE, 'wb') as f:
        pickle.dump(key_map, f, protocol=pickle.HIGHEST_PROTOCOL)
        
    print("Done.")

if __name__ == "__main__":
    build_index_safely()