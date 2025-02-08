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

SEGMENT_INDEX_EXTRACTOR = re.compile(r'segment_(\d+)\.m4s');

hls_worklist_output = utils.get_output_path(
    HlsTranscodePathDef, HlsTranscodePathDef.HLS_TRANSCODE_FILELIST_OUTPUT_NAME
)

hls_finalized_struct_output_pth = utils.get_output_path(
    HlsTranscodePathDef, HlsTranscodePathDef.HLS_FINALIZED_FILELIST_OUTPUT_NAME
)

hls_worklist = json_utils.json_load(hls_worklist_output)

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

all_results = {}
for index, (_, entry) in enumerate(hls_worklist.items()):
    print(f"[{index}/{len(hls_worklist)}] Processing: {_}", end='\r')
    try:
        src = entry[list(entry.keys())[0]]['src']
        src_root = os.path.dirname(src)
        src_filename_no_ext = os.path.splitext(os.path.basename(src))[0]
        proc_root = os.path.join(src_root, src_filename_no_ext)

        """
        Result sample: 
        { 
            "320k": {
                "playlist": "<Full FP Omitted>/hls/320k/playlist.m3u8",
                "segments": {
                    // note here that init.mp4 will always receive an index assignment of 1
                    "<Full FP Omitted>/hls/320k/init.mp4": -1,

                    // index assignment based of segment extractor regex 
                    "<Full FP Omitted>/hls/320k/segment_000.m4s": 0
                }
            }
        }
        """
        result = {}
        for quality, target_info in entry.items():
            result[quality] = {'segments': {}}
            dst_root = target_info['dst_root']
            for file in os.listdir(dst_root):
                fp = os.path.join(dst_root, file)
                if file == 'playlist.m3u8':
                    result[quality]['playlist'] = fp
                    continue

                if file == 'init.mp4':
                    result[quality]['segments'][fp] = -1
                    continue

                index = SEGMENT_INDEX_EXTRACTOR.search(file)
                if not index:
                    input(f"UnKNOWN FILE: {file}")

                index_value = int(index[1])
                result[quality]['segments'][fp] = index_value

        # Test if master playlist file already exists
        master_playlist_path = os.path.join(proc_root, "playlist.m3u8")
        if not os.path.isfile(master_playlist_path): 
            utils.append_file(master_playlist_path, generate_master_playlist(result, proc_root))
    except:
        utils.append_file("error.txt", proc_root + '\n', True)
        continue

    all_results[src] = {
        "master_playlist": master_playlist_path,
        "medias": result
    }

print("\nPrcoessing Complete, writing results to output")
json_utils.json_dump(all_results, hls_finalized_struct_output_pth)
