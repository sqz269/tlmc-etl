import os
import json
import re
import subprocess
import threading
import time
import traceback
from Shared.utils import (
    check_cuesheet_attr,
    max_common_prefix,
    get_file_relative,
    oslex_quote,
)

from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED

from Shared.json_utils import json_dump, json_load
from Preprocessor.CueSplitter.output.path_definitions import (
    CUE_DESIGNATER_OUTPUT_NAME,
)


output_root = get_file_relative(__file__, "output")
input_designated = os.path.join(output_root, CUE_DESIGNATER_OUTPUT_NAME)

journal_completed_path = os.path.join(output_root, "splitter.completed.output.txt")
journal_failed_path = os.path.join(output_root, "splitter.failed.output.txt")
journal_completed_file = open(journal_completed_path, "a+", encoding="utf-8")
journal_failed_file = open(journal_failed_path, "a+", encoding="utf-8")


def mk_ffmpeg_cmd(track, info):
    audio_path = info["AudioFilePath"]
    if info["AudioFilePathGuessed"]:
        audio_path = info["AudioFilePathGuessed"]

    out = os.path.join(info["Root"], track["TrackName"])
    if not track["Duration"]:
        return f'ffmpeg -i {oslex_quote(audio_path)} -ss {track["Begin"]} -movflags faststart {oslex_quote(out)} -y -stats -v quiet'

    return f'ffmpeg -i {oslex_quote(audio_path)} -ss {track["Begin"]} -t {track["Duration"]} -movflags faststart {oslex_quote(out)} -y -stats -v quiet'


print_logs = {}
stats = {
    "processed": 0,
    "failed": 0,
    "total": 0,
}
cmd_exec = []


def process_one(profile):
    global print_logs
    cap_time = re.compile(r"time=(\d{2}:\d{2}:\d{2}.\d{2})")
    try:
        ident = threading.get_ident()
        # PROBE EACH OUTPUT FILE TO SEE IF IT EXISTS AND IS COMPLETE AFTER PROCESSING
        for idx, track in enumerate(profile["Tracks"]):
            file_name = track["TrackName"]
            cmd = mk_ffmpeg_cmd(track, profile)
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                shell=True,
                encoding="utf-8",
            )

            for line in proc.stdout:
                progress_time = cap_time.search(line)
                print_logs[
                    ident
                ] = f"[{idx + 1}/{len(profile['Tracks'])}] ({progress_time.group(1) if progress_time else 'NO_INFO'}) {file_name}"

            proc.wait()

            time.sleep(0.6)

        for (
            idx,
            track,
        ) in enumerate(profile["Tracks"]):
            # Perform a final check to make sure the file exists and is not empty
            out = os.path.join(profile["Root"], track["TrackName"])
            if not os.path.exists(out):
                raise Exception(f"Track {track} does not exist after processing")

            if os.path.getsize(out) == 0:
                raise Exception(f"Track {track} is empty after processing")

        stats["processed"] += 1

        journal_completed_file.write(profile["id"] + "\n")
        journal_completed_file.flush()

        audio_track = (
            profile["AudioFilePath"]
            if not profile["AudioFilePathGuessed"]
            else profile["AudioFilePathGuessed"]
        )

        os.unlink(profile["CueFilePath"])
        os.unlink(audio_track)
    except Exception as e:
        stats["failed"] += 1
        journal_failed_file.write(profile["id"] + "\n")
        journal_failed_file.flush()
        print_logs[ident] = f"Failed to process {profile['id']}"
        return


def process(profiles):
    queued = 0
    processes = []
    try:
        with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
            for id, profile in profiles.items():
                processes.append(executor.submit(process_one, profile))
                queued += 1
            print(f"Queued {queued} processes", end="\r")
            stats["total"] = queued

            time.sleep(1)
            try:
                key = print_logs.keys()
                while any([p.running() for p in processes]):
                    if key != print_logs.keys():
                        key = print_logs.keys()

                    print(
                        "PROGRESS [{}/{} | {}]".format(
                            stats["processed"],
                            stats["total"],
                            stats["failed"],
                        )
                    )
                    for ident in key:
                        print(print_logs[ident], end="\n")

                    wait(processes, timeout=0.7, return_when=ALL_COMPLETED)
                    os.system("cls" if os.name == "nt" else "clear")
            except Exception as e:
                print(e)
                print(traceback.format_exc())

    except Exception as e:
        traceback.print_exc()
        print(e)


def main():
    if not os.path.exists(input_designated):
        print("No designated file found.")
        return

    profiles = json_load(input_designated)

    processed = journal_completed_file.read().splitlines()
    for id in processed:
        print(f"Skipping {id} (already processed)")
        profiles.pop(id, None)

    process(profiles)


if __name__ == "__main__":
    main()
