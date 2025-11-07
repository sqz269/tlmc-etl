import os
import tqdm
from typing import Dict, Literal, Literal
import torch

def load_embeddings(pool_mode: Literal["mean", "max", "mean+max"] = "mean") -> torch.Tensor:
  embedding_dir = "embeddings"
  target_dir = os.path.join(embedding_dir, pool_mode)
  if not os.path.exists(target_dir):
    raise FileNotFoundError(f"Directory {target_dir} does not exist.")
  
  tensors = load_tensor(target_dir)
  return torch.stack(list(tensors.values()))


def load_tensor(dir: str) -> Dict[str, torch.Tensor]:
  """Loads all .pt files from a directory into a dictionary."""
  tensors: Dict[str, torch.Tensor] = {}
  # tqdm
  for file in tqdm.tqdm(os.listdir(dir)):
    if file.endswith(".pt"):
      try:
        tensor = torch.load(os.path.join(dir, file))
        tensors[file] = tensor
      except Exception as e:
        print(f"Could not load {file}: {e}")
  return tensors


def pool(tensor: torch.Tensor, mode: str = "mean") -> torch.Tensor:
  """
  Pooling function for 2D tensor of shape (time, dim).
  Supported modes: 'mean', 'max', 'mean+max' (concatenation).
  Returns a 1D tensor of shape (dim,) or (2*dim,) for 'mean+max'.
  """
  if mode == "mean":
    return tensor.mean(dim=0)
  elif mode == "max":
    return tensor.max(dim=0).values
  elif mode == "mean+max":
    mean_pool = tensor.mean(dim=0)
    max_pool = tensor.max(dim=0).values
    return torch.cat((mean_pool, max_pool), dim=0)
  else:
    raise ValueError(f"Unsupported pooling mode: {mode}")

def save_tensor(tensor: torch.Tensor, filepath: str) -> None:
  """
  Save a tensor to a file.
  """
  torch.save(tensor, filepath)
