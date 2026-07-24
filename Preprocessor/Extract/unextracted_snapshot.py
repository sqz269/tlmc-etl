"""
Hashes the archives of a release before extraction.

The snapshot is the baseline for identifying what changed in the *next* release
without reprocessing everything. Note that a hash only carries across releases
while the container format stays the same: v4 shipped `.rar` and v6 ships `.7z`,
so no v4 hash matches a v6 archive even for byte-identical album contents.
Across such a change the album path is the only usable identity.
"""

import json
import os
from typing import List

import xxhash

import Preprocessor.Extract.output.path_definitions as ExtractOutputPaths
from Shared.utils import get_output_path

ARCHIVE_EXTENSIONS = (".7z", ".zip", ".rar")

output_path = get_output_path(
    ExtractOutputPaths, ExtractOutputPaths.UNEXTRACTED_RAR_SNAPSHOT_OUTPUT_NAME
)


def generate_archive_list(root: str):
    archives = []
    for fp, dirs, files in os.walk(root):
        for file in files:
            if file.lower().endswith(ARCHIVE_EXTENSIONS):
                archives.append(os.path.join(fp, file))

    return archives


def filter_archive_list_by_completed(filelist: List[str]):
    # File is structured as {filename: {hash: str, size: int}}
    # with each line in the output file being a separate JSON object
    with open(output_path, "r", encoding="utf-8") as f:
        completed_files = [json.loads(line) for line in f.readlines()]
        completed_files = {list(file.keys())[0] for file in completed_files}

    return [file for file in filelist if file not in completed_files]


def generate_archive_snapshot(filelist: List[str]):
    for idx, file in enumerate(filelist):
        with open(file, "rb") as f:
            print(f"[{idx}/{len(filelist)}] Hashing {file}", end="\r")

            # Stream hash the file
            hash = xxhash.xxh128()
            while True:
                data = f.read(4096)
                if not data:
                    break
                hash.update(data)

            size = os.path.getsize(file)

            obj = {
                file: {
                    "hash": hash.hexdigest(),
                    "size": size,
                }
            }

            with open(output_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    tlmc_root = input("Enter TLMC release root: ")

    if not os.path.exists(tlmc_root):
        print("Invalid path")
        exit(1)

    if not os.path.isfile(output_path):
        with open(output_path, "w", encoding="utf-8") as f:
            pass

    print("Generating archive file list...")
    archives = generate_archive_list(tlmc_root)
    print(f"Found {len(archives)} archives")
    print("Filtering archive list by completed...")
    archives = filter_archive_list_by_completed(archives)
    print(f"Filtered to {len(archives)} archives")
    generate_archive_snapshot(archives)
