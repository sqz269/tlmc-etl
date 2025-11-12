from typing import List, Set
from dataclasses import dataclass
from google.cloud import storage
import subprocess
import os
import pandas as pd

# ------------------------------------------------------------------------------
# Dataclasses
# ------------------------------------------------------------------------------

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


# ------------------------------------------------------------------------------
# Paths / configs
# ------------------------------------------------------------------------------

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

_storage_client = None
_bucket = None


# ------------------------------------------------------------------------------
# Basic helpers
# ------------------------------------------------------------------------------

def get_storage_bucket():
  """Lazy-init and return the GCS bucket."""
  global _storage_client, _bucket
  if _bucket is None:
    _storage_client = storage.Client()
    _bucket = _storage_client.bucket(GCS_BUCKET_NAME)
  return _bucket


def get_completed_tracks(completed_items_path: str) -> Set[str]:
  if not os.path.exists(completed_items_path):
    return set()

  with open(completed_items_path, "r") as f:
    return set(line.strip() for line in f if line.strip())

# def append_completed_track_immediate(completed_items_path: str, track_id: str) -> None:
#     os.makedirs(os.path.dirname(completed_items_path), exist_ok=True)
#     with open(completed_items_path, "a") as f:
#       f.write(track_id + "\n")

append_logs = {}
appended = 0
def append_completed_track(completed_items_path: str, track_id: str) -> None:
  append_logs.setdefault(completed_items_path, [])
  append_logs[completed_items_path].append(track_id)
  global appended
  appended += 1
  if appended < 100:
    return

  print("Flushing append logs...")
  for path, ids in append_logs.items():
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
      for tid in ids:
          f.write(tid + "\n")
  append_logs.clear()
  appended = 0
  
def read_targets(input_csv: str, playlist_path_rewrite: tuple) -> pd.DataFrame:
  csv_df = pd.read_csv(input_csv)

  csv_df["PlaylistPath"] = csv_df["PlaylistPath"].apply(
    lambda p: p.replace(playlist_path_rewrite[0], playlist_path_rewrite[1])
  )

  return csv_df


def remuxed_local_path_for_track(track_id: str) -> str:
  """Compute deterministic local path for the remuxed file given a track_id."""
  return os.path.join(STAGING_DIRECTORY, "remuxed", f"{track_id}.m4a")


def gcs_path_for_track(track_id: str) -> str:
  """Compute deterministic GCS path for a given track_id."""
  return f"remuxed/{track_id}.m4a"


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


# ------------------------------------------------------------------------------
# Workers
# ------------------------------------------------------------------------------

def remux_playlist_to_aac(playlist_path: str, output_path: str) -> bool:
  cmd = [
    "ffmpeg",
    "-y",
    "-hide_banner",
    "-loglevel",
    "error",
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
    append_completed_track(REMUX_COMPLETED_ITEMS, track_id)
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
    append_completed_track(UPLOAD_COMPLETED_ITEMS, track_id)
    return True
  except Exception as e:
    print(f"[UPLOAD] Error uploading {track_id} from {remuxed_path}: {e}")
    return False
