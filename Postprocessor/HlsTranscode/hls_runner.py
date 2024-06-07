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

hls_journal_general_output = get_output_path(
    HlsTranscodePathDef, HlsTranscodePathDef.HLS_TRANSCODE_JOURNAL_GENERAL_OUTPUT_NAME
)
hls_journal_completed_output = get_output_path(
    HlsTranscodePathDef, HlsTranscodePathDef.HLS_TRANSCODE_JOURNAL_COMPLETED_OUTPUT_NAME
)
hls_journal_failed_output = get_output_path(
    HlsTranscodePathDef, HlsTranscodePathDef.HLS_TRANSCODE_JOURNAL_FAILED_OUTPUT_NAME
)

hls_completed_output = get_output_path(
    HlsTranscodePathDef, HlsTranscodePathDef.HLS_TRANSCODE_COMPLETED_OUTPUT_NAME
)


class HlsRunner:
    @staticmethod
    def remove_completed(workslist: dict):
        complted = set()
        with utils.open_for_read(hls_completed_output) as f:
            for line in f:
                if line.strip():
                    complted.add(line.strip())

        for key in list(workslist.keys()):
            if key in complted:
                del workslist[key]

    @staticmethod
    def process_one(
        journalWriter: JournalWriter,
        messageWriter: PrintMessageReporter,
        outputWriter: OutputWriter,
        track_id: str,
        work: dict,
    ):
        try:
            src_file = None
            for quality, work_details in work.items():
                src = work_details["src"]
                src_file = src
                cmd = work_details["cmd"]
                dst_root = work_details["dst_root"]
                messageWriter.report_state(f"[{quality}] Processing {src}")
                # Create destination directory
                os.makedirs(dst_root, exist_ok=True)

                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    shell=True,
                )

                stdout, stderr = proc.communicate()
                if proc.returncode != 0:
                    journalWriter.report_error(
                        f"Failed to process {track_id} with command [{cmd}]\n"
                    )
                    continue

                outputWriter.write(f"{track_id}\n")

            journalWriter.report_completed(f"Completed {track_id}\n")
            os.unlink(src_file)
            # Unlink completed

        except Exception as e:
            journalWriter.report_error(
                f"Failed to process {track_id} with command [{work['cmd']}]\n"
            )

    @staticmethod
    def start():
        journal_writer = JournalWriter(
            hls_journal_general_output,
            hls_journal_failed_output,
            hls_journal_completed_output,
        )

        output_writer = OutputWriter(hls_completed_output)

        processor = StatAutoMuxMultiProcessor(
            os.cpu_count(),
            journal_writer,
            output_writer,
        )

        print("Loading worklist")
        worklist = json_utils.json_load(hls_worklist_output)
        print("Loaded worklist ({} items)".format(len(worklist)))
        HlsRunner.remove_completed(worklist)
        print("Remaining worklist ({} items)".format(len(worklist)))

        for track_id, work in worklist.items():
            processor.submit_job(HlsRunner.process_one, track_id, work)

        processor.wait_print_complete()
        processor.reset_terminal()


def main():
    HlsRunner.start()


if __name__ == "__main__":
    main()
