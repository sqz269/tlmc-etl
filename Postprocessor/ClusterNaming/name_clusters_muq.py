"""Proposes names for the embedding-map clusters by listening to exemplars.

Stage 1 of the genre plan: MERT space has no text alignment, so the 48 k-means
acoustic families on the explore map are anonymous colors. This stage scores a
sample of each cluster (10 medoids + 6 randoms from sample_cluster_tracks.sql)
against a doujin-native vocabulary with MuQ-MuLan (OpenMuQ/MuQ-MuLan-large,
CC-BY-NC 4.0 — fine here, not redistributable commercially), zero-shot.

Clusters are named by LIFT, not raw score: per label z = (cluster mean - global
mean) / global std across all sampled tracks. Raw scores would call every
cluster "rock"; lift asks what a cluster has more of than the library does.

Audio comes from the 128k HLS rung (self-contained fMP4), decoded with PyAV so
no system ffmpeg is needed, resampled to MuQ's 24 kHz, center 30 s.

Reads cluster_sample.csv from the cwd. Writes track_scores.csv (resumable:
already-scored tracks are skipped on rerun) and cluster_names.csv, and prints
the review report. Run:

  uv run --no-project --with muq --with av --with soxr python name_clusters_muq.py
"""

import csv
import os
import sys
import time

import numpy as np

LIBRARY_ROOT = "/mnt/tlmc/TLMC v6"
HLS_RUNG = "hls/128k/stream.m4s"
INPUT_CSV = "cluster_sample.csv"
SCORES_CSV = "track_scores.csv"
NAMES_CSV = "cluster_names.csv"

TARGET_SR = 24000
CLIP_SECONDS = 30

# The vocabulary is the quality lever. Doujin-native styles, phrased the way a
# music caption would read — MuLan-family models were trained on captions.
VOCAB: list[tuple[str, str]] = [
  ("eurobeat", "high energy eurobeat with driving synth riffs and fast beats"),
  ("denpa", "hyperactive cute denpa song with high pitched female vocals"),
  ("piano solo", "solo piano performance"),
  ("orchestral", "epic orchestral arrangement with strings and brass"),
  ("violin classical", "classical violin ensemble chamber piece"),
  ("vocal ballad", "emotional slow ballad with female vocals"),
  ("vocal pop", "upbeat japanese pop song with female vocals"),
  ("vocal rock", "japanese rock song with female vocals and electric guitars"),
  ("vocal trance", "uplifting vocal trance with female vocals and supersaw synths"),
  ("trance", "melodic instrumental trance with supersaw synths"),
  ("metal", "heavy metal with distorted guitars and double bass drums"),
  ("symphonic metal", "symphonic metal with orchestra and heavy guitars"),
  ("instrumental rock", "energetic instrumental rock with electric guitar melodies"),
  ("post-rock", "atmospheric instrumental post rock build up"),
  ("jazz", "jazz combo with swinging piano and walking bass"),
  ("big band", "big band swing with brass section"),
  ("bossa nova", "relaxed bossa nova with nylon guitar"),
  ("celtic folk", "celtic folk with tin whistle fiddle and accordion"),
  ("wagakki", "traditional japanese instruments koto shamisen and taiko drums"),
  ("chiptune", "8-bit chiptune video game music"),
  ("retro game synth", "retro synthesizer video game soundtrack with trumpet lead melody"),
  ("house", "four on the floor house music with piano stabs"),
  ("happy hardcore", "fast happy hardcore rave with pitched up vocals"),
  ("speedcore", "extremely fast aggressive gabber speedcore with distorted kicks"),
  ("drum and bass", "fast breakbeat drum and bass with rolling bassline"),
  ("breakcore", "chaotic breakcore with chopped amen breaks"),
  ("dubstep", "dubstep with heavy wobble bass drops"),
  ("electro swing", "electro swing mixing jazz samples with dance beats"),
  ("hip-hop", "hip hop beat with rap vocals"),
  ("lo-fi", "lofi chill beats with dusty texture"),
  ("ambient", "calm ambient soundscape with soft pads"),
  ("acoustic", "acoustic guitar folk arrangement"),
  ("a cappella", "unaccompanied vocal harmony group a cappella"),
  ("funk", "funk groove with slap bass and horns"),
  ("disco", "disco with four on the floor and strings"),
  ("ska", "upbeat ska with horn section and offbeat guitar"),
  ("techno", "driving techno with repetitive synth stabs"),
  ("synthwave", "retro synthwave with analog synth arpeggios"),
  ("future bass", "future bass with detuned synth chords and vocal chops"),
  ("kawaii edm", "cute kawaii future bass with bright bells and vocal chops"),
  ("hardstyle", "hardstyle with distorted kick and pitched leads"),
  ("eurodance", "90s eurodance with catchy synth hook and dance beat"),
  ("r&b", "smooth rnb with soulful vocals"),
  ("reggae", "laid back reggae with offbeat skank guitar"),
  ("brass march", "military march with brass band and snare drums"),
  ("waltz", "elegant orchestral waltz in three four time"),
  ("tango", "dramatic tango with accordion and strings"),
  ("cinematic epic", "epic cinematic trailer music with choir and percussion"),
  ("choir", "epic choir chanting with orchestra"),
  ("music box", "delicate music box lullaby"),
  ("harpsichord baroque", "baroque harpsichord piece"),
  ("pipe organ", "church pipe organ piece"),
  ("noise experimental", "harsh noise experimental sound collage"),
]


def decode_center_clip(path: str) -> np.ndarray | None:
  import av
  import soxr

  try:
    with av.open(path) as container:
      stream = container.streams.audio[0]
      rate = stream.rate or 44100
      chunks = []
      for frame in container.decode(stream):
        chunks.append(frame.to_ndarray())
  except Exception as error:  # noqa: BLE001 — one bad rip must not kill the run
    print(f"  decode failed: {path}: {error}")
    return None
  if not chunks:
    return None
  audio = np.concatenate(chunks, axis=1).astype(np.float32)
  mono = audio.mean(axis=0)
  mono = soxr.resample(mono, rate, TARGET_SR)
  want = TARGET_SR * CLIP_SECONDS
  if len(mono) > want:
    start = (len(mono) - want) // 2
    mono = mono[start : start + want]
  return mono


def main():
  import torch

  torch.set_num_threads(os.cpu_count() or 8)

  rows = list(csv.reader(open(INPUT_CSV)))
  done: dict[str, list[float]] = {}
  if os.path.exists(SCORES_CSV):
    for row in csv.reader(open(SCORES_CSV)):
      done[row[0]] = [float(v) for v in row[1:]]
    print(f"resuming: {len(done)} tracks already scored")

  from muq import MuQMuLan

  print("loading MuQ-MuLan-large...")
  mulan = MuQMuLan.from_pretrained("OpenMuQ/MuQ-MuLan-large").eval()

  with torch.no_grad():
    text_embeds = mulan(texts=[prompt for _, prompt in VOCAB])
    text_embeds = torch.nn.functional.normalize(text_embeds, dim=-1)

  t0 = time.time()
  pending = [r for r in rows if r[1] not in done]
  scores_file = open(SCORES_CSV, "a", newline="")
  writer = csv.writer(scores_file)
  for i, (cluster, track_id, role, title, media_key) in enumerate(pending):
    clip = decode_center_clip(os.path.join(LIBRARY_ROOT, media_key, HLS_RUNG))
    if clip is None:
      continue
    with torch.no_grad():
      audio_embed = mulan(wavs=torch.from_numpy(clip).unsqueeze(0))
      audio_embed = torch.nn.functional.normalize(audio_embed, dim=-1)
      sims = (audio_embed @ text_embeds.T).squeeze(0).tolist()
    done[track_id] = sims
    writer.writerow([track_id] + [f"{v:.5f}" for v in sims])
    scores_file.flush()
    if (i + 1) % 20 == 0:
      rate = (time.time() - t0) / (i + 1)
      print(
        f"  {i + 1}/{len(pending)} scored, {rate:.1f}s/track, "
        f"~{rate * (len(pending) - i - 1) / 60:.0f} min left"
      )
  scores_file.close()

  # -- aggregate: z-lift per (cluster, label) --------------------------------
  labels = [label for label, _ in VOCAB]
  matrix = np.array([done[r[1]] for r in rows if r[1] in done], dtype=np.float64)
  clusters = np.array([int(r[0]) for r in rows if r[1] in done])
  g_mean = matrix.mean(axis=0)
  g_std = matrix.std(axis=0) + 1e-9

  with open(NAMES_CSV, "w", newline="") as f:
    out = csv.writer(f)
    out.writerow(["cluster", "n_scored", "top_by_lift", "top_raw", "medoid_titles"])
    for c in sorted(set(clusters.tolist())):
      rows_c = matrix[clusters == c]
      z = (rows_c.mean(axis=0) - g_mean) / g_std
      lift_order = np.argsort(-z)[:5]
      raw_order = np.argsort(-rows_c.mean(axis=0))[:3]
      titles = [r[3] for r in rows if int(r[0]) == c and r[2] == "medoid"][:3]
      lift_s = "; ".join(f"{labels[j]} ({z[j]:+.2f})" for j in lift_order)
      raw_s = "; ".join(labels[j] for j in raw_order)
      out.writerow([c, len(rows_c), lift_s, raw_s, " / ".join(titles)])
      print(f"cluster {c:2d} (n={len(rows_c):2d}): {lift_s}")
      print(f"            raw: {raw_s}")
      print(f"            e.g. {' / '.join(titles)}")

  print(f"\nWrote {NAMES_CSV}")


if __name__ == "__main__":
  sys.exit(main())
