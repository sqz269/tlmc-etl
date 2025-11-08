# ---- put THIS at the very top of mert_batch.py ----
from genericpath import isdir
from importlib.metadata import files
import os, sys
from typing import Dict, List, Set, Tuple

try:
  import dotenv
  dotenv.load_dotenv()
except Exception:
  pass

ffmpeg_bin = os.getenv("FFMPEG_SHARED_LIB_PATH")
if ffmpeg_bin:
  # print("Injecting FFMPEG_SHARED_LIB_PATH to PATH:", ffmpeg_bin)
  # 1) Make sure Windows can find the DLLs
  #    (Python 3.8+ on Windows supports this)
  try:
    os.add_dll_directory(ffmpeg_bin)  # crucial for DLL lookup
  except Exception:
    # fallback: prepend to PATH if add_dll_directory is unavailable
    os.environ["PATH"] = ffmpeg_bin + os.pathsep + os.environ.get("PATH", "")
  else:
      # Even with add_dll_directory, PATH prepend doesn't hurt
    os.environ["PATH"] = ffmpeg_bin + os.pathsep + os.environ.get("PATH", "")

  # 2) Tell torio which FFmpeg major to use (matches your 6.x build)
  os.environ.setdefault("TORIO_USE_FFMPEG_VERSION", "6")

  # Optional: debug where torio is searching
  # os.environ["TORIO_LOG_LEVEL"] = "DEBUG"

# ---- only now import anything that pulls in torchaudio/torio ----

import numpy as np
import torch
import requests
from loader import load_flac, load_m3u8_playlist_remote, ChunkingConfig
import mert
from utils import utils
from tqdm import tqdm

POOLING_POLICY = "mean+max"
EMBEDDING_DIRECTORY = f"embeddings/{POOLING_POLICY}"

chunking_config = ChunkingConfig(
  target_sample_rate=16000, # for MERT
  chunk_size=20,
  overlap_size=5,
)

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
        genre, title = parse_filename_genre_and_title(f)
        completed.setdefault(genre, set()).add(title)

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

def main():
  flac_list = get_flac_list("data/")
  completed_embeddings = get_completed_embeddings(EMBEDDING_DIRECTORY)

  for genre, files in tqdm(flac_list.items(),
                                total=len(flac_list),
                                desc="Genres",
                                dynamic_ncols=True):
    for fp in tqdm(files,
                        total=len(files),
                        desc=genre,
                        leave=False,
                        dynamic_ncols=True):
      # print("Processing track ID:", i)
      # get file name
      filename = os.path.splitext(os.path.basename(fp))[0]
      if genre in completed_embeddings and filename in completed_embeddings[genre]:
        tqdm.write(f"Skipping {filename} in {genre} (already processed)")
        continue

      try:
        audio_chunks_hls = load_flac(
          fp=fp,
          chunking_config=chunking_config,
        )
      except Exception as e:
        tqdm.write(f"Could not load {fp}: {e}")
        continue

      # check if any chunks were loaded
      if len(audio_chunks_hls.chunks) == 0:
        tqdm.write(f"No audio chunks found in {fp}, skipping.")
        continue

      embeddings_hls = mert.embed_waveforms_batched(
        chunks=audio_chunks_hls.chunks,
        sr_in=audio_chunks_hls.sample_rate,
        layer_mix="last4",
        batch_size=3,
        num_workers=1,  # parallel CPU preprocessing
        pin_memory=True
      )

      # print("Embeddings HLS shape:", embeddings_hls.shape)

      hls_pooled = utils.pool(tensor=embeddings_hls, mode=POOLING_POLICY)

      # print("Pooled HLS shape:", hls_pooled.shape)

      write_path = os.path.join(EMBEDDING_DIRECTORY, f"[{genre}] - {filename}.pt")
      utils.save_tensor(hls_pooled, write_path)

if __name__ == "__main__":
  main()
