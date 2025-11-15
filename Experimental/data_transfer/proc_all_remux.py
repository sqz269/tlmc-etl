from tqdm import tqdm
import os

from utils.common import (
  STAGING_DIRECTORY,
  ROOT_REWRITE,
  INPUT_CSV,
  REMUX_COMPLETED_ITEMS,
  read_targets,
  get_completed_tracks,
  df_to_remux_info_list,
  remux_worker,
  remuxed_local_path_for_track,
)


def main():
  os.makedirs(STAGING_DIRECTORY, exist_ok=True)
  os.makedirs(os.path.join(STAGING_DIRECTORY, "remuxed"), exist_ok=True)

  worklist = read_targets(INPUT_CSV, ROOT_REWRITE)
  remux_completed = get_completed_tracks(REMUX_COMPLETED_ITEMS)

  # pending = not in remux-completed log
  df_remux_pending = worklist[~worklist["TrackID"].isin(remux_completed)]
  remux_list = df_to_remux_info_list(df_remux_pending)

  total = len(remux_list)
  print(f"Remux pending: {total} tracks out of {len(worklist)} total tracks ({len(remux_completed)} already remuxed)")

  succeeded = 0
  failed_ids = []

  for item in tqdm(remux_list, desc="Remuxing", unit="track"):
    ok = remux_worker(item.track_id, item.playlist_path)
    if ok:
      succeeded += 1
    else:
      failed_ids.append(item.track_id)

  failed = len(failed_ids)

  print("\n=== REMUX STAGE SUMMARY ===")
  print(f"Total attempted: {total}")
  print(f"Succeeded   : {succeeded}")
  print(f"Failed    : {failed}")

  if failed_ids:
    # only print a small sample to avoid huge logs
    preview = ", ".join(failed_ids[:10])
    print(f"Failed TrackIDs (first 10): {preview}")
    if failed > 10:
      print(f"... and {failed - 10} more")


if __name__ == "__main__":
  main()
