import os
import json
import subprocess
import time
from typing import List
import xxhash
from Preprocessor.Extract.output.path_definitions import (
    EXTRACTION_LOG_ERROR_FILE_NAME,
    EXTRACTION_WORK_LIST_NAME,
    EXTRACTED_FILESYSTEM_SNAPSHOT_OUTPUT_NAME,
    UNEXTRACTED_RAR_SNAPSHOT_OUTPUT_NAME
)
from Shared import utils

def generate_rar_filelist(root):
    rar_files = []
    for fp, dirs, files in os.walk(root):
        files = [f for f in files if f.endswith(".rar")]
        for file in files:
            rar_files.append(os.path.join(fp, file))

    return rar_files


def generate_rar_snapshot(files: List[str]):
    results = {}
    for idx, file in enumerate(files):
        with open(file, "rb") as f:
            print(f"[{idx}/{len(files)}] Hashing {file}", end="\r")
            hash = xxhash.xxh3_128_hexdigest(f.read())
            results[file] = {
                "hash": hash,
                "size": os.path.getsize(file),
            }

    return results

def extract_rar_files(files: List[str]):
    error_log_fp = utils.get_self_output_path(__file__, EXTRACTION_LOG_ERROR_FILE_NAME)
    error_log_file = open(error_log_fp, "a", encoding="utf-8")

    for idx, file in enumerate(files):
        if (not os.path.exists(file)):
            print(f"[{idx}/{len(files)}] RAR File not found (Already extracted?): {file}")
            time.sleep(2)
            continue
        try:
            print(f"[{idx}/{len(files)}] Extracting: {file}")
            result = subprocess.run(["7z", "x", file])
            if (result.returncode != 0):
                error_log_file.write(f"7Z CMD ERROR [{file}] RETURNED FAILURE STATUS {result.returncode}\n")
                error_log_file.flush()
                continue
            os.unlink(file)
        except Exception as e:
            error_log_file.write(f"ERROR [{file}] {str(e)}\n")
            error_log_file.flush()

def generate_filesystem_snapshot(root: str):
    results = {}
    count = 0
    for fp, dirs, files in os.walk(root):
        for file in files:
            count += 1
            print(f"[{count}] Hashing {file}", end="\r")
            file_path = os.path.join(fp, file)
            hash = xxhash.xxh3_128_hexdigest(file_path)
            results[file_path] = {
                "hash": hash,
                "size": os.path.getsize(file_path),
            }

    return results

if __name__ == '__main__': 
    rar_filelist_path = utils.get_self_output_path(__file__, EXTRACTION_WORK_LIST_NAME)
    if (os.path.exists(rar_filelist_path)):
        print("Extraction work list already exists. Skipping generation.")
        with open(rar_filelist_path, "r", encoding="utf-8") as f:
            rar_files = json.load(f)
    else:
        tlmc_root = input("Enter TLMC root path: ")
        rar_files = generate_rar_filelist(tlmc_root)
        
        with open(rar_filelist_path, "w", encoding="utf-8") as f:
            json.dump(rar_files, f, indent=4, ensure_ascii=False)

    rar_snapshot_path = utils.get_self_output_path(__file__, UNEXTRACTED_RAR_SNAPSHOT_OUTPUT_NAME)
    if (os.path.exists(rar_snapshot_path)):
        print("Unextracted rar snapshot already exists. Skipping snapshot generation.")
    else:
        result = generate_rar_snapshot(rar_files)
        with open(rar_snapshot_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=4, ensure_ascii=False)
    
    extract_rar_files(rar_files)

    # Generate filesystem snapshot
    if (os.path.exists(rar_snapshot_path)):
        print("Extracted filesystem snapshot already exists. Skipping snapshot generation.")
    else:
        result = generate_filesystem_snapshot(tlmc_root)
        with open(rar_snapshot_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=4, ensure_ascii=False)
