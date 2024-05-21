import os
import subprocess
import time
from typing import List

from Preprocessor.Extract.output.path_definitions import EXTRACTION_LOG_ERROR_FILE_NAME
from Shared import utils


def extract_rar_files(files: List[str]):
    error_log_fp = utils.get_self_output_path(__file__, EXTRACTION_LOG_ERROR_FILE_NAME)
    error_log_file = open(error_log_fp, "a", encoding="utf-8")

    for idx, file in enumerate(files):
        try:
            print(f"[{idx}/{len(files)}] Extracting: {file}")
            file_dir = os.path.dirname(file)
            extract_dir_name = os.path.basename(file).replace(".rar", "")
            extract_dir = os.path.join(file_dir, extract_dir_name)

            os.makedirs(extract_dir, exist_ok=True)

            os.chdir(extract_dir)

            result = subprocess.run(["7z", "x", file])
            if result.returncode != 0:
                error_log_file.write(
                    f"7Z CMD ERROR [{file}] RETURNED FAILURE STATUS {result.returncode}\n"
                )
                error_log_file.flush()
                continue
            os.unlink(file)
        except Exception as e:
            error_log_file.write(f"ERROR [{file}] {str(e)}\n")
            error_log_file.flush()


def generate_filelist(root):
    files = []
    for fp, dirs, fs in os.walk(root):
        fs = [f for f in fs if f.endswith(".rar")]
        for f in fs:
            files.append(os.path.join(fp, f))
    return files


if __name__ == "__main__":
    tlmc_root = input("Enter TLMC root path: ")
    rar_files = generate_filelist(tlmc_root)
    print(f"Found {len(rar_files)} RAR files")
    input("Press enter to start extraction")
    extract_rar_files(rar_files)
