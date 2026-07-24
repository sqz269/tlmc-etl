"""
Extracts a TLMC release into the merged album tree described by an extraction
plan.

Reads `output/extraction_plan.output.json` produced by `extract_plan.py` and
extracts each archive to the destination that plan assigns it, so the result is
the two-level `<circle>/<album>/` layout the rest of the pipeline expects.

Progress is journaled per archive, so the script can be interrupted and rerun;
archives already recorded as complete are skipped.
"""

import json
import os
import shutil
import subprocess
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import Preprocessor.Extract.output.path_definitions as ExtractOutputPaths
from Preprocessor.Extract.extract_plan import LAYOUT_FLAT
from Shared.json_utils import json_load
from Shared.utils import get_output_path

# Extraction is IO bound and the v6 archives are stored uncompressed, so more
# workers only helps on solid state storage. Keep this at 1 for spinning disks.
MAX_WORKERS = 1

# Delete each archive once it has been extracted. Halves the peak disk
# requirement but destroys the downloaded release (and any torrent seeding it).
# Flip to True at run time once the destination array is in place; left False so
# the destructive path is never armed by accident between runs.
DELETE_ARCHIVE_AFTER_EXTRACT = False

plan_path = get_output_path(
    ExtractOutputPaths, ExtractOutputPaths.EXTRACTION_PLAN_OUTPUT_NAME
)
journal_path = get_output_path(
    ExtractOutputPaths, ExtractOutputPaths.EXTRACTION_JOURNAL_OUTPUT_NAME
)
error_log_path = get_output_path(
    ExtractOutputPaths, ExtractOutputPaths.EXTRACTION_LOG_ERROR_FILE_NAME
)


def load_journal():
    """Returns the set of archives already extracted successfully."""
    if not os.path.isfile(journal_path):
        return set()

    completed = set()
    with open(journal_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("Status") == "completed":
                completed.add(record["Archive"])
    return completed


def append_journal(record, lock):
    with lock:
        with open(journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_error(message, lock):
    with lock:
        with open(error_log_path, "a", encoding="utf-8") as f:
            f.write(message + "\n")


def check_collisions(entries):
    """
    Returns the album directories that more than one archive would write to.
    Extracting these would silently merge two releases into one directory.
    """
    destinations = defaultdict(list)
    for entry in entries:
        for album in entry["Albums"]:
            destinations[(entry["Circle"], album)].append(entry["Archive"])

    return {key: value for key, value in destinations.items() if len(value) > 1}


def required_bytes(entries):
    total = 0
    for entry in entries:
        try:
            total += os.path.getsize(entry["Archive"])
        except OSError:
            pass
    return total


def extract_one(entry, lock):
    """
    Extracts a single archive into the destination its plan entry assigns.

    For `flat` archives the destination is a freshly created album directory.
    For `nested` and `bundle` archives it is the circle directory, because the
    archive already carries the album directory names inside it.
    """
    archive = entry["Archive"]
    destination = entry["ExtractInto"]

    try:
        os.makedirs(destination, exist_ok=True)

        result = subprocess.run(
            ["7z", "x", archive, f"-o{destination}", "-y", "-bso0", "-bsp0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        if result.returncode != 0:
            output = result.stdout.decode("utf-8", errors="replace").strip()
            append_error(
                f"7Z FAILED [{archive}] exit {result.returncode}\n{output}", lock
            )
            append_journal(
                {"Archive": archive, "Status": "failed", "Code": result.returncode},
                lock,
            )
            # Do not leave an empty album directory behind; the album scanner
            # would otherwise pick it up and flag it as an album with no tracks.
            if entry["Layout"] == LAYOUT_FLAT and not os.listdir(destination):
                os.rmdir(destination)
            return False

        # For a flat archive the destination is the album directory itself; for
        # the other layouts the archive brought its own album directories along.
        if entry["Layout"] == LAYOUT_FLAT:
            expected = [destination]
        else:
            expected = [os.path.join(destination, a) for a in entry["Albums"]]

        missing = [path for path in expected if not os.path.isdir(path)]
        if missing:
            append_error(f"MISSING ALBUM DIRS [{archive}] expected {missing}", lock)

        if DELETE_ARCHIVE_AFTER_EXTRACT:
            os.unlink(archive)

        append_journal({"Archive": archive, "Status": "completed"}, lock)
        return True

    except Exception as e:
        append_error(f"ERROR [{archive}] {e}", lock)
        append_journal({"Archive": archive, "Status": "failed", "Error": str(e)}, lock)
        return False


def main():
    if not os.path.isfile(plan_path):
        print(f"Extraction plan not found at {plan_path}")
        print("Run Preprocessor/Extract/extract_plan.py first.")
        exit(1)

    plan = json_load(plan_path)
    entries = plan["Entries"]
    destination_root = plan["Destination"]

    collisions = check_collisions(entries)
    if collisions:
        print(f"{len(collisions)} album directories are claimed by more than one archive:")
        for (circle, album), archives in list(collisions.items())[:10]:
            print(f"  {circle}/{album}")
            for archive in archives:
                print(f"      {archive}")
        if len(collisions) > 10:
            print(f"  ... and {len(collisions) - 10} more")
        print()
        print("Resolve these in the plan (rename an album or drop an archive) first.")
        exit(1)

    completed = load_journal()
    pending = [e for e in entries if e["Archive"] not in completed]

    print(f"Destination      : {destination_root}")
    print(f"Archives in plan : {len(entries)}")
    print(f"Already extracted: {len(completed)}")
    print(f"Pending          : {len(pending)}")

    if not pending:
        print("Nothing to do.")
        return

    needed = required_bytes(pending)
    try:
        os.makedirs(destination_root, exist_ok=True)
    except OSError as e:
        print()
        print(f"Cannot create the destination {destination_root}: {e}")
        print("Fix the path or its permissions, or rerun the plan with a different")
        print("destination, then try again.")
        exit(1)
    free = shutil.disk_usage(destination_root).free
    print(f"Space required   : {needed / 1024 ** 4:.2f} TiB")
    print(f"Space available  : {free / 1024 ** 4:.2f} TiB")
    if needed > free and not DELETE_ARCHIVE_AFTER_EXTRACT:
        print()
        print("WARNING: the destination does not have room for the pending archives.")
        print("The v6 archives are stored uncompressed, so extraction is roughly 1:1.")

    if DELETE_ARCHIVE_AFTER_EXTRACT:
        print()
        print("WARNING: DELETE_ARCHIVE_AFTER_EXTRACT is on. Source archives will be")
        print("permanently removed as they are extracted.")

    print()
    input("Press enter to start extraction, Ctrl+C to abort")

    lock = threading.Lock()
    done = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for entry, ok in zip(pending, executor.map(lambda e: extract_one(e, lock), pending)):
            done += 1
            if not ok:
                failed += 1
            print(
                f"[{done}/{len(pending)}] {'FAIL' if not ok else 'ok  '} "
                f"{os.path.basename(entry['Archive'])}",
                end="\r",
            )

    print()
    print(f"Extracted {done - failed} archives, {failed} failed")
    if failed:
        print(f"See {error_log_path}")


if __name__ == "__main__":
    main()
