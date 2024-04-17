import Processor.InfoCollector.AlbumInfo.output.path_definitions as AlbumInfoOutputPaths
import Postprocessor.HlsTranscode.output.path_definitions as HlsTranscodeOutputPaths
from Shared.utils import get_output_path
from Shared.json_utils import json_load, json_dump

import os
from pathlib import Path

album_info_ph3 = get_output_path(
    AlbumInfoOutputPaths, AlbumInfoOutputPaths.INFO_SCANNER_PHASE3_OUTPUT_NAME
)
filelist_output = get_output_path(
    HlsTranscodeOutputPaths, HlsTranscodeOutputPaths.HLS_TRANSCODE_FILELIST_OUTPUT_NAME
)


def main():
    album_info = json_load(album_info_ph3)
    filelist = {}
    for album in album_info:
        for disc_root, disc in album["Discs"].items():
            for track in disc["Tracks"]:
                track_path = track["TrackPath"]
                track_name = os.path.basename(track_path)
                track_parent = os.path.dirname(track_path)
                dst_dir = os.path.join(track_parent, Path(track_name).stem)
                dst_master_playlist = os.path.join(dst_dir, "playlist.m3u8")

                filelist[track_path] = {
                    "src": track_path,
                    "dst_dir": dst_dir,
                    "dst_master_playlist": dst_master_playlist,
                }

    print("Total tracks:", len(filelist))
    json_dump(filelist, filelist_output)


if __name__ == "__main__":
    main()
