from transformers import Wav2Vec2FeatureExtractor, AutoModel
import torch
import torchaudio.transforms as T
import numpy as np

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
    wav_np = wav_np.mean(axis=0)  # average channels
  wav_np = wav_np.astype(np.float32, copy=False)

  # resample if needed (keep input & kernel dtypes aligned)
  sr = processor.sampling_rate
  if sr_in != sr:
    wav_t = torch.from_numpy(wav_np)                     # Float32
    resampler = T.Resample(sr_in, sr, dtype=torch.float32)
    wav_t = resampler(wav_t)                             # Float32
    wav_np = wav_t.numpy()

  # processor expects 1D float32 mono at `sr`
  inputs = processor(wav_np, sampling_rate=sr, return_tensors="pt")
  inputs = {k: v.to(device) for k, v in inputs.items()}

  with torch.inference_mode():
    out = model(**inputs, output_hidden_states=True)
    # hidden_states is a tuple of [layer tensors shaped (B, T, C)]
    hs = torch.stack(out.hidden_states)                  # [L, B, T, C]
    hs = hs[:, 0]                                        # [L, T, C]
    hs_time = hs.mean(dim=1)                             # [L, C]

    if layer_mix == "last":
      vec = hs_time[-1]
    elif layer_mix == "last4":
      vec = hs_time[-4:].mean(dim=0)
    elif layer_mix == "mid":
      vec = hs_time[hs_time.shape[0] // 2]
    else:
      raise ValueError("layer_mix must be one of {'last','last4','mid'}")

    vec = torch.nn.functional.normalize(vec, p=2, dim=0)
    return vec.detach().cpu().numpy()
