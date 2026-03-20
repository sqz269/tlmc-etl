import pickle
import re
import os
import tqdm
import hashlib
import torch
import numpy as np
from typing import Dict, List, Literal, Literal, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.loader import SourceFileInfo

def load_embeddings(pool_mode: Literal["mean", "max", "mean+max"] = "mean") -> torch.Tensor:
  embedding_dir = "embeddings"
  target_dir = os.path.join(embedding_dir, pool_mode)
  if not os.path.exists(target_dir):
    raise FileNotFoundError(f"Directory {target_dir} does not exist.")
  
  tensors = load_tensor(target_dir)
  return torch.stack(list(tensors.values()))

def load_embeddings_chunks(embedding_dir: str) -> Dict[str, torch.Tensor]:
  target_dir = os.path.join(embedding_dir, "chunks")
  if not os.path.exists(target_dir):
    raise FileNotFoundError(f"Directory {target_dir} does not exist.")
  
  tensors = load_tensor(target_dir)
  return tensors

def load_tensor(dir: str, num_workers: int = 8, use_cache: bool = True, cache_dir: str = "embeddings/cache") -> Dict[str, torch.Tensor]:
  """Loads all .pt files from a directory in parallel."""

  if use_cache:
    print(f"Loading cache from {cache_dir}")
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"{hashlib.md5(dir.encode()).hexdigest()}.pkl")
    if os.path.exists(cache_file):
      with open(cache_file, "rb") as f:
        return pickle.load(f)
    else:
      print(f"Cache file {cache_file} does not exist, loading from directory {dir}")

  # pt_files = [f for f in os.listdir(dir) if f.endswith(".pt")]
  # load pt files recurisvely
  pt_files = []
  for root, _, files in os.walk(dir):
    for file in files:
      if file.endswith(".pt"):
        pt_files.append(os.path.join(root, file))
  tensors: Dict[str, torch.Tensor] = {}

  def load_file(filepath):
    try:
      return filepath, torch.load(filepath)
    except Exception as e:
      return filepath, e

  with ThreadPoolExecutor(max_workers=num_workers) as ex:
    futures = {ex.submit(load_file, f): f for f in pt_files}
    for fut in tqdm.tqdm(as_completed(futures), total=len(futures)):
      fname, result = fut.result()
      if isinstance(result, Exception):
        print(f"Could not load {fname}: {result}")
      else:
        # get filename
        filename = os.path.basename(fname)
        tensors[filename] = result


  if use_cache:
    print(f"Saving cache to {cache_file}")
    with open(cache_file, "wb") as f:
      pickle.dump(tensors, f, protocol=pickle.HIGHEST_PROTOCOL)

  return tensors

def load_vlad_tensors(embedding_dir: str, max_workers: int = 4) -> Dict[str, np.ndarray]:
  target_dir = os.path.join(embedding_dir, "vlad_pooled")
  if not os.path.exists(target_dir):
    raise FileNotFoundError(f"Directory {target_dir} does not exist.")
  
  # Get list of files
  npy_files = [f for f in os.listdir(target_dir) if f.endswith(".npy")]
  tensors: Dict[str, np.ndarray] = {}

  # Helper function for a single load
  def load_single_file(filename):
    path = os.path.join(target_dir, filename)
    return filename, np.load(path)

  print(f"Loading {len(npy_files)} VLAD tensors with {max_workers} workers")
  with ThreadPoolExecutor(max_workers=max_workers) as executor:
    futures = {executor.submit(load_single_file, f): f for f in npy_files}
    for fut in tqdm.tqdm(as_completed(futures), total=len(futures)):
      filename, array = fut.result()
      tensors[filename] = array
  return tensors

def pool_loaded_tensor_dict(
  tensors: Dict[str, torch.Tensor],
  mode: Literal["mean", "max", "mean+max"] = "mean",
) -> Dict[str, torch.Tensor]:
  # check if we are processing all chunks
  sample_tensor = next(iter(tensors.values()))
  sample_file = next(iter(tensors.keys()))
  pooled_tensors: Dict[str, torch.Tensor] = {}
  if sample_tensor.ndim == 2 and "allchunks" in sample_file:
    print(f"Detected allchunks tensors, pooling to 1D embedding ({mode})")
    for key in tqdm.tqdm(tensors):
      tensor = pool(tensors[key], mode=mode)
      pooled_tensors[key] = tensor

  return pooled_tensors

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

def get_tag_and_filename(fname: str) -> Tuple[str, str]:
  try:
    if not fname.endswith(".pt"):
      raise ValueError("Filename must end with .pt")
    
    if "allchunks" in fname:
      fname = fname.replace(".allchunks.pt", ".pt")
    
    # Assumes format "[{genre}] - {filename}.pt"
    tag, name = fname.split('] - ', 1)
    tag = tag[1:]  # Remove the leading '['
    return tag, name
  except ValueError as e:
    raise e
  
UUID_REGEX = re.compile(
  r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
def get_uuid_from_filename(fname: str) -> str:
  match = UUID_REGEX.search(fname)
  if match:
    return match.group(0)
  else:
    raise ValueError(f"No UUID found in filename: {fname}")

def save_tensor(tensor: torch.Tensor, filepath: str) -> None:
  """
  Save a tensor to a file.
  """
  torch.save(tensor, filepath)

def parse_filename_genre_and_title(filename: str) -> Tuple[str, str]:
  try:
    # Assumes format "[{genre}] - {filename}.pt"
    genre_part, filename_part = filename.split('] - ', 1)
    genre = genre_part[1:]  # Remove the leading '['
    title = os.path.splitext(filename_part)[0]  # Remove .pt extension
    return genre, title
  except ValueError:
    return 'Unknown', os.path.splitext(filename)[0]

def get_completed_embeddings(embedding_dir: str) -> Dict[str, Set[str]]:
  completed: Dict[str, Set[str]] = {}
  for fp, _, files in os.walk(embedding_dir):
    for f in files:
      if f.lower().endswith(".pt"):
        tag, title = parse_filename_genre_and_title(f)
        completed.setdefault(tag, set()).add(title)

  return completed

def get_flac_list(dir_path: str) -> Dict[str, List[str]]:
  # genre and list of songs
  flac_files: Dict[str, List[str]] = {}
  # first level dir is genre info
  for item in os.listdir(dir_path):
    path = os.path.join(dir_path, item)
    if not os.path.isdir(path):
      continue

    flac_files[item] = []
    for fp, _, files in os.walk(path):
      for f in files:
        if f.lower().endswith(".flac"):
          full_path = os.path.join(fp, f)
          # if ("[ignore]" in full_path.lower()):
          #   continue
          flac_files[item].append(full_path)

  return flac_files

def get_process_list(dir_path: str, embedding_path: str) -> List[SourceFileInfo]:
  flac_list = get_flac_list(dir_path)
  completed = get_completed_embeddings(embedding_path)
  proc: List[SourceFileInfo] = []
  loaded = 0
  done = 0
  for tag, files in flac_list.items():
    for fp in files:
      fn = os.path.splitext(os.path.basename(fp))[0]
      if tag in completed:
        if fn in completed[tag]:
          done += 1
          continue
      info = SourceFileInfo(
        path=fp,
        filename=fn,
        tag=tag,
      )
      loaded += 1
      proc.append(info)

  print(f"Total files to process: {loaded}, already completed: {done}")
  return proc
