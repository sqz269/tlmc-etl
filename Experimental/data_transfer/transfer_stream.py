from typing import List, Set
from threading import Lock, Thread
from queue import Queue
from dataclasses import dataclass
from google.cloud import storage
import subprocess
import os
import pandas as pd

STAGING_DIRECTORY = "/ssd_staging/transfer"

REMUX_COMPLETED_ITEMS = "/ssd_staging/completed_items.txt"
UPLOAD_COMPLETED_ITEMS = "/ssd_staging/uploaded_items.txt"

# [AlbumID, TrackID, PlaylistPath]
INPUT_CSV = "data_transfer/all_targets.csv"

# rewrite mount points
ROOT_REWRITE = (
  "/external_data/",
  "/tlmc_staging/",
)

# GCS configs
GCS_BUCKET_NAME = "tlmc-processing-data"

# worker counts
REMUX_WORKERS = 4
UPLOAD_WORKERS = 8

# global locks for completion logs
REMUX_COMPLETED_LOCK = Lock()
UPLOAD_COMPLETED_LOCK = Lock()

# GCS client globals
_storage_client = None
_bucket = None
STORAGE_INIT_LOCK = Lock()

@dataclass
class TrackRemuxInfo:
  track_id: str
  playlist_path: str
  remuxed_path: str

  def to_dict(self) -> dict:
    return {
      "track_id": self.track_id,
      "playlist_path": self.playlist_path,
      "remuxed_path": self.remuxed_path,
    }

  @staticmethod
  def from_dict(data: dict) -> "TrackRemuxInfo":
    return TrackRemuxInfo(
      track_id=data["track_id"],
      playlist_path=data["playlist_path"],
      remuxed_path=data["remuxed_path"],
    )


@dataclass
class TrackUploadInfo:
  track_id: str
  remuxed_path: str
  gcs_path: str

  def to_dict(self) -> dict:
    return {
      "track_id": self.track_id,
      "remuxed_path": self.remuxed_path,
      "gcs_path": self.gcs_path,
    }

  @staticmethod
  def from_dict(data: dict) -> "TrackUploadInfo":
    return TrackUploadInfo(
      track_id=data["track_id"],
      remuxed_path=data["remuxed_path"],
      gcs_path=data["gcs_path"],
    )


def get_storage_bucket():
  global _storage_client, _bucket
  if _bucket is None:
    with STORAGE_INIT_LOCK:
      if _bucket is None:
        _storage_client = storage.Client()
        _bucket = _storage_client.bucket(GCS_BUCKET_NAME)
  return _bucket


def get_completed_tracks(completed_items_path: str) -> Set[str]:
  if not os.path.exists(completed_items_path):
    return set()

  with open(completed_items_path, "r") as f:
    return set(line.strip() for line in f if line.strip())


def read_targets(input_csv: str, playlist_path_rewrite: tuple) -> pd.DataFrame:
  csv_df = pd.read_csv(input_csv)

  csv_df["PlaylistPath"] = csv_df["PlaylistPath"].apply(
    lambda p: p.replace(playlist_path_rewrite[0], playlist_path_rewrite[1])
  )

  return csv_df


def remuxed_local_path_for_track(track_id: str) -> str:
  """
  Compute deterministic local path for the remuxed file given a track_id.
  """
  return os.path.join(STAGING_DIRECTORY, f"{track_id}.aac")


def gcs_path_for_track(track_id: str) -> str:
  """
  Compute deterministic GCS path for a given track_id.
  """
  return f"{track_id}.aac"


def df_to_remux_info_list(df: pd.DataFrame) -> List[TrackRemuxInfo]:
  remux_list: List[TrackRemuxInfo] = []
  for _, row in df.iterrows():
    track_id = str(row["TrackID"])
    playlist_path = str(row["PlaylistPath"])
    remuxed_path = remuxed_local_path_for_track(track_id)
    remux_list.append(
      TrackRemuxInfo(
        track_id=track_id,
        playlist_path=playlist_path,
        remuxed_path=remuxed_path,
      )
    )
  return remux_list


def df_to_upload_info_list(df: pd.DataFrame) -> List[TrackUploadInfo]:
  upload_list: List[TrackUploadInfo] = []
  for _, row in df.iterrows():
    track_id = str(row["TrackID"])
    remuxed_path = remuxed_local_path_for_track(track_id)
    gcs_path = gcs_path_for_track(track_id)
    upload_list.append(
      TrackUploadInfo(
        track_id=track_id,
        remuxed_path=remuxed_path,
        gcs_path=gcs_path,
      )
    )
  return upload_list


def remux_playlist_to_aac(playlist_path: str, output_path: str) -> bool:
  cmd = [
    "ffmpeg",
    "-y",
    "-protocol_whitelist",
    "file,http,https,tcp,tls",
    "-i",
    playlist_path,
    "-c",
    "copy",
    "-vn",
    "-bsf:a",
    "aac_adtstoasc",
    output_path,
  ]

  os.makedirs(os.path.dirname(output_path), exist_ok=True)
  try:
    subprocess.run(cmd, check=True)
    return True
  except subprocess.CalledProcessError as e:
    print(f"Error remuxing {playlist_path}: {e}")
    return False


def remux_worker(track_id: str, playlist_path: str) -> bool:
  """
  Remux a single playlist to a local AAC/MP4 (m4a) file.
  Also appends the track_id to REMUX_COMPLETED_ITEMS on success.
  """
  output_path = remuxed_local_path_for_track(track_id)
  success = remux_playlist_to_aac(playlist_path, output_path)
  if success:
    with REMUX_COMPLETED_LOCK:
      with open(REMUX_COMPLETED_ITEMS, "a") as f:
        f.write(track_id + "\n")
  return success


def uploader_worker(track_id: str, remuxed_path: str) -> bool:
  """
  Upload a single remuxed file to GCS.
  Also appends the track_id to UPLOAD_COMPLETED_ITEMS on success.
  """
  if not os.path.exists(remuxed_path):
    print(f"[UPLOAD] Remuxed file not found for {track_id}: {remuxed_path}")
    return False

  bucket = get_storage_bucket()
  blob_name = gcs_path_for_track(track_id)
  blob = bucket.blob(blob_name)

  try:
    blob.upload_from_filename(remuxed_path)
    with UPLOAD_COMPLETED_LOCK:
      with open(UPLOAD_COMPLETED_ITEMS, "a") as f:
        f.write(track_id + "\n")
    print(f"[UPLOAD] Uploaded {track_id} to gs://{GCS_BUCKET_NAME}/{blob_name}")
    return True
  except Exception as e:
    print(f"[UPLOAD] Error uploading {track_id} from {remuxed_path}: {e}")
    return False


def remux_thread_loop(remux_queue: Queue, upload_queue: Queue):
  """
  Thread loop: take TrackRemuxInfo from remux_queue,
  run remux, and on success enqueue TrackUploadInfo to upload_queue.
  """
  while True:
    item: TrackRemuxInfo = remux_queue.get()
    if item is None:  # sentinel
      remux_queue.task_done()
      break

    print(f"[REMUX] Processing TrackID={item.track_id}")
    success = remux_worker(item.track_id, item.playlist_path)

    if success:
      upload_info = TrackUploadInfo(
        track_id=item.track_id,
        remuxed_path=item.remuxed_path,
        gcs_path=gcs_path_for_track(item.track_id),
      )
      upload_queue.put(upload_info)

    remux_queue.task_done()


def upload_thread_loop(upload_queue: Queue):
  """
  Thread loop: take TrackUploadInfo from upload_queue,
  run upload to GCS.
  """
  while True:
    item: TrackUploadInfo = upload_queue.get()
    if item is None:  # sentinel
      upload_queue.task_done()
      break

    print(f"[UPLOAD] Processing TrackID={item.track_id}")
    uploader_worker(item.track_id, item.remuxed_path)

    upload_queue.task_done()


def main():
  os.makedirs(STAGING_DIRECTORY, exist_ok=True)
  os.makedirs(os.path.join(STAGING_DIRECTORY, "remuxed"), exist_ok=True)

  worklist = read_targets(INPUT_CSV, ROOT_REWRITE)
  remux_completed = get_completed_tracks(REMUX_COMPLETED_ITEMS)
  upload_completed = get_completed_tracks(UPLOAD_COMPLETED_ITEMS)

  # determine which tracks still need remux and upload
  df_remux_pending = worklist[~worklist["TrackID"].isin(remux_completed)]
  df_remux_completed = worklist[worklist["TrackID"].isin(remux_completed)]
  df_upload_pending = df_remux_completed[
    ~df_remux_completed["TrackID"].isin(upload_completed)
  ]

  remux_list = df_to_remux_info_list(df_remux_pending)
  upload_list = df_to_upload_info_list(df_upload_pending)

  print(f"Remux pending: {len(remux_list)} tracks")
  print(f"Upload pending from previous runs: {len(upload_list)} tracks")

  remux_queue: Queue = Queue()
  upload_queue: Queue = Queue()

  # seed queues
  for r in remux_list:
    remux_queue.put(r)

  # Already-remuxed-but-not-uploaded get seeded directly into upload queue
  for u in upload_list:
    upload_queue.put(u)

  # start workers
  remux_threads: List[Thread] = []
  for _ in range(REMUX_WORKERS):
    t = Thread(target=remux_thread_loop, args=(remux_queue, upload_queue))
    t.daemon = True
    t.start()
    remux_threads.append(t)

  upload_threads: List[Thread] = []
  for _ in range(UPLOAD_WORKERS):
    t = Thread(target=upload_thread_loop, args=(upload_queue,))
    t.daemon = True
    t.start()
    upload_threads.append(t)

  # wait for all remux tasks to finish
  remux_queue.join()

  # send sentinel to remux workers
  for _ in range(REMUX_WORKERS):
    remux_queue.put(None)
  for t in remux_threads:
    t.join()

  # now wait for all upload tasks (including ones generated by remux workers)
  upload_queue.join()

  # send sentinel to upload workers
  for _ in range(UPLOAD_WORKERS):
    upload_queue.put(None)
  for t in upload_threads:
    t.join()

  print("All remux and upload tasks completed.")


if __name__ == "__main__":
  main()
