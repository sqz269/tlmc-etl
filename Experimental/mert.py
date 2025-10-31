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
  # resample if needed
  sr = processor.sampling_rate
  if sr_in != sr:
    wav = torch.from_numpy(wav_np)
    wav = T.Resample(sr_in, sr)(wav).numpy()
  else:
    wav = wav_np

  # processor expects float32 mono 1D array
  inputs = processor(wav.astype(np.float32), sampling_rate=sr, return_tensors="pt")
  inputs = {k: v.to(device) for k, v in inputs.items()}

  with torch.inference_mode():
    out = model(**inputs, output_hidden_states=True)
    # hidden_states: tuple(len=L+1 if includes conv feats); use last 25 for transformer blocks
    hs = torch.stack(
      out.hidden_states
    )  # [layers, B, T, C] or [layers, T, C] depending on model
    if hs.dim() == 3:  # [layers, T, C]
      hs = hs.unsqueeze(1)  # -> [layers, 1, T, C]
    hs = hs[:, 0]  # [layers, T, C]

    # time pooling (mean over frames)
    hs_time = hs.mean(dim=1)  # [layers, C]

    # layer mixing
    if layer_mix == "last":
      vec = hs_time[-1]
    elif layer_mix == "last4":
      vec = hs_time[-4:].mean(dim=0)
    elif layer_mix == "mid":
      mid = hs_time.shape[0] // 2
      vec = hs_time[mid]
    else:
      raise ValueError("layer_mix must be one of {'last','last4','mid'}")

    # L2 normalize
    vec = torch.nn.functional.normalize(vec, p=2, dim=0)  # [C]
    return vec.detach().cpu().numpy()
