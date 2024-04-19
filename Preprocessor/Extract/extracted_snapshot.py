import json
import os
from typing import List
import xxhash

from Shared.utils import get_output_path

import Preprocessor.Extract.output.path_definitions as ExtractOutputPaths

output_path = get_output_path(
    ExtractOutputPaths, ExtractOutputPaths.EXTRACTED_FILESYSTEM_SNAPSHOT_OUTPUT_NAME
)


def generate_rar_list(root: str):
    files = []
    for fp, dirs, files in os.walk(root):
        for file in files:
            files.append(os.path.join(fp, file))

    return files


def filter_filelist_by_completed(filelist: List[str]):
    # File will be structued as {filename: {hash: str, size: int}}
    # each line in the output file will be a separate JSON object
    with open(output_path, "r", encoding="utf-8") as f:
        completed_files = [json.loads(line) for line in f.readlines()]
        completed_files = {list(file.keys())[0] for file in completed_files}

    return [file for file in filelist if file not in completed_files]


def generate_files_snapshot(filelist: List[str]):
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
    tlmc_root = input("Enter TLMC root path: ")

    if not os.path.exists(tlmc_root):
        print("Invalid path")
        exit(1)

    if not os.path.isfile(output_path):
        with open(output_path, "w", encoding="utf-8") as f:
            pass

    print("Generating file list")
    files = generate_rar_list(tlmc_root)
    print("Total: ", len(files))
    print("Filtering file list")
    files = filter_filelist_by_completed(files)
    print("Filtered Total: ", len(files))
    print("Generating snapshot")
    generate_files_snapshot(files)
