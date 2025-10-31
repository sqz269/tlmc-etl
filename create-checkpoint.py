from genericpath import exists
import os
import json
import tarfile
import shutil
from typing import List
from pprint import pprint

output_files: List[str] = []
for fp, dirs, files in os.walk("."):
  for file in files:
    if "output.json" in file:
      path = os.path.join(fp, file)
      output_files.append(path)

# copy output files to checkpoint dir
checkpoint_dir = ".checkpoint"
os.makedirs(checkpoint_dir, exist_ok=True)
for output_file in output_files:
  # perserve directory structure
  relative_path = os.path.relpath(output_file, ".")
  base_dir = os.path.dirname(relative_path)

  dest_dir = os.path.join(checkpoint_dir, base_dir)
  os.makedirs(dest_dir, exist_ok=True)

  dest_path = os.path.join(dest_dir, os.path.basename(output_file))
  print(f"Copying {output_file}")
  shutil.copy2(output_file, dest_path)

# create archive
print("Creating checkpoint archive...")
archive_name = "checkpoint.tar.gz"
with tarfile.open(archive_name, "w:gz") as tar:
  tar.add(checkpoint_dir, arcname=os.path.basename(checkpoint_dir))

# clean up checkpoint dir
shutil.rmtree(checkpoint_dir)
print(f"Checkpoint created: {archive_name}")
