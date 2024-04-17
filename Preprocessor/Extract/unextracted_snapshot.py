import json
import os
from typing import List
import xxhash

from Shared.utils import get_self_output_path

from Preprocessor.Extract.output.path_definitions import UNEXTRACTED_RAR_SNAPSHOT_OUTPUT_NAME

output_path = get_self_output_path(__file__, UNEXTRACTED_RAR_SNAPSHOT_OUTPUT_NAME)

def generate_rar_list(root: str):
    rar_files = []
    for fp, dirs, files in os.walk(root):
        files = [f for f in files if f.endswith(".rar")]
        for file in files:
            rar_files.append(os.path.join(fp, file))

    return rar_files


def filter_rar_list_by_completed(filelist: List[str]):
    # File will be structued as {filename: {hash: str, size: int}}
    # each line in the output file will be a separate JSON object
    with open(output_path, "r") as f:
        completed_files = [json.loads(line) for line in f.readlines()]
        completed_files = {file["filename"]: file for file in completed_files}

    return [file for file in filelist if os.path.basename(file) not in completed_files]

def generate_rar_snapshot(filelist: List[str]):
    for idx, file in enumerate(filelist):
        with open(file, "rb") as f:
            print(f"[{idx}/{len(filelist)}] Hashing {file}", end="\r")
            hash = xxhash.xxh3_128_hexdigest(f.read())
            size = os.path.getsize(file)

            obj = {
                file: {
                    "hash": hash,
                    "size": size,
                }
            }

            with open(output_path, "a") as f:
                f.write(json.dumps(obj) + "\n")

if __name__ == "__main__":
    tlmc_root = input("Enter TLMC root path: ")

    print("Generating RAR file list...")
    rar_files = generate_rar_list(tlmc_root)
    print(f"Found {len(rar_files)} RAR files")
    print("Filtering RAR file list by completed...")
    rar_files = filter_rar_list_by_completed(rar_files)
    print(f"Filtered to {len(rar_files)} RAR files")
    rar_snapshot = generate_rar_snapshot(rar_files)
