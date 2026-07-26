import os
import re
import subprocess
import Postprocessor.HlsTranscode.output.path_definitions as HlsTranscodePathDef
from Shared import json_utils, utils
from Shared.reporting_multi_processor import (
    JournalWriter,
    OutputWriter,
    PrintMessageReporter,
    StatAutoMuxMultiProcessor,
)
from Shared.utils import get_output_path
from Postprocessor.HlsTranscode.hls_assignment import SEGMENT_NAME_SINGLE

SEGMENT_INDEX_EXTRACTOR = re.compile(r'segment_(\d+)\.m4s');

hls_worklist_output = utils.get_output_path(
    HlsTranscodePathDef, HlsTranscodePathDef.HLS_TRANSCODE_FILELIST_OUTPUT_NAME
)

hls_finalized_struct_output_pth = utils.get_output_path(
    HlsTranscodePathDef, HlsTranscodePathDef.HLS_FINALIZED_FILELIST_OUTPUT_NAME
)

unknown_files = []


def scan_quality_dir(dst_root) -> dict:
    """
    Returns {'playlist': <path>, 'segments': {<path>: <index>}} for one quality.

    Two layouts exist in the tree and both are handled, since the v5 output is
    per-segment and anything transcoded after HLS_SINGLE_FILE was enabled is not:

      segments     init.mp4 at index -1, then segment_NNN.m4s at index N.
      single_file  playlist.m3u8 + stream.m4s only. The init segment lives
                   inside stream.m4s as a byte range, so there is a single media
                   entry at index 0 rather than an init plus N segments.

    The shape is identical either way, so AlbumTrackMetadataProcessor.cs consumes
    it unchanged -- it just inserts one HlsSegment row per quality instead of
    ~26. Playback does not need per-segment rows: the player reads the byte
    ranges out of playlist.m3u8 and issues HTTP Range requests against the one
    media file, which any static file server already supports.
    """
    scanned = {'segments': {}}

    for file in sorted(os.listdir(dst_root)):
        fp = os.path.join(dst_root, file)

        if file == 'playlist.m3u8':
            scanned['playlist'] = fp
        elif file == SEGMENT_NAME_SINGLE:
            scanned['segments'][fp] = 0
        elif file == 'init.mp4':
            scanned['segments'][fp] = -1
        else:
            index = SEGMENT_INDEX_EXTRACTOR.search(file)
            if index:
                scanned['segments'][fp] = int(index[1])
            else:
                # Was a blocking input() prompt, which stalls a 162k-track batch
                # on the first stray file and cannot be answered unattended.
                unknown_files.append(fp)

    return scanned


def generate_master_playlist(hls_scan_result, proc_root) -> str:
    lines_to_write = [
        "#EXTM3U",
        "#EXT-X-VERSION:7",
        "#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID=\"audio\",NAME=\"Audio\",DEFAULT=YES,AUTOSELECT=YES"
    ]

    for quality, info in hls_scan_result.items():
        bitrate = quality.replace("k", "")
        lines_to_write.append(f"#EXT-X-STREAM-INF:BANDWIDTH={bitrate}000,AUDIO=\"audio\",CODECS=\"mp4a.40.2\"")
        lines_to_write.append(info['playlist'].replace(proc_root, "").removeprefix(os.path.sep))

    return "\n".join(lines_to_write)

def main():
    # Guarded so that importing scan_quality_dir does not run the whole
    # finalizer -- and does not fail outright when no worklist exists yet.
    hls_worklist = json_utils.json_load(hls_worklist_output)

    all_results = {}
    for index, (track_id, entry) in enumerate(hls_worklist.items()):
        print(f"[{index}/{len(hls_worklist)}] Processing: {track_id}", end='\r')
        proc_root = None
        try:
            src = entry[list(entry.keys())[0]]['src']
            src_root = os.path.dirname(src)
            src_filename_no_ext = os.path.splitext(os.path.basename(src))[0]
            proc_root = os.path.join(src_root, src_filename_no_ext)

            """
        Result sample (single_file layout -- one media entry per quality, the
        init segment living inside it as a byte range):
        {
            "320k": {
                "playlist": "<Full FP Omitted>/hls/320k/playlist.m3u8",
                "segments": {
                    "<Full FP Omitted>/hls/320k/stream.m4s": 0
                }
            }
        }

        Legacy per-segment layout, still present across the v5 tree:
        {
            "320k": {
                "playlist": "<Full FP Omitted>/hls/320k/playlist.m3u8",
                "segments": {
                    // init.mp4 always receives an index assignment of -1
                    "<Full FP Omitted>/hls/320k/init.mp4": -1,

                    // index assignment based of segment extractor regex
                    "<Full FP Omitted>/hls/320k/segment_000.m4s": 0
                }
            }
            }
            """
            result = {}
            for quality, target_info in entry.items():
                result[quality] = scan_quality_dir(target_info['dst_root'])

            # Test if master playlist file already exists
            master_playlist_path = os.path.join(proc_root, "playlist.m3u8")
            if not os.path.isfile(master_playlist_path):
                utils.append_file(master_playlist_path, generate_master_playlist(result, proc_root))
        except Exception as e:
            # proc_root is unset if the failure happened before it was built,
            # which made the old handler raise NameError and abort the run.
            utils.append_file("error.txt", f"{proc_root or track_id}\t{e!r}\n", True)
            continue

        all_results[src] = {
            "master_playlist": master_playlist_path,
            "medias": result
        }

    print("\nPrcoessing Complete, writing results to output")

    if unknown_files:
        print(f"WARNING: {len(unknown_files)} unrecognised file(s) in quality "
              f"directories, see unknown_files.txt")
        utils.append_file("unknown_files.txt", "\n".join(unknown_files) + "\n", True)

    json_utils.json_dump(all_results, hls_finalized_struct_output_pth)


if __name__ == "__main__":
    main()
