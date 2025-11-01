# ---- put THIS at the very top of mert_batch.py ----
import os, sys

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
from loader import load_flac, load_m3u8_playlist_remote, ChunkingConfig
import mert
from utils import utils


chunking_config = ChunkingConfig(
  target_sample_rate=16000, # for MERT
  chunk_size=20,
  overlap_size=5,
)

def main():
  audio_chunks_flac = load_flac("data/(01) [二羽凛奈，朔間咲] 明日世界をなくしても.flac", chunking_config)
  audio_chunks_hls = load_m3u8_playlist_remote("https://staging-api.marisad.me/api/asset/track/b7963120-4ab6-4c04-b584-bb76396bb552/hls/128k/playlist.m3u8", chunking_config)

  embeddings_flac = mert.embed_waveforms_batched(
    chunks=audio_chunks_flac.chunks,
    sr_in=audio_chunks_flac.sample_rate,
    layer_mix="last4",
    batch_size=3,
    num_workers=1,  # parallel CPU preprocessing
    pin_memory=True
  )

  print("Embeddings FLAC shape:", embeddings_flac.shape)

  embeddings_hls = mert.embed_waveforms_batched(
    chunks=audio_chunks_hls.chunks,
    sr_in=audio_chunks_hls.sample_rate,
    layer_mix="last4",
    batch_size=3,
    num_workers=1,  # parallel CPU preprocessing
    pin_memory=True
  )

  print("Embeddings HLS shape:", embeddings_hls.shape)

  flac_pooled = utils.pool(embeddings_flac, mode="mean");
  hls_pooled = utils.pool(embeddings_hls, mode="mean");

  print("Pooled FLAC shape:", flac_pooled.shape)
  print("Pooled HLS shape:", hls_pooled.shape)

  utils.save_tensor(flac_pooled, "embeddings/pooled_flac.pt")
  utils.save_tensor(hls_pooled, "embeddings/pooled_hls.pt")

if __name__ == "__main__":
  main()
