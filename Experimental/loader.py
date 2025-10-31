from typing import Tuple
import numpy as np
import soundfile as sf


def load_flac(fp: str) -> Tuple[np.ndarray, int]:
  wav_np, sr = sf.read(fp)
  if len(wav_np.shape) > 1:
    wav_np = wav_np.mean(axis=1)  # Convert to mono by averaging channels
  return wav_np, sr