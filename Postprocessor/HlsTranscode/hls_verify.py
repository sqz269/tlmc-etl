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

SEGMENT_INDEX_EXTRACTOR = re.compile(r'segment_(\d+)\.m4s')

hls_worklist_output = utils.get_output_path(
    HlsTranscodePathDef, HlsTranscodePathDef.HLS_TRANSCODE_FILELIST_OUTPUT_NAME
)

hls_worklist = 
