import sys
import os
import subprocess

print("This script will extract all .rar files in the current directory and delete them after extraction.\n")
print("Make sure you have 7z installed and added to PATH (Must be 64 bit version for very large file support).\n")
print("Make sure you have enough disk space to extract all files.\n")
print("Advised to run this script in a screen session.\n")
input("Press Enter to continue...")

log_path = input("Enter error log path: ")
err_log = open(log_path, "a", encoding="utf-8");

tlmc_root = input("Enter TLMC root path: ")

for fp, dirs, files in os.walk("."):
    files = [f for f in files if f.endswith(".rar")]
    input("Found {} files. Press Enter to continue...".format(len(files)))
    total = len(files)
    for idx, file in enumerate(files):
        try:
            # cp = os.path.join(fp, file)
            print(f"[{idx + 1}/{total}] Extracting: {file}")
            cmd = f"7z x {file}"
            result = subprocess.run(["7z", "x", file])
            if (result.returncode != 0):
                err_log.write(f"7Z CMD ERROR [{file}] RETURNED FAILURE STATUS {result.returncode}\n")
                err_log.flush()
                continue
            print(f"Deleting: {file}")
            os.unlink(os.path.join(fp, file))
        except Exception as e:
            err_log.write(f"ERROR [{file}] {str(e)}\n")
            err_log.flush()

err_log.close()