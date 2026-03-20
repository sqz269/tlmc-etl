import argparse
import os
import sys
from pathlib import Path
from typing import List, Tuple, Union

import torch
from transformers import AutoModel, Wav2Vec2FeatureExtractor

# Add root dir to sys path to ensure local imports work
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

# Local imports
from utils.loader import SourceFileInfo, load_flac, ChunkingConfig
from utils import utils

MERT_SAMPLE_RATE = 24000
# Supported audio extensions for folder scanning
AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".ogg", ".m4a"}

chunking_config = ChunkingConfig(
  target_sample_rate=MERT_SAMPLE_RATE,
  chunk_size=6,
  overlap_size=2,
)

def init_model() -> Tuple[AutoModel, Wav2Vec2FeatureExtractor, str]:
  device = "cuda" if torch.cuda.is_available() else "cpu"
  print(f"Loading model on {device}...")
  
  model = (
    AutoModel.from_pretrained("m-a-p/MERT-v1-330M", trust_remote_code=True)
    .to(device)
    .eval()
  )
  
  processor = Wav2Vec2FeatureExtractor.from_pretrained(
    "m-a-p/MERT-v1-330M", trust_remote_code=True
  )

  return model, processor, device

def process_single_file(
  input_path: Path,
  output_path: Path,
  model: AutoModel,
  processor: Wav2Vec2FeatureExtractor,
  device: str,
  batch_size: int = 32
):
  # 1. Setup metadata wrapper
  source_info = SourceFileInfo(
    path=str(input_path),
    tag="single_run", 
    filename=input_path.stem
  )

  # 2. Load Audio
  # print(f"Processing: {input_path.name}")
  try:
    audio_container = load_flac(
      file=source_info,
      chunking_config=chunking_config,
    )
  except Exception as e:
    print(f"Error loading {input_path.name}: {e}")
    return

  chunks = audio_container.chunks
  if not chunks:
    print(f"Skipping {input_path.name}: No audio chunks found (file too short?).")
    return

  # 3. Process in batches
  embeddings = []
  
  for i in range(0, len(chunks), batch_size):
    batch = chunks[i : i + batch_size]
    wav_list = [ch.data for ch in batch]

    inputs = processor(
      wav_list,
      sampling_rate=MERT_SAMPLE_RATE,
      return_tensors="pt",
      padding=True   
    )
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.inference_mode():
      with torch.amp.autocast("cuda", dtype=torch.float16) if device == "cuda" else torch.autocast("cpu"):
        outputs = model(**inputs, output_hidden_states=True)

    # Aggregation: Last 4 layers mean
    hs = torch.stack(outputs.hidden_states, dim=0)  
    hs_time = hs.mean(dim=2)            
    vec = hs_time[-4:].mean(dim=0)          

    vec = torch.nn.functional.normalize(vec, p=2, dim=-1)
    embeddings.append(vec.cpu())

  # 4. Save results
  if embeddings:
    final_tensor = torch.cat(embeddings, dim=0)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    utils.save_tensor(final_tensor, str(output_path))
    print(f"Saved: {output_path.name}")

def main():
  parser = argparse.ArgumentParser(description="Generate MERT embeddings. Supports single file or folder (delta scan).")
  parser.add_argument("input", help="Path to input file OR folder of audio files")
  parser.add_argument("output", help="Path to output file OR folder for .pt files")
  parser.add_argument("--batch-size", type=int, default=32, help="Inference batch size")
  
  args = parser.parse_args()
  
  input_path = Path(args.input)
  output_path = Path(args.output)

  if not input_path.exists():
    print(f"Error: Input '{input_path}' does not exist.")
    sys.exit(1)

  # --- Mode Selection ---
  is_batch_mode = input_path.is_dir()

  files_to_process: List[Tuple[Path, Path]] = []

  if is_batch_mode:
    if output_path.exists() and not output_path.is_dir():
      print("Error: Input is a directory, but output is a file. Output must be a directory.")
      sys.exit(1)
    
    print(f"Scanning folder: {input_path}")
    
    # Scan folder for valid audio
    for f in input_path.iterdir():
      if f.suffix.lower() in AUDIO_EXTENSIONS:
        # define expected output filename
        target_out = output_path / f"{f.stem}.pt"
        
        # Delta check: Does output exist?
        if not target_out.exists():
          files_to_process.append((f, target_out))
        # else:
        #   print(f"Skipping {f.name} (already exists)")
    
    print(f"Found {len(files_to_process)} files to process (Delta scan complete).")
    
  else:
    # Single file mode
    # If output is a directory, append the input filename with .pt extension
    if output_path.is_dir():
      target_out = output_path / f"{input_path.stem}.pt"
    else:
      target_out = output_path
      
    files_to_process.append((input_path, target_out))

  if not files_to_process:
    print("Nothing to process.")
    return

  # --- Initialization & Execution ---
  model, processor, device = init_model()

  for in_file, out_file in files_to_process:
    process_single_file(
      input_path=in_file,
      output_path=out_file,
      model=model,
      processor=processor,
      device=device,
      batch_size=args.batch_size
    )

if __name__ == "__main__":
  main()