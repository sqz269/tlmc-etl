import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from typing import Literal, List
import torch
import numpy as np
from tqdm import tqdm
from utils import utils
from utils.utils import load_tensor

# Configuration
SOURCE_DIR = "embeddings/uuid_embeddings/embeddings/"
OUTPUT_DIR = "embeddings/push_ready/"
POOLING_POLICY: List[str] = ["mean", "mean+max"]

def export_pooled_embeddings(pooling_policy: Literal["mean", "mean+max"]):
  # 1. Load the raw PyTorch tensors
  print(f"Loading tensors from {SOURCE_DIR}...")
  tensors = load_tensor(SOURCE_DIR, num_workers=os.cpu_count() or 4)
  
  if not tensors:
    print("No files found.")
    return

  # 2. Perform Pooling in Python (Keep your existing logic here)
  print(f"Pooling tensors with policy: '{pooling_policy}'...")
  pooled_tensors = utils.pool_loaded_tensor_dict(tensors=tensors, mode=pooling_policy)

  # 3. Export to C#-compatible Binary
  # Structure: Directory of files named "{UUID}.bin"
  # Content: Pure raw bytes (Float32 array)
  
  save_path = os.path.join(OUTPUT_DIR, pooling_policy)
  os.makedirs(save_path, exist_ok=True)
  
  print(f"Exporting binaries to {save_path}...")
  
  count = 0
  for filename, tensor in tqdm(pooled_tensors.items()):
    try:
      # Extract UUID to use as the clean filename
      uuid = utils.get_uuid_from_filename(filename)
      
      # Ensure tensor is on CPU and Float32
      # flattening is optional since it's 1D, but good safety
      arr = tensor.cpu().numpy().astype(np.float32).flatten()
      
      # Save raw bytes
      # This is readable by C# BinaryReader or File.ReadAllBytes
      arr.tofile(os.path.join(save_path, f"{uuid}.bin"))
      count += 1
      
    except Exception as e:
      print(f"Error exporting {filename}: {e}")

  print(f"Successfully exported {count} files ready for C#.")

if __name__ == "__main__":
  for pooling_policy in POOLING_POLICY:
    export_pooled_embeddings(pooling_policy)