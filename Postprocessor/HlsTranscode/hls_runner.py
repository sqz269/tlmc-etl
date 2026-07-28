import glob
import hashlib
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

# Delete each source FLAC once all of its qualities have transcoded. Off by
# default: HLS output is lossy, so the FLAC is the only copy that can be
# re-encoded later, and the MERT embedding pipeline reads the FLAC directly.
# Deleting here makes both regeneration and embedding generation impossible.
DELETE_SOURCE_AFTER_TRANSCODE = False


# Splitting the encode across machines. Set both on each node:
#
#   TLMC_SHARD_COUNT=3  TLMC_SHARD_INDEX=0   # first of three
#
# Every node reads the same worklist and keeps only the tracks its shard owns,
# so no node ever touches another's work and no coordination, locking or queue
# is needed. Ownership is derived from the track id, not from position in the
# worklist, so it is stable if the worklist is regenerated.
#
# blake2b rather than hash(): Python salts str hashing per process unless
# PYTHONHASHSEED is fixed, so hash() would assign the same track to different
# shards on different nodes -- some tracks encoded three times, others never.
def shard_config():
    count = int(os.environ.get("TLMC_SHARD_COUNT", "1"))
    index = int(os.environ.get("TLMC_SHARD_INDEX", "0"))
    if count < 1:
        raise ValueError(f"TLMC_SHARD_COUNT must be >= 1, got {count}")
    if not 0 <= index < count:
        raise ValueError(
            f"TLMC_SHARD_INDEX must be in [0, {count}), got {index}"
        )
    return index, count


def owns(track_id: str, index: int, count: int) -> bool:
    if count == 1:
        return True
    digest = hashlib.blake2b(track_id.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % count == index


def shard_path(path: str, index: int, count: int) -> str:
    """Per-shard journal/output path, so nodes on shared storage never interleave
    writes into one file."""
    if count == 1:
        return path
    root, ext = os.path.splitext(path)
    return f"{root}.shard{index}of{count}{ext}"


class HlsRunner:
    @staticmethod
    def remove_completed(workslist: dict):
        # Every shard's completed list is honoured, not just this node's. The
        # shard count can then change between runs -- or results be gathered
        # from other nodes -- without re-encoding what is already done.
        root, ext = os.path.splitext(hls_completed_output)
        complted = set()
        for path in sorted(glob.glob(f"{root}*{ext}")):
            with utils.open_for_read(path) as f:
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
            succeeded = 0
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

                succeeded += 1

            # A track only counts as done when every quality rendered. The old
            # code reported "Completed" and unlinked the source even when all
            # four encodes failed, which destroyed the only lossless copy of a
            # track that had produced no playable output at all.
            if succeeded != len(work):
                journalWriter.report_error(
                    f"Incomplete {track_id}: {succeeded}/{len(work)} qualities "
                    f"rendered, source kept for retry\n"
                )
                return

            # Written once per track, not once per quality: `remove_completed`
            # reads this back into a set, so the extra lines were only bloat.
            outputWriter.write(f"{track_id}\n")
            journalWriter.report_completed(f"Completed {track_id}\n")

            if DELETE_SOURCE_AFTER_TRANSCODE and src_file:
                os.unlink(src_file)

        except Exception as e:
            # `work` is {quality: {...}}, so the old `work['cmd']` raised
            # KeyError from inside the handler. Nothing calls .result() on these
            # futures, so that exception was swallowed and the failure vanished.
            journalWriter.report_error(f"Failed to process {track_id}: {e}\n")

    @staticmethod
    def start():
        index, count = shard_config()

        journal_writer = JournalWriter(
            shard_path(hls_journal_general_output, index, count),
            shard_path(hls_journal_failed_output, index, count),
            shard_path(hls_journal_completed_output, index, count),
        )

        output_writer = OutputWriter(shard_path(hls_completed_output, index, count))

        processor = StatAutoMuxMultiProcessor(
            os.cpu_count(),
            journal_writer,
            output_writer,
        )

        print("Loading worklist")
        worklist = json_utils.json_load(hls_worklist_output)
        print("Loaded worklist ({} items)".format(len(worklist)))

        if count > 1:
            before = len(worklist)
            worklist = {
                k: v for k, v in worklist.items() if owns(k, index, count)
            }
            print(
                f"Shard {index} of {count}: {len(worklist)} of {before} items "
                f"({100 * len(worklist) / before:.1f}%)"
            )

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
