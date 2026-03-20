import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Tuple

import torch
from tqdm import tqdm
import itertools
from transformers import AutoModel, Wav2Vec2FeatureExtractor

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from utils.loader import AudioChunk, SourceFileInfo, load_flac, ChunkingConfig

from torch.utils.data import DataLoader, IterableDataset
from torch.cuda.amp import autocast

from utils import utils

DATA_DIRECTORY = str(ROOT_DIR / "data" / "artist_arsmagna" / "[ignore][ArsMagnA]")

MERT_SAMPLE_RATE = 24000
EMBEDDING_DIRECTORY = str(ROOT_DIR / "embeddings" / "chunks_30s_ars")

chunking_config = ChunkingConfig(
  target_sample_rate=MERT_SAMPLE_RATE,
  chunk_size=30,
  overlap_size=5,
)

def init_model() -> Tuple[AutoModel, Wav2Vec2FeatureExtractor, str]:
  device = "cuda" if torch.cuda.is_available() else "cpu"
  model = (
    AutoModel.from_pretrained("m-a-p/MERT-v1-330M", trust_remote_code=True)
    .to(device)
    .eval()
  )

  if torch.cuda.is_available():
    model = torch.compile(model, mode="reduce-overhead", fullgraph=False)

  processor = Wav2Vec2FeatureExtractor.from_pretrained(
    "m-a-p/MERT-v1-330M", trust_remote_code=True
  )

  print(f"Using device: {device}")
  return model, processor, device

class ChunkStreamDataset(IterableDataset):
  def __init__(
    self,
    flac_list: List[SourceFileInfo],
    chunking_config,
  ):
    super().__init__()
    self.flac_list = flac_list
    self.chunking_config = chunking_config

  def __iter__(self) -> Iterator[AudioChunk]:
    worker_info = torch.utils.data.get_worker_info()
    
    if worker_info is None:
      flac_iterator = self.flac_list
    else:
      # make sure each worker loads a disjoint subset of files
      flac_iterator = itertools.islice(
        self.flac_list, worker_info.id, None, worker_info.num_workers)
    
    for info in flac_iterator:
      # print(f"Loading file: {info.path}")
      fp = info.path

      try:
        audio_chunks_hls = load_flac(
          file=info,
          chunking_config=self.chunking_config,
        )
      except Exception as e:
        print(f"Could not load {fp}: {e}")
        continue

      if len(audio_chunks_hls.chunks) == 0:
        print(f"No audio chunks found in {fp}, skipping.")
        continue

      # yield one chunk at a time
      for idx, chunk in enumerate(audio_chunks_hls.chunks):
        yield chunk

def collate_batch_fn(batch):
    return batch

def embed_waveforms_batched(
  data_set: ChunkStreamDataset,
  model: Any,
  processor: Wav2Vec2FeatureExtractor,
  device: str,
  results: Dict[str, List[torch.Tensor]],
  layer_mix: str = "last4",
  batch_size: int = 32,
  pin_memory: bool = True,
  num_workers: int = max(os.cpu_count() - 1, 0), # type: ignore
):
  data_loader: DataLoader = DataLoader(
    data_set,
    batch_size=batch_size,
    pin_memory=pin_memory,
    collate_fn=collate_batch_fn,
    num_workers=num_workers,
    persistent_workers=num_workers > 0,
  )
  
  total_files = len(data_set.flac_list)
  file_pbar = tqdm(
    total=total_files,
    desc="Files processed",
    unit="file",
    position=0,
    leave=True,
  )
  batch_pbar = tqdm(
    desc="Batches processed",
    unit="batch",
    position=1,
    leave=False,
  )

  model.eval()
  with torch.inference_mode():
    batch_chunks: List[AudioChunk]
    for batch_chunks in data_loader:
      batch_pbar.update(1)
      # print("Processing batch of size:", len(batch_chunks))
      wav_list = [ch.data for ch in batch_chunks]  # list[np.ndarray]
      inputs = processor(
        wav_list,
        sampling_rate=MERT_SAMPLE_RATE,
        return_tensors="pt",
        padding=True     
      )
      inputs = {k: v.to(device, non_blocking=True) for k, v in inputs.items()}
      
      with torch.amp.autocast("cuda", dtype=torch.float16):
        outputs = model(**inputs, output_hidden_states=True)

      hs = torch.stack(outputs.hidden_states, dim=0)  # [L, B, T, C]
      hs_time = hs.mean(dim=2)                        # [L, B, C]

      if layer_mix == "last4":
        vec = hs_time[-4:].mean(dim=0)                # [B, C]
      elif layer_mix == "last":
        vec = hs_time[-1]                             # [B, C]
      else:
        raise ValueError("layer_mix must be one of {'last','last4'}")

      vec = torch.nn.functional.normalize(vec, p=2, dim=-1)
      r = vec.detach().cpu() # [B, C]

      # get metadata for each B
      for tensor, metadata in zip(r, batch_chunks):
        if metadata.source.path not in results:
          results[metadata.source.path] = []

        results[metadata.source.path].append(tensor)
        # check if all tensor is collected
        if (metadata.total_chunks == len(results[metadata.source.path])):
          # write to disk
          tensor_stack = torch.stack(tensors=results[metadata.source.path], dim=0) # [chunks, C]
          write_path = os.path.join(
            EMBEDDING_DIRECTORY,
            f"[{metadata.source.tag}] - {metadata.source.filename}.allchunks.pt"
          )
          utils.save_tensor(tensor_stack, write_path)
          # print(f"Saved embedding to {write_path}")
          del results[metadata.source.path]
          file_pbar.update(1)

      # print(f"Processed {len(batch_chunks)} chunks.")

def main():
  intermediate_results: Dict[str, List[torch.Tensor]] = {}

  proc_list = utils.get_process_list(DATA_DIRECTORY, EMBEDDING_DIRECTORY)
  model, processor, device = init_model()
  dataset = ChunkStreamDataset(
    flac_list=proc_list,
    chunking_config=chunking_config,
  )
  
  os.makedirs(EMBEDDING_DIRECTORY, exist_ok=True)
  
  embed_waveforms_batched(
    data_set=dataset,
    model=model,
    processor=processor,
    device=device,
    results=intermediate_results,
    layer_mix="last4",
    batch_size=64,
    pin_memory=True,
    num_workers=8,
  )

if __name__ == "__main__":
  main()
