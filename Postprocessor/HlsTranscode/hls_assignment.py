import os
from typing import Dict, List

import Processor.InfoCollector.Aggregator.output.path_definitions as AggregatorPathDef
import Postprocessor.HlsTranscode.output.path_definitions as HlsTranscodePathDef
from Shared import json_utils, utils

assigned_merged_output = utils.get_output_path(
    AggregatorPathDef, AggregatorPathDef.ID_ASSIGNED_PATH
)

hls_worklist_output = utils.get_output_path(
    HlsTranscodePathDef, HlsTranscodePathDef.HLS_TRANSCODE_FILELIST_OUTPUT_NAME
)


target_qualities = [
    "128k",
    "192k",
    "256k",
    "320k",
]


def make_ffmpeg_hls_transcode_cmd(src, dst_root, bitrate):
    src = utils.oslex_quote(src)
    seg_path = utils.oslex_quote(os.path.join(dst_root, "segment_%03d.m4s"))
    dst_playlist = utils.oslex_quote(os.path.join(dst_root, "playlist.m3u8"))
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


def generate_worklist_from_ids(entry: dict):
    all_tracks = {}
    for album_id, album_data in entry.items():
        discs = album_data["Discs"]
        for disc_root, disc_data in discs.items():
            disc_tracks = disc_data["Tracks"]
            for track in disc_tracks:
                track_id = track["TrackMetadata"]["TrackId"]
                track_path = track["TrackPath"]
                all_tracks[track_id] = track_path

    return generate_worklist(all_tracks)


def generate_worklist(all_tracks: Dict[str, str]):
    work = {}
    for track_id, track_path in all_tracks.items():
        file_parent = os.path.dirname(track_path)
        file_name = os.path.basename(track_path)
        file_name_no_ext = os.path.splitext(file_name)[0]
        hls_target_base_dir = os.path.join(file_parent, file_name_no_ext)

        work_group = {}
        for quality in target_qualities:
            dst_root = os.path.join(hls_target_base_dir, "hls", quality)
            work_group[quality] = {
                "src": track_path,
                "dst_root": dst_root,
                "cmd": " ".join(
                    make_ffmpeg_hls_transcode_cmd(track_path, dst_root, quality)
                ),
            }
        work[track_id] = work_group

    return work


def main():
    print(f"Load id assignment from {assigned_merged_output}")
    id_assignment = json_utils.json_load(assigned_merged_output)

    print(f"Generate HLS transcode worklist")
    result = generate_worklist_from_ids(id_assignment)

    print(f"Writing HLS transcode worklist to {hls_worklist_output}")
    json_utils.json_dump(result, hls_worklist_output)


if __name__ == "__main__":
    main()
