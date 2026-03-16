import os
import sys
import re
from typing import Any, Dict, Iterable, Iterator, List, Tuple, Set
from concurrent.futures import ThreadPoolExecutor  # <--- MODIFIED: Added import
from pathlib import Path

import torch
from tqdm import tqdm
import itertools
import pandas as pd
from transformers import AutoModel, Wav2Vec2FeatureExtractor

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from loader import AudioChunk, SourceFileInfo, load_flac, load_m3u8, load_m4a, ChunkingConfig

from torch.utils.data import DataLoader, IterableDataset

from utils.utils import save_tensor
import torch.multiprocessing as mp

mp.set_start_method("spawn", force=True)

torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True

DATA_DIRECTORY = str(ROOT_DIR / "data")
EMBEDDING_DIRECTORY = str(ROOT_DIR / "embeddings" / "chunked_6s")

MERT_SAMPLE_RATE = 24000
chunking_config = ChunkingConfig(
  target_sample_rate=MERT_SAMPLE_RATE,
  chunk_size=6,
  overlap_size=2,
)

UUID_REGEX = re.compile(
  r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

def get_completed_embeddings(embedding_dir: str) -> Set[str]:
  completed: Set[str] = set()
  for fp, _, files in os.walk(embedding_dir):
    for f in files:
      if f.lower().endswith(".pt"):
        item_id = UUID_REGEX.search(f)
        if item_id:
          completed.add(item_id.group(0))

  return completed

def get_m4a_list(dir_path: str) -> Set[str]:
  # genre and list of songs
  m4a_files: Set[str] = set()
  for fp, _, files in os.walk(dir_path):
    for f in files:
      if f.lower().endswith(".m4a"):
        full_path = os.path.join(fp, f)
        # if ("[ignore]" in full_path.lower()):
        #   continue
        m4a_files.add(full_path)

  return m4a_files

def get_m3u8_process_list(dir_path: str, target_csv_path: str, embedding_path: str) -> List[SourceFileInfo]:
  # target is {"track_id": "m3u8_path"}
  # csv col: AlbumID,TrackID,PlaylistPath
  csv_df = pd.read_csv(target_csv_path)
  targets = csv_df[["TrackID", "PlaylistPath"]].to_dict(orient="records")
  targets = {item["TrackID"]: item["PlaylistPath"] for item in targets}

  completed = get_completed_embeddings(embedding_path)
  proc: List[SourceFileInfo] = []
  loaded = 0
  done = 0
  for track_id, m3u8_path in targets.items():
    if track_id in completed:
      done += 1
      continue
    info = SourceFileInfo(
      path=m3u8_path,
      filename=track_id,
      tag="<UNUSED>",
    )
    loaded += 1
    proc.append(info)
  print(f"Total files to process: {loaded}, already done: {done}")
  return proc

def get_process_list(dir_path: str, embedding_path: str) -> List[SourceFileInfo]:
  m4a_files = get_m4a_list(dir_path)
  completed = get_completed_embeddings(embedding_path)
  proc: List[SourceFileInfo] = []
  loaded = 0
  done = 0
  for fp in m4a_files:
    fn = os.path.splitext(os.path.basename(fp))[0]
    item_id = UUID_REGEX.search(fn)
    if item_id and item_id.group(0) in completed:
      done += 1
      continue
    info = SourceFileInfo(
      path=fp,
      filename=fn,
      tag="<UNUSED>",
    )
    loaded += 1
    proc.append(info)

  print(f"Total files to process: {loaded}, already done: {done}")
  return proc

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
        self.flac_list, worker_info.id, None, worker_info.num_workers
      )

    for info in flac_iterator:
      # print(f"Loading file: {info.path}")
      fp = info.path

      try:

        if info.path.endswith(".m3u8"):
          audio_chunks = load_m3u8(
            file=info,
            chunking_config=self.chunking_config,
          )
        else:
          audio_chunks = load_m4a(
            file=info,
            chunking_config=self.chunking_config,
          )
      except Exception as e:
        print(f"Could not load {fp}: {e}")
        continue

      if len(audio_chunks.chunks) == 0:
        print(f"No audio chunks found in {fp}, skipping.")
        continue

      # yield one chunk at a time
      for idx, chunk in enumerate(audio_chunks.chunks):
        yield chunk

def collate_batch_fn(batch):
  return batch

def embed_waveforms_batched(
  data_set: ChunkStreamDataset,
  model: Any,
  processor: Wav2Vec2FeatureExtractor,
  device: str,
  results: Dict[str, List[torch.Tensor]],
  executor: ThreadPoolExecutor,  # <--- MODIFIED: Accept executor
  layer_mix: str = "last4",
  batch_size: int = 32,
  pin_memory: bool = True,
  num_workers: int = max(os.cpu_count() - 1, 0),  # type: ignore
  prefetch_factor: int = 8,
):
  data_loader: DataLoader = DataLoader(
    data_set,
    batch_size=batch_size,
    pin_memory=pin_memory,
    collate_fn=collate_batch_fn,
    prefetch_factor=prefetch_factor,
    num_workers=num_workers,
    persistent_workers=num_workers > 0,
    multiprocessing_context=mp.get_context("spawn"),
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
        padding=True,
      )
      inputs = {k: v.to(device, non_blocking=True) for k, v in inputs.items()}

      with torch.amp.autocast(device_type="cuda", dtype=torch.float16):
        outputs = model(**inputs, output_hidden_states=True)

      hidden = outputs.hidden_states if layer_mix == "last4" else None
      if layer_mix == "last4":
          vec = torch.stack([h.mean(dim=1) for h in hidden[-4:]], dim=0).mean(dim=0)  # [B,C]
      else:  # "last"
          vec = outputs.last_hidden_state.mean(dim=1)  # [B,C]

      vec = torch.nn.functional.normalize(vec, p=2, dim=-1)
      r = vec.detach().cpu()

      # get metadata for each B
      for tensor, metadata in zip(r, batch_chunks):
        if metadata.source.path not in results:
          results[metadata.source.path] = []

        results[metadata.source.path].append(tensor)
        # check if all tensor is collected
        if metadata.total_chunks == len(results[metadata.source.path]):
          # write to disk
          tensor_stack = torch.stack(
            tensors=results[metadata.source.path], dim=0
          )  # [chunks, C]
          write_path = os.path.join(
            EMBEDDING_DIRECTORY,
            f"{metadata.source.filename}.allchunks.pt",
          )
          
          # <--- MODIFIED: Offload saving to the worker thread pool
          executor.submit(save_tensor, tensor_stack, write_path)
          
          # print(f"Saved embedding to {write_path}")
          del results[metadata.source.path]
          file_pbar.update(1)

      # print(f"Processed {len(batch_chunks)} chunks.")


def main():
  intermediate_results: Dict[str, List[torch.Tensor]] = {}

  # proc_list = get_process_list(DATA_DIRECTORY, EMBEDDING_DIRECTORY)
  proc_list = get_m3u8_process_list(DATA_DIRECTORY, "/mnt/j/PROG/tlmc-etl/Experimental/data_transfer/all_targets.csv", EMBEDDING_DIRECTORY)
  dataset = ChunkStreamDataset(
    flac_list=proc_list,
    chunking_config=chunking_config,
  )

  os.makedirs(EMBEDDING_DIRECTORY, exist_ok=True)

  model, processor, device = init_model()
  with ThreadPoolExecutor(max_workers=8) as executor:
    embed_waveforms_batched(
      data_set=dataset,
      model=model,
      processor=processor,
      device=device,
      results=intermediate_results,
      executor=executor,  # <--- MODIFIED: Pass the executor
      layer_mix="last4",
      batch_size=224,
      pin_memory=True,
      num_workers=8,
      prefetch_factor=8,
    )

if __name__ == "__main__":
  main()