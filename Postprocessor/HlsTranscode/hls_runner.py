import glob
import hashlib
import os
import shutil
import subprocess
import Postprocessor.HlsTranscode.output.path_definitions as HlsTranscodePathDef
from Postprocessor.HlsTranscode.hls_assignment import make_ffmpeg_hls_transcode_cmd
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


# Encode to local scratch, then copy the finished track to its real destination.
# Set to a path on the node's OWN disk; leave unset for direct writes.
#
#   TLMC_STAGE_DIR=/stage
#
# Only worth setting when the destination is a network mount. Measured on the
# remote node writing to the library over SMB, same track, same load:
#
#   ladder straight to SMB          69.97 s
#   ladder to local disk             8.22 s
#   bulk copy of the result to SMB   1.15 s   -> 9.38 s total, 7.5x faster
#
# The win is not bandwidth -- the link was carrying 12 MB/s of a measured 83,
# the server's disk was 41% busy and its smbd used 3.6% CPU. It is round trips.
# ffmpeg rewrites playlist.m3u8 after every segment and appends each segment as
# it is produced, so one rung is hundreds of small dependent writes, each paying
# CIFS latency. The node's 32 workers sat in uninterruptible I/O wait (load 36,
# 454% CPU of 3200%) waiting on those. Staging turns the whole track into one
# 22 MB streaming copy, which the link does in about a second.
STAGE_DIR = os.environ.get("TLMC_STAGE_DIR") or None


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
    def publish_one(stage_root: str, dst_root: str):
        """Copy one finished quality directory from scratch to its destination.

        The media file is copied before playlist.m3u8 so an interrupted publish
        never leaves a playlist referring to bytes that are not there yet. A
        half-published track is not recorded as completed, so the next run
        re-encodes it and ffmpeg's -y overwrites whatever landed.
        """
        os.makedirs(dst_root, exist_ok=True)
        names = sorted(os.listdir(stage_root), key=lambda n: n == "playlist.m3u8")
        for name in names:
            shutil.copy2(os.path.join(stage_root, name), os.path.join(dst_root, name))

    @staticmethod
    def process_one(
        journalWriter: JournalWriter,
        messageWriter: PrintMessageReporter,
        outputWriter: OutputWriter,
        track_id: str,
        work: dict,
    ):
        stage_track_dir = os.path.join(STAGE_DIR, track_id) if STAGE_DIR else None
        try:
            src_file = None
            succeeded = 0
            for quality, work_details in work.items():
                src = work_details["src"]
                src_file = src
                cmd = work_details["cmd"]
                dst_root = work_details["dst_root"]

                # Staging re-derives the command rather than rewriting the one
                # baked into the worklist: that string is already shell-quoted
                # and carries dst_root in two places, so patching it textually
                # would have to re-implement the quoting to stay correct.
                if stage_track_dir:
                    dst_root = os.path.join(stage_track_dir, quality)
                    cmd = " ".join(
                        make_ffmpeg_hls_transcode_cmd(
                            src, dst_root, quality, gain_db=work_details["gain_db"]
                        )
                    )

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

            # Publish only once every rung has rendered, so a track that fails
            # halfway leaves nothing behind at the destination to clean up.
            if stage_track_dir:
                for quality, work_details in work.items():
                    HlsRunner.publish_one(
                        os.path.join(stage_track_dir, quality),
                        work_details["dst_root"],
                    )

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
        finally:
            # Unconditional: a failed track must not leave its part-encoded
            # rungs behind. 32 workers x 22 MB is trivial on disk, but a run of
            # 82k tracks that never swept scratch would accumulate the lot.
            if stage_track_dir:
                shutil.rmtree(stage_track_dir, ignore_errors=True)

    @staticmethod
    def start():
        index, count = shard_config()

        if STAGE_DIR:
            os.makedirs(STAGE_DIR, exist_ok=True)
            print(f"Staging encodes in {STAGE_DIR}, publishing each track on completion")

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
