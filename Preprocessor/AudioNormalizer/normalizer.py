import re
import os
import sys
import json
import time
import shlex
import traceback

import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED

from uuid import uuid4

from Shared.json_utils import json_dump, json_load
from Shared.utils import get_file_relative, oslex_quote

output_root = get_file_relative(__file__, "output")
output_file = os.path.join(output_root, "normalizer.filelist.output.json")
journal_completed_path = os.path.join(output_root, "normalizer.completed.output.txt")
journal_failed_path = os.path.join(output_root, "normalizer.failed.output.txt")

journal_completed_lock = threading.Lock()
journal_failed_lock = threading.Lock()

# disable buffering to prevent data loss on exception
journal_completed_file = open(journal_completed_path, "a+", encoding="utf-8")
journal_failed_file = open(journal_failed_path, "a+", encoding="utf-8")

FILE_EXT = (".flac", ".wav", ".mp3")


def mk_ffmpeg_cmd(src, dst):
    return [
        "ffmpeg",
        "-i",
        oslex_quote(src),
        "-af",
        "loudnorm",  # "loudnorm=I=-24:LRA=7:tp=-2.0",
        "-movflags",
        "faststart",
        oslex_quote(dst),
        "-y",
        "-v",
        "quiet",
        "-stats",
    ]


def mk_out_filename(original_name):
    return "audio.norm." + original_name


def generate_file_list(root):
    output = {}
    count = 0
    for fp, dirs, files in os.walk(root):
        for file in files:
            if file.endswith(tuple(FILE_EXT)):
                id = str(uuid4())
                output[id] = {
                    "id": id,
                    "src": os.path.join(fp, file),
                    "tmp_dst": os.path.join(fp, mk_out_filename(file)),
                }
                count += 1
                print(f"Found {count} files", end="\r")

    return output


print_queue_lock = threading.Lock()
print_queue = {}
stats_lock = threading.Lock()
stats = {
    "processed": 0,
    "failed": 0,
    "total": 0,
}


def process_one(file_info):
    cap_time = re.compile(r"time=(\d{2}:\d{2}:\d{2}.\d{2})")
    global print_queue
    global stats
    try:
        ident = threading.get_ident()
        cmd = mk_ffmpeg_cmd(file_info["src"], file_info["tmp_dst"])
        # for some reason it refuses to work with shell=False and array args
        proc = subprocess.Popen(
            " ".join(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            shell=True,
        )

        for line in proc.stdout:
            progress_time = cap_time.search(line)
            print_queue[
                ident
            ] = f"[{progress_time.group(1) if progress_time else 'NO_INFO'}] {file_info['src']}"

        proc.wait()
        if proc.returncode != 0:
            print_queue[ident] = f"[FAILED] {file_info['id']} ({proc.returncode})"
            stats_lock.acquire()
            stats["failed"] += 1
            stats_lock.release()

            journal_failed_lock.acquire()
            journal_failed_file.write(file_info["id"] + f"\t{' '.join(cmd)}\t" + "\n")
            journal_failed_file.flush()
            journal_failed_lock.release()

            print_queue_lock.acquire()
            print_queue[ident] = f"[FAILED] {file_info['id']}"
            print_queue_lock.release()
            return
        print_queue[ident] = f"[DONE] {file_info['id']}"
        time.sleep(0.6)
        stats["processed"] += 1

        journal_completed_lock.acquire()
        journal_completed_file.write(file_info["id"] + "\n")
        journal_completed_file.flush()
        journal_completed_lock.release()

        os.unlink(file_info["src"])
        os.rename(file_info["tmp_dst"], file_info["src"])
    except Exception as e:
        stats_lock.acquire()
        stats["failed"] += 1
        stats_lock.release()

        journal_failed_lock.acquire()
        journal_failed_file.write(file_info["id"] + "\n")
        journal_failed_file.flush()
        journal_failed_lock.release()

        print_queue_lock.acquire()
        print_queue[ident] = f"[FAILED] {file_info['id']}"
        print_queue_lock.release()

        print(traceback.format_exc())


def process(file_list):
    global print_queue
    stats["total"] = len(file_list)

    queued = 0
    processes = []
    try:
        with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
            for key, file_info in file_list.items():
                queued += 1
                processes.append(executor.submit(process_one, file_info))

            try:
                key = print_queue.keys()
                while any([p.running() for p in processes]):
                    if print_queue.keys() != key:
                        key = print_queue.keys()

                    print(
                        "PROGRESS [{}/{} | {}]".format(
                            stats["processed"],
                            stats["total"],
                            stats["failed"],
                        )
                    )
                    for ident in key:
                        print(print_queue[ident], end="\n")

                    print("\n\n")
                    wait(processes, timeout=0.5, return_when=ALL_COMPLETED)
                    os.system("cls" if os.name == "nt" else "clear")
            except Exception as e:
                pass

    except Exception as e:
        pass

    finally:
        pass


def main():
    file_list = None
    if not os.path.exists(output_file):
        tlmc_root = input("Enter the path to the root of the TLMC: ")
        print("Generating file list...")
        file_list = generate_file_list(tlmc_root)
        json_dump(file_list, output_file)
    else:
        print("Existing File List Detected Resuming")
        file_list = json_load(output_file)

        for id in journal_completed_file:
            if id in file_list:
                del file_list[id]
        for id in journal_failed_file:
            if id in file_list:
                del file_list[id]

        print("Resuming with ", len(file_list), "files")

    process(file_list)
    if os.name != "nt":
        # reset terminal
        os.system("reset")


if __name__ == "__main__":
    main()
