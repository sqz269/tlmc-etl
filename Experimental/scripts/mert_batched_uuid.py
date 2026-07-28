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

from utils.loader import AudioChunk, SourceFileInfo, load_flac, load_m3u8, load_m4a, ChunkingConfig

from torch.utils.data import DataLoader, IterableDataset

from utils.utils import save_tensor
from utils.journal import RunJournal, scan_completed_ids
import torch.multiprocessing as mp

mp.set_start_method("spawn", force=True)

torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True

# Overridable by environment so the same script runs on a host checkout and
# inside the container, where the repo is bind-mounted and the library sits at
# its own absolute path. The former hardcoded /mnt/j/... CSV path was a WSL drive
# mount that exists on exactly one machine.
DATA_DIRECTORY = os.environ.get("MERT_DATA_DIR") or str(ROOT_DIR / "data")
EMBEDDING_DIRECTORY = os.environ.get("MERT_EMBEDDING_DIR") or str(
  ROOT_DIR / "embeddings" / "chunked_6s"
)
TARGET_CSV = os.environ.get("MERT_TARGET_CSV") or str(
  ROOT_DIR / "data_transfer" / "all_targets.csv"
)

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
  """Deprecated: the O(files) directory walk this used to do on every start.

  Kept only as the seed for RunJournal.load_completed, which calls it once when
  adopting the journal against an embeddings directory that predates it.
  """
  return scan_completed_ids(embedding_dir)

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

def get_m3u8_process_list(dir_path: str, target_csv_path: str, completed: Set[str]) -> List[SourceFileInfo]:
  # target is {"track_id": "m3u8_path"}
  # csv col: AlbumID,TrackID,PlaylistPath
  csv_df = pd.read_csv(target_csv_path)
  targets = csv_df[["TrackID", "PlaylistPath"]].to_dict(orient="records")
  targets = {item["TrackID"]: item["PlaylistPath"] for item in targets}

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

def get_process_list(dir_path: str, completed: Set[str]) -> List[SourceFileInfo]:
  # NOTE if this path is ever revived (main() uses the m3u8 one): `filename` here
  # is a whole basename, whereas the journal keys on whatever `filename` holds and
  # the resume filter below compares bare UUIDs. The m3u8 path sets filename to
  # the track id, so the two agree; this one would need the same before its
  # completed entries could be matched on restart.
  m4a_files = get_m4a_list(dir_path)
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
    journal: RunJournal = None,
  ):
    super().__init__()
    self.flac_list = flac_list
    self.chunking_config = chunking_config
    self.journal = journal

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
        if self.journal is not None:
          self.journal.report_failed(info.filename, fp, e)
        continue

      if len(audio_chunks.chunks) == 0:
        print(f"No audio chunks found in {fp}, skipping.")
        if self.journal is not None:
          self.journal.report_failed(info.filename, fp, "decoded to zero chunks")
        continue

      # yield one chunk at a time
      for idx, chunk in enumerate(audio_chunks.chunks):
        yield chunk

def collate_batch_fn(batch):
  return batch


def save_and_record(
  tensor: torch.Tensor,
  write_path: str,
  track_id: str,
  journal: RunJournal,
) -> None:
  """Persist one track's embedding, then mark it done -- never the other order.

  Runs on the publish thread pool. The completed marker is written only after
  save_tensor's atomic rename has landed, so every id in the journal has a whole
  .pt behind it and resume can trust the list without re-validating files.

  Exceptions are journalled rather than raised: this runs inside executor.submit,
  whose Future nobody reads, so a raise here would vanish silently and the track
  would look complete because the progress bar had already advanced.
  """
  try:
    save_tensor(tensor, write_path)
  except Exception as e:
    journal.report_failed(track_id, write_path, f"save failed: {e}")
    return
  journal.report_completed(track_id)

def embed_waveforms_batched(
  data_set: ChunkStreamDataset,
  model: Any,
  processor: Wav2Vec2FeatureExtractor,
  device: str,
  results: Dict[str, List[torch.Tensor]],
  executor: ThreadPoolExecutor,  # <--- MODIFIED: Accept executor
  journal: RunJournal,
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
          executor.submit(
            save_and_record,
            tensor_stack,
            write_path,
            metadata.source.filename,
            journal,
          )

          # print(f"Saved embedding to {write_path}")
          del results[metadata.source.path]
          file_pbar.update(1)

      # print(f"Processed {len(batch_chunks)} chunks.")


def main():
  intermediate_results: Dict[str, List[torch.Tensor]] = {}

  os.makedirs(EMBEDDING_DIRECTORY, exist_ok=True)

  journal = RunJournal(EMBEDDING_DIRECTORY, name="mert_chunked_6s")
  # Seeds itself from a directory walk the first time only, so switching to the
  # journal does not recompute embeddings an earlier run already produced.
  completed = journal.load_completed(
    rebuild_from=lambda: get_completed_embeddings(EMBEDDING_DIRECTORY)
  )

  # proc_list = get_process_list(DATA_DIRECTORY, completed)
  proc_list = get_m3u8_process_list(DATA_DIRECTORY, TARGET_CSV, completed)
  dataset = ChunkStreamDataset(
    flac_list=proc_list,
    chunking_config=chunking_config,
    journal=journal,
  )

  model, processor, device = init_model()
  try:
    with ThreadPoolExecutor(max_workers=8) as executor:
      embed_waveforms_batched(
        data_set=dataset,
        model=model,
        processor=processor,
        device=device,
        results=intermediate_results,
        executor=executor,  # <--- MODIFIED: Pass the executor
        journal=journal,
        layer_mix="last4",
        # Measured on the RTX 5090 (32 GB), 6 s chunks, output_hidden_states=True:
        #
        #   batch    8   16   32   64   96  128  224
        #   chunks/s 275 320  347  342  354  353   25
        #   VRAM GB  2.5 3.7  6.0 10.8 15.5 20.3  34.6
        #
        # Throughput plateaus from 32 up. 224 -- the previous value -- asks for
        # 34.6 GB on a 32 GB card, spills into host memory over PCIe and runs
        # 14x SLOWER than any batch that fits. 64 sits on the plateau with room
        # for real-audio variance and torch.compile's workspace, and cuts the
        # DataLoader prefetch reservation (workers x prefetch x batch) from
        # ~8 GB of host RAM to ~2.4 GB.
        batch_size=64,
        pin_memory=True,
        num_workers=8,
        prefetch_factor=8,
      )
    # Leaving the `with` block joins the pool, so every queued save has landed
    # and been journalled before anything below runs.

    # Tracks whose chunks were read but never completed a full set: a mid-stream
    # decode failure, or a total_chunks mismatch. They are not on disk and not in
    # the completed list, so a rerun picks them up -- but without this they would
    # leave no trace of having been attempted.
    for src_path, chunks in intermediate_results.items():
      print(f"WARNING: incomplete chunk set, not saved: {src_path}")
      journal.report_failed(
        os.path.splitext(os.path.basename(src_path))[0],
        src_path,
        f"incomplete chunk set: only {len(chunks)} chunks collected",
      )
  finally:
    journal.close()

if __name__ == "__main__":
  main()
