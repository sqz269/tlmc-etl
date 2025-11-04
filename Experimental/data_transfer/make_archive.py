import subprocess
import tarfile
import os
from typing import List
import shlex

# rewrite mount points
ROOT_REWRITE = (
  "/external_data/",
  "/tlmc_staging/"
)

TAR_OUTPUT_ROOT = "/ssd_staging/archives/"
OUTPUT_NAME = "凋叶棕.tar"
INPUT_CSV = "data_transfer/target_playlists.csv"

REMUX_TMP_DIR = "/ssd_staging/remux_tmp/"

"""
Use this query to extact list of playlist of interest


select hp."HlsPlaylistPath"
from "Tracks" t
join "Albums" a on t."AlbumId" = a."Id"
join "AlbumCircle" ac on T."AlbumId" = ac."AlbumsId"
join "Circles" c on ac."AlbumArtistId" = c."Id"
join "HlsPlaylist" hp on hp."TrackId" = t."Id"
where c."Name" = '凋叶棕'
  and hp."Bitrate" = 320;
"""

def read_targets(input_csv: str):
  targets = []
  with open(input_csv, "r", encoding="utf-8") as f:
    for line in f:
      line = line.strip()
      if line:
        targets.append(line)
  return targets

def remux_playlist_to_wav(playlist_path: str, output_path: str) -> bool:
  cmd = [
    "ffmpeg",
    "-loglevel", "error",
    "-nostdin",
    "-y",
    "-allowed_extensions", "ALL",
    "-protocol_whitelist", "file,crypto,udp,rtp,tcp,tls,https,http,subfile",
    "-i", playlist_path,
    "-vn",
    "-c:a", "copy",
    "-movflags", "+faststart",
    output_path
  ]
  os.makedirs(os.path.dirname(output_path), exist_ok=True)
  try:
    subprocess.run(cmd, check=True)
    return True
  except subprocess.CalledProcessError as e:
    print(f"Error remuxing {playlist_path}: {e}")
    return False

def get_cirle_album_track(playlist_path: str):
  parts = playlist_path.split(os.sep)
  circle = None
  album = None
  track = None

  for i, part in enumerate(parts):
    if part.startswith("[") and part.endswith("]") and circle is None:
      circle = part
      if i + 1 < len(parts):
        album = parts[i + 1]
    if part == "hls":
      if i - 1 >= 0:
        track = parts[i - 1]
      break

  if circle is None or album is None or track is None:
    raise ValueError(f"Could not parse circle, album, or track from {playlist_path}")

  return circle, album, track

def make_archive(source_playlist_list: List[str], target_tar: str) -> None:
  with tarfile.open(target_tar, "w") as tar:
    for playlist_path in source_playlist_list:
      if os.path.exists(playlist_path):
        # TODO Demux the playlist here
        circle, album, track = get_cirle_album_track(playlist_path)
        # detect circle, album, and track
        # circle regex: ^\[.+\]$
        # album is right after circle
        # track is right before hls/
        remuxed_file_path = os.path.join(
          REMUX_TMP_DIR,
          circle,
          album,
          f"{track}.m4a"
        )

        print(f"Remuxing {playlist_path}...")
        success = remux_playlist_to_wav(playlist_path, remuxed_file_path)
        if success:
          print(f"Adding {remuxed_file_path} to archive...")
          tar.add(remuxed_file_path, arcname=os.path.basename(remuxed_file_path))
        else:
          print(f"Failed to remux {playlist_path}, skipping...")
      else:
        print(f"Warning: {playlist_path} does not exist and will be skipped.")

def main():
  targets = read_targets(INPUT_CSV)
  # rewrite target paths for mount points
  rewrited_targets = [
    t.replace(ROOT_REWRITE[0], ROOT_REWRITE[1]) for t in targets
  ]

  os.makedirs(REMUX_TMP_DIR, exist_ok=True)
  os.makedirs(TAR_OUTPUT_ROOT, exist_ok=True)

  target = os.path.join(TAR_OUTPUT_ROOT, OUTPUT_NAME)
  make_archive(rewrited_targets, target)

if __name__ == "__main__":
  main()
