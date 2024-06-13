import os
from uuid import uuid4

import Processor.InfoCollector.Aggregator.output.path_definitions as AggregatorPathDef
import Postprocessor.HlsTranscode.output.path_definitions as HlsTranscodePathDef
import Postprocessor.HlsTranscode.hls_assignment as HlsAssignment
from Shared import json_utils, utils


hls_worklist_output = utils.get_output_path(
    HlsTranscodePathDef,
    HlsTranscodePathDef.HLS_TRANSCODE_FILELIST_EXPERIMENT_FS_SCAN_OUTPUT_NAME,
)


def generate_worklist_from_path(root):
    trakcs = {}
    for p, dir, files in os.walk(root):
        for file in files:
            if file.lower().endswith(".flac"):
                trakcs[str(uuid4())] = os.path.join(p, file)

    return HlsAssignment.generate_worklist(trakcs)


def main():
    root = input("Enter the root directory: ")
    print(f"Scanning {root} for FLAC files")
    print(f"Generating HLS transcode worklist")
    result = generate_worklist_from_path(root)

    print(f"Writing HLS transcode worklist to {hls_worklist_output}")
    json_utils.json_dump(result, hls_worklist_output)


if __name__ == "__main__":
    main()
