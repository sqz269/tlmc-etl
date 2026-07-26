import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from Preprocessor.CueSplitter.output.path_definitions import CUE_SCANNER_OUTPUT_NAME
from Shared.utils import check_cuesheet_attr, get_file_relative

TARGET_TYPES = (".flac", ".wav", ".mp3", ".m4a")

# One ffprobe is spawned per audio file (~48ms each, ~150k files), so the scan is
# subprocess bound rather than CPU or disk bound. Scanning albums concurrently
# turns a two hour serial walk into minutes. Kept modest so the probes do not
# swamp a rotational disk with seeks.
MAX_WORKERS = 8

# The full result is written once, at the end. Flushing partial results
# periodically means an interrupted scan still leaves something usable.
PARTIAL_WRITE_EVERY = 250

output_root = get_file_relative(__file__, "output")
os.makedirs(output_root, exist_ok=True)
output_file = os.path.join(output_root, CUE_SCANNER_OUTPUT_NAME)


def assign_confidence(potential: dict):
    """
    Determine the likelihood of an album needing to be split.

    Parameters:
    album_info (dict): A dictionary containing 'cue', 'audio', and 'total_flac_count' keys.

    Returns:
    float: A score between 0 and 1 indicating the likelihood of needing splitting.
    """
    # Number of cue files and FLAC files
    num_cue_files = len(potential["cue"])  # 1
    num_cuesheet_attr_files = len(potential["audio"])  # 0
    num_flac_files = potential["total_flac_count"]  #  1

    # If there are exactly as many cue files as FLAC files,
    # and the number of cue files is the same as the number of audio files,
    # then this is a very strong indicator that the album needs splitting.
    if (num_cue_files == num_cuesheet_attr_files) and (num_cue_files == num_flac_files):
        return 1

    if num_cue_files == num_cuesheet_attr_files:
        return 0.9

    if num_cue_files == 0 and num_cuesheet_attr_files != 0:
        return 0.9

    # Base score based on the ratio of cue files to FLAC files
    if num_flac_files == 0:
        return 0  # Avoid division by zero

    score = min(num_cue_files / num_flac_files, 0.8)

    # Adjust score based on the total count of FLAC files
    if num_flac_files > 7:  # Arbitrary threshold for high FLAC count
        score *= 1 / (
            num_flac_files / 7
        )  # The higher the FLAC count, the lower the score

    return score


def list_subdirectories(path: str):
    """
    Subdirectories of `path`, skipping anything that cannot be read.

    An unreadable directory (ext4's root owned `lost+found` is the one that
    always exists) used to raise PermissionError out of the scan loop and kill
    the whole run.
    """
    try:
        entries = os.listdir(path)
    except OSError as e:
        print(f"Skipping unreadable directory {path}: {e}")
        return []

    result = []
    for name in sorted(entries):
        full = os.path.join(path, name)
        try:
            if os.path.isdir(full):
                result.append(full)
        except OSError:
            continue
    return result


def scan_potential_album(album_root: str):
    pending_cue = []
    pending_audio = []
    total_flac_count = 0
    flag_reason = None

    # os.walk swallows traversal errors by default, which is what we want here:
    # one unreadable subdirectory should not abort the album.
    for root, dirs, files in os.walk(album_root):
        for file in files:
            if file.lower().endswith(".cue"):
                pending_cue.append(os.path.join(root, file))
                if flag_reason is None:
                    flag_reason = "Cue file found"

            if file.lower().endswith(TARGET_TYPES):
                # probe file and check if have cue metadata
                total_flac_count += 1
                path = os.path.join(root, file)
                try:
                    has_cuesheet = check_cuesheet_attr(path)
                except Exception as e:
                    # A single unreadable or malformed file should not lose the
                    # rest of the album.
                    print(f"Probe failed for {path}: {e}")
                    has_cuesheet = False

                if has_cuesheet:
                    pending_audio.append(path)
                    if flag_reason is None:
                        flag_reason = "Audio file with cuesheet attribute found"

    return {
        "root": album_root,
        "cue": pending_cue,
        "audio": pending_audio,
        "total_flac_count": total_flac_count,
        "flag_reason": flag_reason,
    }


def write_results(potential: list):
    """Scores, sorts and writes the result set, replacing the output atomically."""
    for pot in potential:
        pot["confidence"] = assign_confidence(pot)

    potential.sort(key=lambda x: x["confidence"], reverse=True)

    tmp = output_file + ".partial"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(potential, f, indent=4, ensure_ascii=False)
    os.replace(tmp, output_file)


def main():
    tlmc_root = input("Enter the path to the root of the TLMC: ")

    if not os.path.exists(tlmc_root):
        print("Invalid path")
        exit(1)

    # Only directories are albums. The previous listdir had no isdir filter, so
    # loose files sitting at circle level were scanned as albums; os.walk on a
    # file yields nothing, so they silently contributed an empty result.
    circles = list_subdirectories(tlmc_root)
    album_paths = []
    for circle_path in circles:
        album_paths.extend(list_subdirectories(circle_path))

    print(f"Found {len(album_paths)} albums under {len(circles)} circles")
    print(f"Scanning with {MAX_WORKERS} workers")

    potential = []
    lock = threading.Lock()
    scanned = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(scan_potential_album, path): path for path in album_paths
        }

        for future in as_completed(futures):
            album_path = futures[future]
            try:
                pot = future.result()
            except Exception as e:
                print(f"Failed to scan {album_path}: {e}")
                pot = None

            with lock:
                scanned += 1
                if (
                    pot is not None
                    and (len(pot["cue"]) > 0 or len(pot["audio"]) > 0)
                    and pot["total_flac_count"] > 0
                ):
                    potential.append(pot)
                    print(
                        f"[{scanned}/{len(album_paths)} | {len(potential)}] Flagged "
                        f"{os.path.basename(album_path)}. Reason: {pot['flag_reason']}"
                    )
                elif scanned % 200 == 0:
                    print(
                        f"[{scanned}/{len(album_paths)} | {len(potential)}] scanning..."
                    )

                if scanned % PARTIAL_WRITE_EVERY == 0:
                    write_results(potential)

    write_results(potential)
    print(f"\nScanned {scanned} albums, flagged {len(potential)}")
    print(f"Wrote {output_file}")


if __name__ == "__main__":
    main()
