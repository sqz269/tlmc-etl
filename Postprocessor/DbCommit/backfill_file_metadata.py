"""Backfills track durations and asset byte sizes for the v6 database.

The loader never had these: durations live in the FLAC STREAMINFO headers and
byte sizes on the filesystem, neither of which PushToDb touches. This script
produces two CSVs the DB update applies via temp table + UPDATE FROM:

  durations.csv   media_key,duration_seconds   (from FLAC headers, exact)
  byte_sizes.csv  asset_id,byte_size           (stat over asset storage keys)

Durations are read from the source FLACs named by the hls finalizer manifest
(track_dir -> media_key is a relpath from the library root), so exactly the
media-carrying tracks get one — the 811 media-less tracks stay NULL, which is
honest. Asset ids come in via assets.csv, exported from the DB first:

  COPY (SELECT id, storage_key FROM asset) TO STDOUT WITH CSV

content_hash is deliberately NOT here: it needs a full read of every byte in
the library, which is a planned pass of its own, not a side effect.
"""

import csv
import os
import sys
from multiprocessing import Pool

from mutagen.flac import FLAC

import Postprocessor.HlsTranscode.output.path_definitions as HlsOutputPathDef
from Shared import utils
from Shared.json_utils import json_load

LIBRARY_ROOT = "/mnt/tlmc/TLMC v6"
WORKERS = 12

finalized_manifest_path = utils.get_output_path(
    HlsOutputPathDef, HlsOutputPathDef.HLS_FINALIZED_FILELIST_OUTPUT_NAME
)


def read_duration(item):
    flac_path, media_key = item
    try:
        return (media_key, FLAC(flac_path).info.length, None)
    except Exception as e:
        return (media_key, None, f"{type(e).__name__}: {e}")


def stat_size(item):
    asset_id, storage_key = item
    try:
        return (asset_id, os.stat(os.path.join(LIBRARY_ROOT, storage_key)).st_size, None)
    except OSError as e:
        return (asset_id, None, f"{type(e).__name__}: {e}")


def run(items, worker, out_path, label):
    ok = 0
    failures = []
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        with Pool(WORKERS) as pool:
            for i, (key, value, err) in enumerate(
                pool.imap_unordered(worker, items, chunksize=256), 1
            ):
                if err is None:
                    writer.writerow([key, value])
                    ok += 1
                else:
                    failures.append(f"{key} :: {err}")
                if i % 5000 == 0 or i == len(items):
                    print(f"[{label} {i}/{len(items)}] ok {ok}, failed {len(failures)}", end="\r")
    print()
    if failures:
        fail_path = f"{label}_failures.txt"
        with open(fail_path, "w", encoding="utf-8") as f:
            f.write("\n".join(failures) + "\n")
        print(f"{label}: {len(failures)} failures -> {fail_path}")
    return ok, len(failures)


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "."

    manifest = json_load(finalized_manifest_path)
    duration_items = [
        (flac_path, os.path.relpath(entry["track_dir"], LIBRARY_ROOT))
        for flac_path, entry in manifest.items()
    ]
    run(duration_items, read_duration, os.path.join(out_dir, "durations.csv"), "durations")

    assets_csv = os.path.join(out_dir, "assets.csv")
    if not os.path.exists(assets_csv):
        print(f"{assets_csv} not found — export it first:")
        print("  COPY (SELECT id, storage_key FROM asset) TO STDOUT WITH CSV")
        sys.exit(1)

    with open(assets_csv, encoding="utf-8", newline="") as f:
        asset_items = [tuple(row) for row in csv.reader(f)]
    run(asset_items, stat_size, os.path.join(out_dir, "byte_sizes.csv"), "byte_sizes")


if __name__ == "__main__":
    main()
