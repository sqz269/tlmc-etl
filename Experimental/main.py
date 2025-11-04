# ---- put THIS at the very top of mert_batch.py ----
from genericpath import isdir
from importlib.metadata import files
import os, sys
from typing import Dict, List

try:
  import dotenv
  dotenv.load_dotenv()
except Exception:
  pass

ffmpeg_bin = os.getenv("FFMPEG_SHARED_LIB_PATH")
if ffmpeg_bin:
  print("Injecting FFMPEG_SHARED_LIB_PATH to PATH:", ffmpeg_bin)
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


chunking_config = ChunkingConfig(
  target_sample_rate=16000, # for MERT
  chunk_size=20,
  overlap_size=5,
)

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
          if ("[ignore]" in full_path.lower()):
            continue
          flac_files[item].append(full_path)

  return flac_files

def main():
  flac_list = get_flac_list("data/")

  for genre, files in flac_list.items():
    for i in files:
      print("Processing track ID:", i)
      audio_chunks_hls = load_flac(
        fp=i,
        chunking_config=chunking_config,
      )

      embeddings_hls = mert.embed_waveforms_batched(
        chunks=audio_chunks_hls.chunks,
        sr_in=audio_chunks_hls.sample_rate,
        layer_mix="last4",
        batch_size=3,
        num_workers=1,  # parallel CPU preprocessing
        pin_memory=True
      )

      print("Embeddings HLS shape:", embeddings_hls.shape)

      hls_pooled = utils.pool(tensor=embeddings_hls, mode="mean+max");

      print("Pooled HLS shape:", hls_pooled.shape)

      # get file name
      filename = os.path.splitext(os.path.basename(i))[0]

      utils.save_tensor(hls_pooled, f"embeddings/[{genre}] - {filename}.pt")

if __name__ == "__main__":
  main()
