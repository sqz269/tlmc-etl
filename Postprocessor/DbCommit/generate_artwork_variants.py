"""Generates artwork variant images and dominant colors for the v6 database.

SCHEMA-V6.md section 13 step 4, which v5 ran inside the backend at application
startup (UpdateDb.GenerateAlbumThumbnail) and v6 evicted without a replacement:
every artwork row currently has an empty variant ladder and colors = '{}'.

Variant files are written into the library root under _derived/artwork/, NOT a
separate thumbnail volume: the library is the one filesystem both this machine
and the API pod already share, and asset rows are (root, key) pairs, so serving
them requires no deployment change.

Reads artworks.csv, exported from the DB first (idempotent: only artworks with
no variants at all are exported):

  COPY (
    SELECT a.id, a.source_asset_id, s.storage_key
    FROM artwork a
    JOIN asset s ON s.id = a.source_asset_id
    WHERE NOT EXISTS (SELECT 1 FROM artwork_variant v WHERE v.artwork_id = a.id)
  ) TO STDOUT WITH CSV

Produces three CSVs applied by apply_artwork_variants.sql (temp table + insert,
conflict-safe, one transaction):

  variant_files.csv  asset_id,storage_key,name,mime,byte_size   (new asset rows)
  variants.csv       artwork_id,size_px,asset_id                (the ladder;
                     size 0 references the existing source asset — the original
                     becomes addressable through the ladder without copying it)
  colors.csv         artwork_id,{#rrggbb,...}                   (dominant first)

content_hash is deliberately NOT set here — same reasoning as
backfill_file_metadata.py: hashing is its own planned pass.
"""

import csv
import os
import sys
import uuid
from multiprocessing import Pool

from PIL import Image

LIBRARY_ROOT = "/mnt/tlmc/TLMC v6"
DERIVED_PREFIX = "_derived/artwork"

# Longest-edge targets. Adding a size later is an insert (SCHEMA-V6.md section
# 6); sizes at or above the original's longest edge are skipped, never upscaled.
LADDER = (120, 300, 600)
JPEG_QUALITY = 85
DOMINANT_COLORS = 8
WORKERS = 12

Image.MAX_IMAGE_PIXELS = None  # scans legitimately exceed the decompression-bomb default


def _dominant_colors(image):
    """Pixel-share-ordered hex colors from an adaptive 8-color quantization of
    a 100px copy — the v5 backend's octree approach, in Pillow terms."""
    probe = image.convert("RGB").copy()
    probe.thumbnail((100, 100), Image.Resampling.NEAREST)
    quantized = probe.quantize(colors=DOMINANT_COLORS)
    palette = quantized.getpalette()
    counts = sorted(quantized.getcolors(), reverse=True)
    return [
        "#{:02x}{:02x}{:02x}".format(*palette[index * 3 : index * 3 + 3])
        for _, index in counts
    ]


def process_artwork(item):
    artwork_id, source_asset_id, storage_key = item
    try:
        out_dir = os.path.join(LIBRARY_ROOT, DERIVED_PREFIX, artwork_id)
        os.makedirs(out_dir, exist_ok=True)

        with Image.open(os.path.join(LIBRARY_ROOT, storage_key)) as image:
            colors = _dominant_colors(image)

            files = []
            longest = max(image.size)
            for size in LADDER:
                if size >= longest:
                    continue
                scaled = image.convert("RGB")
                scaled.thumbnail((size, size), Image.Resampling.LANCZOS)
                name = f"{size}.jpg"
                path = os.path.join(out_dir, name)
                scaled.save(path, "JPEG", quality=JPEG_QUALITY)
                files.append(
                    (size, f"{DERIVED_PREFIX}/{artwork_id}/{name}", name, os.path.getsize(path))
                )

        return (artwork_id, source_asset_id, files, colors, None)
    except Exception as e:  # noqa: BLE001 - per-item failures are data, not crashes
        return (artwork_id, source_asset_id, None, None, f"{type(e).__name__}: {e}")


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "."

    artworks_csv = os.path.join(out_dir, "artworks.csv")
    if not os.path.exists(artworks_csv):
        print(f"{artworks_csv} not found — export it first (see module docstring)")
        sys.exit(1)

    with open(artworks_csv, encoding="utf-8", newline="") as f:
        items = [tuple(row) for row in csv.reader(f)]

    ok = 0
    failures = []
    with (
        open(os.path.join(out_dir, "variant_files.csv"), "w", encoding="utf-8", newline="") as files_f,
        open(os.path.join(out_dir, "variants.csv"), "w", encoding="utf-8", newline="") as variants_f,
        open(os.path.join(out_dir, "colors.csv"), "w", encoding="utf-8", newline="") as colors_f,
    ):
        files_writer = csv.writer(files_f)
        variants_writer = csv.writer(variants_f)
        colors_writer = csv.writer(colors_f)

        with Pool(WORKERS) as pool:
            for i, (artwork_id, source_asset_id, files, colors, err) in enumerate(
                pool.imap_unordered(process_artwork, items, chunksize=16), 1
            ):
                if err is None:
                    variants_writer.writerow([artwork_id, 0, source_asset_id])
                    for size, key, name, byte_size in files:
                        asset_id = str(uuid.uuid4())
                        files_writer.writerow([asset_id, key, name, "image/jpeg", byte_size])
                        variants_writer.writerow([artwork_id, size, asset_id])
                    colors_writer.writerow([artwork_id, "{" + ",".join(colors) + "}"])
                    ok += 1
                else:
                    failures.append(f"{artwork_id} :: {err}")
                if i % 500 == 0 or i == len(items):
                    print(f"[variants {i}/{len(items)}] ok {ok}, failed {len(failures)}", end="\r")
    print()

    if failures:
        fail_path = os.path.join(out_dir, "variants_failures.txt")
        with open(fail_path, "w", encoding="utf-8") as f:
            f.write("\n".join(failures) + "\n")
        print(f"variants: {len(failures)} failures -> {fail_path}")

    print(f"done: {ok} artworks; apply with: psql -f apply_artwork_variants.sql (from {out_dir})")


if __name__ == "__main__":
    main()
