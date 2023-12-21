import json
import os
import subprocess

from Preprocessor.CueSplitter.output.path_definitions import CUE_SCANNER_OUTPUT_NAME
from Shared.utils import check_cuesheet_attr, get_file_relative

output_root = get_file_relative(__file__, "output", CUE_SCANNER_OUTPUT_NAME)

def assign_confidence(potential: dict):
    """
    Determine the likelihood of an album needing to be split.

    Parameters:
    album_info (dict): A dictionary containing 'cue', 'audio', and 'total_flac_count' keys.

    Returns:
    float: A score between 0 and 1 indicating the likelihood of needing splitting.
    """
    # Number of cue files and FLAC files
    num_cue_files = len(potential['cue']) # 1
    num_cuesheet_attr_files = len(potential['audio']) # 0
    num_flac_files = potential['total_flac_count'] #  1

    # If there are exactly as many cue files as FLAC files, 
    # and the number of cue files is the same as the number of audio files,
    # then this is a very strong indicator that the album needs splitting.
    if (num_cue_files == num_cuesheet_attr_files) and (num_cue_files == num_flac_files):
        return 1

    if (num_cue_files == num_cuesheet_attr_files):
        return 0.9

    # Base score based on the ratio of cue files to FLAC files
    if num_flac_files == 0:
        return 0  # Avoid division by zero

    score = min(num_cue_files / num_flac_files, 1)

    # Adjust score based on the total count of FLAC files
    if num_flac_files > 7:  # Arbitrary threshold for high FLAC count
        score *= 1 / (num_flac_files / 7) # The higher the FLAC count, the lower the score

    return score

def scan_potential_album(root: str):
    pending_cue = []
    pending_audio = []
    total_flac_count = 0
    flag_reason = None

    for root, dirs, files in os.walk(root):
        for file in files:
            if file.endswith(".cue"):
                pending_cue.append(os.path.join(root, file))
                if flag_reason is None:
                    flag_reason = "Cue file found"
            
            if file.endswith(".flac") or file.endswith(".wav") or file.endswith(".mp3"):
                # probe file and check if have cue metadata
                total_flac_count += 1
                path = os.path.join(root, file)
                if check_cuesheet_attr(path):
                    pending_audio.append(path)
                    if flag_reason is None:
                        flag_reason = "Audio file with cuesheet attribute found"

    return {
        "root": root,
        "cue": pending_cue,
        "audio": pending_audio,
        "total_flac_count": total_flac_count,
        "flag_reason": flag_reason
    }

def main():
    tlmc_root = input("Enter the path to the root of the TLMC: ")

    if not os.path.exists(tlmc_root):
        print("Invalid path")
        exit(1)

    potential = []
    artists = [i for i in os.listdir(tlmc_root) if os.path.isdir(os.path.join(tlmc_root, i))]
    scanned = 0 
    for artist in artists:
        artist_path = os.path.join(tlmc_root, artist)
        
        # scan each ablum
        albums = os.listdir(artist_path)
        for album in albums:
            print(f"[{scanned} | {len(potential)}] Scanning {os.path.join(artist_path, album)}")
            album_path = os.path.join(artist_path, album)
            pot = scan_potential_album(album_path)
            if (len(pot["cue"]) > 0 or len(pot["audio"]) > 0) and pot["total_flac_count"] > 0:
                potential.append(pot)
                print(f"Flagged potential album: {album}. Reason: {pot['flag_reason']}")
            scanned += 1
        
    # assign confidence score
    for pot in potential:
        pot["confidence"] = assign_confidence(pot)

    # sort by confidence score
    potential.sort(key=lambda x: x["confidence"], reverse=True)

    with open(os.path.join(output_root, "potential.json"), "w") as f:
        json.dump(potential, f, indent=4, ensure_ascii=False)


if __name__ == "__main__":
    main()
