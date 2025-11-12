from tqdm import tqdm
import os

from data_transfer.utils.common import (
  STAGING_DIRECTORY,
  ROOT_REWRITE,
  INPUT_CSV,
  REMUX_COMPLETED_ITEMS,
  UPLOAD_COMPLETED_ITEMS,
  read_targets,
  get_completed_tracks,
  df_to_upload_info_list,
  uploader_worker,
)


def main():
  os.makedirs(STAGING_DIRECTORY, exist_ok=True)
  os.makedirs(os.path.join(STAGING_DIRECTORY, "remuxed"), exist_ok=True)

  worklist = read_targets(INPUT_CSV, ROOT_REWRITE)

  remux_completed = get_completed_tracks(REMUX_COMPLETED_ITEMS)
  upload_completed = get_completed_tracks(UPLOAD_COMPLETED_ITEMS)

  # only tracks that have been remuxed can be uploaded
  df_ready_for_upload = worklist[worklist["TrackID"].isin(remux_completed)]
  df_upload_pending = df_ready_for_upload[
    ~df_ready_for_upload["TrackID"].isin(upload_completed)
  ]

  upload_list = df_to_upload_info_list(df_upload_pending)

  total = len(upload_list)
  print(f"Upload pending: {total} tracks")

  succeeded = 0
  failed_ids = []

  for item in tqdm(upload_list, desc="Uploading", unit="track"):
    ok = uploader_worker(item.track_id, item.remuxed_path)
    if ok:
      succeeded += 1
    else:
      failed_ids.append(item.track_id)

  failed = len(failed_ids)

  print("\n=== UPLOAD STAGE SUMMARY ===")
  print(f"Total attempted: {total}")
  print(f"Succeeded   : {succeeded}")
  print(f"Failed    : {failed}")

  if failed_ids:
    preview = ", ".join(failed_ids[:10])
    print(f"Failed TrackIDs (first 10): {preview}")
    if failed > 10:
      print(f"... and {failed - 10} more")


if __name__ == "__main__":
  main()
