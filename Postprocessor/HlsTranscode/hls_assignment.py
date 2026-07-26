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

# Emit one contiguous media file per quality plus a byte-range playlist, instead
# of ~25 loose segment files.
#
# Why: hls_runner transcodes a flat worklist in parallel, so ext4 interleaved
# every track's segments with every other track's. Segments of one track ended up
# scattered TB apart, making playback N random seeks with no sequential run for
# readahead to exploit (measured on the USB HDD: 55 files/s, 18.3 ms each).
# One file per quality lets kernel readahead and ZFS zfetch prefetch a whole
# track for free, with no cache logic anywhere.
#
# Catalog-wide file count: ~17.7M -> ~1.5M.
#
# Note ffmpeg folds the fMP4 init segment into the same file under this flag and
# points #EXT-X-MAP at a byte range, so a quality directory holds exactly two
# files and there is no separate init.mp4. Consumers must handle both layouts
# while the v5 tree still contains per-segment output; they detect it from the
# playlist (`byterange is None` means legacy).
HLS_SINGLE_FILE = True

SEGMENT_NAME_SINGLE = "stream.m4s"
SEGMENT_NAME_MULTI = "segment_%03d.m4s"


def make_ffmpeg_hls_transcode_cmd(src, dst_root, bitrate, single_file=None):
    if single_file is None:
        single_file = HLS_SINGLE_FILE

    src = utils.oslex_quote(src)
    media_name = SEGMENT_NAME_SINGLE if single_file else SEGMENT_NAME_MULTI
    seg_path = utils.oslex_quote(os.path.join(dst_root, media_name))
    dst_playlist = utils.oslex_quote(os.path.join(dst_root, "playlist.m3u8"))

    cmd = [
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
        "-hls_segment_filename",
        seg_path,
        "-hls_segment_type",
        "fmp4",
        "-c:a",
        "libfdk_aac",
    ]

    if single_file:
        # -hls_fmp4_init_filename is deliberately omitted here: with
        # single_file ffmpeg writes the init segment into the media file and
        # ignores the option, so passing it only implies a file that never
        # appears.
        cmd += ["-hls_flags", "single_file"]
    else:
        cmd += ["-hls_fmp4_init_filename", "init.mp4"]

    cmd += [dst_playlist, "-y", "-v", "quiet", "-stats"]
    return cmd


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
