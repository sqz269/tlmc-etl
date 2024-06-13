import os
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

hls_worklist_output = utils.get_output_path(
    HlsTranscodePathDef, HlsTranscodePathDef.HLS_TRANSCODE_FILELIST_OUTPUT_NAME
)
hls_completed_output = get_output_path(
    HlsTranscodePathDef, HlsTranscodePathDef.HLS_TRANSCODE_COMPLETED_OUTPUT_NAME
)

def remove_completed(workslist: dict):
    complted = set()
    with utils.open_for_read(hls_completed_output) as f:
        for line in f:
            if line.strip():
                complted.add(line.strip())

    for key in list(workslist.keys()):
        if key in complted:
            src = worklist[key]["128k"]["src"]
            os.unlink(src)
            print(f"Removing file: {src}")
            del workslist[key]

worklist = json_utils.json_load(hls_worklist_output)
remove_completed(worklist)
