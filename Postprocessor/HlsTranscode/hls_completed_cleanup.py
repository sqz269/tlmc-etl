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
    """
    Deletes the source audio of every track that has finished transcoding.

    Irreversible: HLS output is lossy, so this destroys the only copy that can
    be re-encoded, and the one the embedding pipeline reads.
    """
    complted = set()
    with utils.open_for_read(hls_completed_output) as f:
        for line in f:
            if line.strip():
                complted.add(line.strip())

    removed = 0
    for key in list(workslist.keys()):
        if key in complted:
            # Was `worklist[key]` — the module-level global rather than the
            # parameter, so this only worked by accident when the caller
            # happened to pass that same dict.
            src = workslist[key]["128k"]["src"]
            os.unlink(src)
            print(f"Removing file: {src}")
            del workslist[key]
            removed += 1

    return removed


def main():
    worklist = json_utils.json_load(hls_worklist_output)

    print(f"Worklist entries: {len(worklist)}")
    print()
    print("This permanently deletes the source audio of every completed track.")
    print("HLS output is lossy and the embedding pipeline reads the source, so")
    print("this cannot be undone from the transcoded files.")
    if input("Type DELETE to continue: ").strip() != "DELETE":
        print("Aborted.")
        return

    removed = remove_completed(worklist)
    print(f"Removed {removed} source files")


# Guarded: without this, `import hls_completed_cleanup` deleted source audio as
# an import side effect.
if __name__ == "__main__":
    main()
