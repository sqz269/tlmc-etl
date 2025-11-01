import os
from typing import List, Tuple, Iterable
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
import torchaudio.transforms as T
from transformers import AutoModel, Wav2Vec2FeatureExtractor


device = "cuda" if torch.cuda.is_available() else "cpu"
model = (
  AutoModel.from_pretrained("m-a-p/MERT-v1-330M", trust_remote_code=True)
  .to(device)
  .eval()
)
processor = Wav2Vec2FeatureExtractor.from_pretrained(
  "m-a-p/MERT-v1-330M", trust_remote_code=True
)

def embed_waveform(wav_np: np.ndarray, sr_in: int, layer_mix="last4"):
  # ensure mono (N,) and float32
  if wav_np.ndim == 2:
    wav_np = wav_np.mean(axis=0)
  wav_np = wav_np.astype(np.float32, copy=False)

  # resample if needed
  sr = processor.sampling_rate
  if sr_in != sr:
    wav_t = torch.from_numpy(wav_np)
    resampler = T.Resample(sr_in, sr, dtype=torch.float32)
    wav_t = resampler(wav_t)
    wav_np = wav_t.numpy()

  # processor pads/normalizes as needed
  inputs = processor(wav_np, sampling_rate=sr, return_tensors="pt")
  inputs = {k: v.to(device) for k, v in inputs.items()}

  with torch.inference_mode():
    out = model(**inputs, output_hidden_states=True)
    hs = torch.stack(out.hidden_states)   # [L, B, T, C]
    hs = hs[:, 0]                         # [L, T, C]
    hs_time = hs.mean(dim=1)              # [L, C]

    if layer_mix == "last":
      vec = hs_time[-1]
    elif layer_mix == "last4":
      vec = hs_time[-4:].mean(dim=0)
    elif layer_mix == "mid":
      vec = hs_time[hs_time.shape[0] // 2]
    else:
      raise ValueError("layer_mix must be one of {'last','last4','mid'}")

    vec = torch.nn.functional.normalize(vec, p=2, dim=0)
    return vec.detach().cpu()


class ChunkDataset(Dataset):
  def __init__(self, chunks: List[np.ndarray], sr_in: int, sr_out: int):
    self.chunks = chunks
    self.sr_in = sr_in
    self.sr_out = sr_out

  def __len__(self) -> int:
    return len(self.chunks)

  def _to_mono_f32(self, x: np.ndarray) -> np.ndarray:
    if x.ndim == 2:
      x = x.mean(axis=0)
    return x.astype(np.float32, copy=False)

  def __getitem__(self, idx: int) -> np.ndarray:
    wav = self._to_mono_f32(self.chunks[idx])
    if self.sr_in != self.sr_out:
      wav_t = torch.from_numpy(wav)  # float32
      resampler = T.Resample(self.sr_in, self.sr_out, dtype=torch.float32)
      wav_t = resampler(wav_t)       # float32
      wav = wav_t.numpy()
    return wav  # 1D float32 @ sr_out


def collate_raw_wavs(batch: List[np.ndarray]) -> List[np.ndarray]:
  return batch

def embed_waveforms_batched(
  chunks: List[np.ndarray],
  sr_in: int,
  layer_mix: str = "last4",
  batch_size: int = 8,
  num_workers: int = max(os.cpu_count() - 1, 0), # type: ignore
  pin_memory: bool = True,
) -> torch.Tensor:
  """
  Parallel CPU preprocessing via DataLoader workers + batched GPU inference.
  Returns an array of shape [N, D].
  """
  sr = processor.sampling_rate
  ds = ChunkDataset(chunks, sr_in=sr_in, sr_out=sr)
  dl = DataLoader(
    ds,
    batch_size=batch_size,
    shuffle=False,
    num_workers=num_workers,
    pin_memory=pin_memory,
    collate_fn=collate_raw_wavs,
    persistent_workers=num_workers > 0,
  )

  all_vecs = []
  model.eval()
  with torch.inference_mode():
    for wav_list in dl:
      # Use the processor to pad and batch
      inputs = processor(
        wav_list,
        sampling_rate=sr,
        return_tensors="pt",
        padding=True
      )
      inputs = {k: v.to(device, non_blocking=True) for k, v in inputs.items()}

      out = model(**inputs, output_hidden_states=True)
      # out.hidden_states: tuple of [layer tensors (B, T, C)] per layer
      # Stack to [L, B, T, C]
      hs = torch.stack(out.hidden_states)       # [L, B, T, C]
      hs_time = hs.mean(dim=2)                  # [L, B, C]

      if layer_mix == "last":
        vec = hs_time[-1]                       # [B, C]
      elif layer_mix == "last4":
        vec = hs_time[-4:].mean(dim=0)          # [B, C]
      elif layer_mix == "mid":
        mid = hs_time.shape[0] // 2
        vec = hs_time[mid]                      # [B, C]
      else:
        raise ValueError("layer_mix must be one of {'last','last4','mid'}")

      vec = torch.nn.functional.normalize(vec, p=2, dim=-1)
      all_vecs.append(vec.detach().cpu())

  return torch.cat(all_vecs, dim=0)     # [N, C]
