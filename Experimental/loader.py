import subprocess
from typing import List
from dataclasses import dataclass
from typing import Tuple
import numpy as np
import soundfile as sf
from torchaudio.io import StreamReader
import torch  # needed because StreamReader yields torch tensors
import torchaudio.transforms as T  # <-- ADDED for resampling


@dataclass
class SourceFileInfo:
  path: str
  filename: str
  tag: str


@dataclass
class ChunkingConfig:
  target_sample_rate: int  # target sample rate after resampling
  chunk_size: int  # in seconds at the target_sample_rate
  overlap_size: int  # in seconds


@dataclass
class AudioChunk:
  source: SourceFileInfo
  data: np.ndarray
  chunk_index: int
  total_chunks: int
  sample_rate: int


@dataclass
class AudioChunks:
  chunks: List[AudioChunk]
  sample_rate: int  # This will be the target_sample_rate
  chunking_config: ChunkingConfig


def chunk_audio(
  wav: np.ndarray, sr: int, config: ChunkingConfig, info: SourceFileInfo
) -> AudioChunks:
  """
  Chunks the given waveform based on the config.
  Assumes wav is already at the config.target_sample_rate.
  """
  target_sr = config.target_sample_rate

  # Check if the provided sample rate matches the target
  if sr != target_sr:
      # This should not happen if upstream functions resample correctly
    raise ValueError(
      f"chunk_audio received SR {sr} but expected {target_sr}. "
      "Audio must be resampled before chunking."
    )

  # Calculate chunk/overlap in samples AT THE TARGET SAMPLE RATE
  chunk_size_samples = int(config.chunk_size * target_sr)
  overlap_size_samples = int(config.overlap_size * target_sr)
  step = chunk_size_samples - overlap_size_samples

  if chunk_size_samples <= 0:
    raise ValueError(
      f"chunk_size ({config.chunk_size}s) results in 0 samples at {target_sr}Hz. Check config."
    )
  if step <= 0:
    raise ValueError(
      "chunk_size and overlap_size result in zero or negative step. "
      "Overlap must be smaller than chunk size."
    )

  chunks: List[AudioChunk] = []
  chunk_id = 0
  for start in range(0, len(wav), step):
    end = start + chunk_size_samples
    if end > len(wav):
      # Original logic: skip the last partial chunk
      break
    chunk = AudioChunk(
      data=wav[start:end],
      source=info,
      chunk_index=chunk_id,
      total_chunks=-1,  # placeholder, will set later
      sample_rate=sr,
    )
    chunks.append(chunk)
    chunk_id += 1

  for chunk in chunks:
    chunk.total_chunks = len(chunks)

  return AudioChunks(chunks=chunks, sample_rate=sr, chunking_config=config)


def load_flac(file: SourceFileInfo, chunking_config: ChunkingConfig) -> AudioChunks:
  wav_np, sr = sf.read(file.path, always_2d=False)
  target_sr = chunking_config.target_sample_rate

  if wav_np.ndim == 2:  # (T, C) -> mono
    wav_np = wav_np.mean(axis=1)

  # ensure float32 in [-1, 1]
  wav_np = wav_np.astype(np.float32, copy=False)

  if sr != target_sr:
    wav_tensor = torch.from_numpy(wav_np)

    resampler = T.Resample(orig_freq=sr, new_freq=target_sr)
    wav_tensor_resampled = resampler(wav_tensor)

    wav_np = wav_tensor_resampled.numpy()
    sr = target_sr  # Update sample rate to new rate

  # Pass the resampled audio and the target SR to chunk_audio
  return chunk_audio(wav_np, sr, chunking_config, info=file)
