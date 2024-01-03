import os
import re
import subprocess
import argparse
import sys
import shlex
import traceback
import mslex
import json
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED
import threading
import time

import Postprocessor.HlsTranscode.output.path_definitions as HlsTranscodeOutputPaths
from Shared.utils import get_output_path, oslex_quote
from Shared.json_utils import json_dump, json_load

filelist_output_path = get_output_path(
    HlsTranscodeOutputPaths, HlsTranscodeOutputPaths.HLS_TRANSCODE_FILELIST_OUTPUT_NAME
)
journal_completed_output_path = get_output_path(
    HlsTranscodeOutputPaths,
    HlsTranscodeOutputPaths.HLS_TRANSCODE_JOURNAL_COMPLETED_OUTPUT_NAME,
)
journal_failed_output_path = get_output_path(
    HlsTranscodeOutputPaths,
    HlsTranscodeOutputPaths.HLS_TRANSCODE_JOURNAL_FAILED_OUTPUT_NAME,
)

journal_completed_file = open(journal_completed_output_path, "a+", encoding="utf-8")
journal_failed_file = open(journal_failed_output_path, "a+", encoding="utf-8")

BITRATES = ["128k", "192k", "320k"]

print_logs = {}
stats = {
    "processed": 0,
    "failed": 0,
    "total": 0,
}
cmd_exec = []


def mk_ffmpeg_tc_cmd(src, root, bitrate):
    src = oslex_quote(src)
    seg_path = oslex_quote(os.path.join(root, "segment_%03d.m4s"))
    dst_playlist = oslex_quote(os.path.join(root, "playlist.m3u8"))
    return [
        "ffmpeg",
        "-i",
        src,
        "-vn",
        "-b:a",
        bitrate,
        "-f",
        "hls",
        "-hls_time",
        "10",
        "-hls_list_size",
        "0",
        "-hls_fmp4_init_filename",
        "init.mp4",
        "-hls_segment_filename",
        seg_path,
        "-hls_segment_type",
        "fmp4",
        "-c:a",
        "libfdk_aac",
        dst_playlist,
        "-y",
        "-v",
        "quiet",
        "-stats",
    ]


def mk_master_playlist(bitrate_list):
    playlist = "#EXTM3U\n"
    for bitrate in bitrate_list:
        playlist += (
            f'#EXT-X-STREAM-INF:BANDWIDTH={bitrate},AUDIO="audio",CODECS="mp4a.40.2"\n'
        )
        playlist += f"hls/{bitrate}/playlist.m3u8\n"
    return playlist


def mk_output_dir_path(target):
    target_dir = os.path.dirname(target)
    target_name = os.path.basename(target)
    target_name = target_name[: target_name.rfind(".")]

    track_dir = os.path.join(target_dir, target_name)

    return track_dir


def execute_cmd_and_report_ffmpeg(cmd: str, cwd, src, report_prefix):
    global print_logs
    ident = threading.get_ident()

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        shell=True,
        encoding="utf-8",
        cwd=cwd,
    )

    cap_time = re.compile(r"time=(\d{2}:\d{2}:\d{2}.\d{2})")
    cap_spd = re.compile(r"speed=\s{0,}(\d+\.?\d{0,})x")
    for line in proc.stdout:
        progress_time = cap_time.search(line)
        progress_speed = cap_spd.search(line)
        time_str = progress_time.group(1) if progress_time else "XX:XX:XX.XX"
        spd_str = f" {progress_speed.group(1)}x" if progress_speed else "XX"
        stats_pad = f"[{time_str} ({spd_str})]".ljust(25)
        if report_prefix:
            print_logs[ident] = f"{stats_pad}"
        print_logs[ident] = f"{stats_pad} {report_prefix} {os.path.basename(src)}"

    proc.wait()
    return proc.returncode


def process_one(key, entry):
    global print_logs
    try:
        ident = threading.get_ident()

        item = entry

        src_path = item["src"]
        dst_dir = item["dst_dir"]
        dst_master_playlist = item["dst_master_playlist"]
        # 1. Create output directory
        os.makedirs(dst_dir, exist_ok=True)

        for bitrate in BITRATES:
            "./hls"
            bitrate_root = os.path.join(dst_dir, "hls", bitrate)

            "./hls/128k/playlist.m3u8"
            playlist = os.path.join(bitrate_root, "playlist.m3u8")
            init = os.path.join(bitrate_root, "init.mp4")
            os.makedirs(bitrate_root, exist_ok=True)

            # 4. Transcode file
            tc_cmd = mk_ffmpeg_tc_cmd(src_path, bitrate_root, bitrate)
            retcode = execute_cmd_and_report_ffmpeg(
                tc_cmd, dst_dir, src_path, f"[{bitrate}]"
            )

            if retcode != 0:
                raise Exception(
                    f"Failed to transcode. FFmpeg return code: {retcode} cmd: {tc_cmd}"
                )

            if not os.path.isfile(playlist) or os.path.getsize(playlist) < 1:
                raise Exception(f"Result file is empty. cmd: {tc_cmd}, cmd: {retcode}")

            # 5. Move init.mp4 to the specific hls bitrate directory
            # if the ffmpeg command did not generate init in the bitrate_root already (behavior in older ffmpeg version)
            if not os.path.isfile(os.path.join(dst_dir, "init.mp4")) and (
                os.path.isfile(os.path.join(bitrate_root, "init.mp4"))
            ):
                pass
            else:
                os.replace(os.path.join(dst_dir, "init.mp4"), init)

        # 6. Create master playlist
        master_playlist = mk_master_playlist(BITRATES)
        with open(os.path.join(dst_dir, "playlist.m3u8"), "w", encoding="utf-8") as f:
            f.write(master_playlist)

        stats_pad = "[DONE]".ljust(25)
        print_logs[ident] = f"{stats_pad} {os.path.basename(src_path)}"

        stats["processed"] += 1
        journal_completed_file.write(key + "\n")
        journal_completed_file.flush()

        os.remove(src_path)

    except Exception as e:
        stats["failed"] += 1
        journal_failed_file.write(key + f" [Reason: {e}]" + "\n")
        journal_failed_file.flush()
        print_logs[ident] = f"Failed to process {key}"
        return


def process(profiles):
    queued = 0
    processes = []
    try:
        with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
            for id, profile in profiles.items():
                processes.append(executor.submit(process_one, id, profile))
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
    if not os.path.exists(filelist_output_path):
        print("No designated file found.")
        return

    profiles = json_load(filelist_output_path)

    ptr = journal_completed_file.tell()
    journal_completed_file.seek(0)
    processed = journal_completed_file.read().splitlines()
    journal_completed_file.seek(ptr)

    for id in processed:
        print(f"Skipping {id} (already processed)")
        profiles.pop(id, None)

    process(profiles)


if __name__ == "__main__":
    main()
