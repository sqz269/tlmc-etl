import glob
import hashlib
import os
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
import Postprocessor.HlsTranscode.output.path_definitions as HlsTranscodePathDef
from Postprocessor.HlsTranscode.hls_assignment import make_ffmpeg_hls_ladder_cmd
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


# Publish finished tracks on a separate pool, so a worker starts its next encode
# instead of waiting for 23 MB to cross the network.
#
#   TLMC_PUBLISH_WORKERS=8
#
# Staging alone left each worker doing encode-then-publish end to end. Measured
# on the SMB node at 16-way concurrency: encoding to local disk sustains 1.25
# tracks/s and publishing sustains 1.35, but run in series they give
# 1/(1/1.25 + 1/1.35) = 0.65 -- and the node was observed at 0.61. Overlapping
# the two makes the slower of the pair the limit rather than their sum.
#
# Raising the worker count instead does not work: it scales encode and publish
# together and multiplies SMB streams. 64 workers measured *worse* (0.45 vs
# 0.61) and tripped 14 `Software caused connection abort` errors out of the soft
# CIFS mount.
#
# TLMC_PUBLISH_QUEUE bounds how many finished tracks may sit in scratch waiting
# to go. Hitting it blocks the encode worker, which is the point: scratch is
# capped at roughly (workers + queue) x 23 MB rather than growing without limit
# if the network falls behind.
PUBLISH_WORKERS = int(os.environ.get("TLMC_PUBLISH_WORKERS") or 0)
PUBLISH_QUEUE = int(os.environ.get("TLMC_PUBLISH_QUEUE") or 32)


class HlsRunner:
    # Set up in start() when TLMC_PUBLISH_WORKERS is on; None means publish
    # inline on the encoding worker, which is what a node with a local library
    # should do -- there is nothing to overlap.
    _publisher = None
    _publish_slots = None

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
    def publish_track(
        journalWriter: JournalWriter,
        outputWriter: OutputWriter,
        track_id: str,
        work: dict,
        stage_track_dir: str,
        src_file: str,
    ):
        """Move a finished track from scratch to its destination and record it.

        The completed marker is written here rather than when the encode
        finished: until the bytes are actually at the destination the track is
        not done, and recording it earlier would let a later run skip a track
        whose publish had failed.
        """
        try:
            for quality, work_details in work.items():
                HlsRunner.publish_one(
                    os.path.join(stage_track_dir, quality), work_details["dst_root"]
                )

            outputWriter.write(f"{track_id}\n")
            journalWriter.report_completed(f"Completed {track_id}\n")

            if DELETE_SOURCE_AFTER_TRANSCODE and src_file:
                os.unlink(src_file)
        except Exception as e:
            journalWriter.report_error(f"Failed to publish {track_id}: {e}\n")
        finally:
            shutil.rmtree(stage_track_dir, ignore_errors=True)

    @staticmethod
    def process_one(
        journalWriter: JournalWriter,
        messageWriter: PrintMessageReporter,
        outputWriter: OutputWriter,
        track_id: str,
        work: dict,
    ):
        stage_track_dir = os.path.join(STAGE_DIR, track_id) if STAGE_DIR else None
        # Set before the try: the finally reads it on every path, including a
        # failure raised before the hand-off point.
        handed_off = False
        try:
            # Every rung of a track shares a source and a gain -- they differ
            # only in bitrate and destination -- so the ladder is one command.
            first = next(iter(work.values()))
            src_file = src = first["src"]
            gain_db = first["gain_db"]

            # The per-rung command baked into the worklist is deliberately not
            # used. It is already shell-quoted and carries dst_root twice, so
            # redirecting it to scratch would mean re-implementing that quoting;
            # rebuilding from the same generator keeps one source of truth.
            dst_roots = {
                quality: (
                    os.path.join(stage_track_dir, quality)
                    if stage_track_dir
                    else details["dst_root"]
                )
                for quality, details in work.items()
            }

            messageWriter.report_state(f"Processing {src}")
            for dst_root in dst_roots.values():
                os.makedirs(dst_root, exist_ok=True)

            cmd = " ".join(make_ffmpeg_hls_ladder_cmd(src, dst_roots, gain_db=gain_db))
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                shell=True,
            )

            stdout, stderr = proc.communicate()

            # A track only counts as done when every rung rendered. The old code
            # reported "Completed" and unlinked the source even when all four
            # encodes failed, which destroyed the only lossless copy of a track
            # that had produced no playable output at all. One process makes
            # that all-or-nothing by construction: the exit code covers the
            # whole ladder, and a partial ladder was already treated as failure.
            if proc.returncode != 0:
                journalWriter.report_error(
                    f"Failed to process {track_id} with command [{cmd}]: "
                    f"{stderr.strip()[-500:]}\n"
                )
                return

            # Publishing happens only once every rung has rendered, so a track
            # that fails halfway leaves nothing behind at the destination.
            if not stage_track_dir:
                # Written once per track, not once per quality: `remove_completed`
                # reads this back into a set, so the extra lines were only bloat.
                outputWriter.write(f"{track_id}\n")
                journalWriter.report_completed(f"Completed {track_id}\n")
                if DELETE_SOURCE_AFTER_TRANSCODE and src_file:
                    os.unlink(src_file)
                return

            if HlsRunner._publisher is None:
                HlsRunner.publish_track(
                    journalWriter, outputWriter, track_id, work, stage_track_dir, src_file
                )
                return

            # Hand off and go straight to the next encode. acquire() blocks once
            # TLMC_PUBLISH_QUEUE tracks are already waiting, which is the
            # backpressure that keeps scratch bounded when the network is the
            # slower half.
            def publish_and_release(
                jw=journalWriter,
                ow=outputWriter,
                tid=track_id,
                wk=work,
                stage=stage_track_dir,
                src_f=src_file,
            ):
                try:
                    HlsRunner.publish_track(jw, ow, tid, wk, stage, src_f)
                finally:
                    HlsRunner._publish_slots.release()

            HlsRunner._publish_slots.acquire()
            try:
                HlsRunner._publisher.submit(publish_and_release)
            except Exception:
                # Nothing took ownership, so give the slot back and let the
                # finally below sweep scratch -- otherwise a rejected submit
                # would leak a permit and eventually wedge every encode worker.
                HlsRunner._publish_slots.release()
                raise
            handed_off = True

        except Exception as e:
            # `work` is {quality: {...}}, so the old `work['cmd']` raised
            # KeyError from inside the handler. Nothing calls .result() on these
            # futures, so that exception was swallowed and the failure vanished.
            journalWriter.report_error(f"Failed to process {track_id}: {e}\n")
        finally:
            # A failed track must not leave its part-encoded rungs behind. Once
            # handed off, ownership of the scratch directory passes to the
            # publisher -- deleting it here would race the copy that is reading
            # it, so the publisher sweeps it in its own finally instead.
            if stage_track_dir and not handed_off:
                shutil.rmtree(stage_track_dir, ignore_errors=True)

    @staticmethod
    def start():
        index, count = shard_config()

        if STAGE_DIR:
            os.makedirs(STAGE_DIR, exist_ok=True)
            print(f"Staging encodes in {STAGE_DIR}, publishing each track on completion")

            if PUBLISH_WORKERS:
                HlsRunner._publish_slots = threading.Semaphore(PUBLISH_QUEUE)
                HlsRunner._publisher = ThreadPoolExecutor(
                    max_workers=PUBLISH_WORKERS, thread_name_prefix="publish"
                )
                print(
                    f"Publishing asynchronously: {PUBLISH_WORKERS} workers, "
                    f"at most {PUBLISH_QUEUE} finished tracks held in scratch"
                )

        journal_writer = JournalWriter(
            shard_path(hls_journal_general_output, index, count),
            shard_path(hls_journal_failed_output, index, count),
            shard_path(hls_journal_completed_output, index, count),
        )

        output_writer = OutputWriter(shard_path(hls_completed_output, index, count))

        # One worker per core is right only when the library is local and the
        # cores are the constraint. The sources sit on a single 12 TB spinning
        # disk, and every worker on every node is an independent read stream
        # across it -- 20 local plus 32 remote drove read await to 156 ms and
        # held the disk to 44 MB/s, well under what it does sequentially. A node
        # that is not CPU-bound anyway (the SMB node ran at 454% of 3200%) buys
        # nothing from more workers and costs the other node seeks.
        workers = int(os.environ.get("TLMC_WORKERS") or os.cpu_count())
        processor = StatAutoMuxMultiProcessor(
            workers,
            journal_writer,
            output_writer,
        )
        print(f"Using {workers} workers")

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

        # The encode futures finishing does not mean the run is done: tracks
        # handed to the publisher are encoded but not yet at their destination,
        # and their completed markers are written by the publisher. Exiting here
        # would strand them -- output half-copied on the share and nothing in the
        # completed list to say so.
        if HlsRunner._publisher is not None:
            print("\nEncodes finished, draining publish queue...")
            HlsRunner._publisher.shutdown(wait=True)
            print("Publish queue drained.")

        processor.reset_terminal()


def main():
    HlsRunner.start()


if __name__ == "__main__":
    main()
