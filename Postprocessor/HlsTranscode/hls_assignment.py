import json
import os
from typing import Dict, List

import Processor.InfoCollector.Aggregator.output.path_definitions as AggregatorPathDef
import Postprocessor.HlsTranscode.output.path_definitions as HlsTranscodePathDef
import Preprocessor.AudioNormalizer.output.path_definitions as AudioNormalizerPathDef
from Preprocessor.AudioNormalizer.output.path_definitions import LOUDNESS_OUTPUT_NAME
from Shared import json_utils, utils

assigned_merged_output = utils.get_output_path(
    AggregatorPathDef, AggregatorPathDef.ID_ASSIGNED_PATH
)

hls_worklist_output = utils.get_output_path(
    HlsTranscodePathDef, HlsTranscodePathDef.HLS_TRANSCODE_FILELIST_OUTPUT_NAME
)


target_qualities = [
    "128k",
    "192k",
    "256k",
    "320k",
]

# Emit one contiguous media file per quality plus a byte-range playlist, instead
# of ~25 loose segment files.
#
# Why: hls_runner transcodes a flat worklist in parallel, so ext4 interleaved
# every track's segments with every other track's. Segments of one track ended up
# scattered TB apart, making playback N random seeks with no sequential run for
# readahead to exploit (measured on the USB HDD: 55 files/s, 18.3 ms each).
# One file per quality lets kernel readahead and ZFS zfetch prefetch a whole
# track for free, with no cache logic anywhere.
#
# Catalog-wide file count: ~17.7M -> ~1.5M.
#
# Note ffmpeg folds the fMP4 init segment into the same file under this flag and
# points #EXT-X-MAP at a byte range, so a quality directory holds exactly two
# files and there is no separate init.mp4. Consumers must handle both layouts
# while the v5 tree still contains per-segment output; they detect it from the
# playlist (`byterange is None` means legacy).
HLS_SINGLE_FILE = True

SEGMENT_NAME_SINGLE = "stream.m4s"
SEGMENT_NAME_MULTI = "segment_%03d.m4s"


def make_ffmpeg_hls_transcode_cmd(src, dst_root, bitrate, single_file=None, gain_db=None):
    if single_file is None:
        single_file = HLS_SINGLE_FILE

    src = utils.oslex_quote(src)
    media_name = SEGMENT_NAME_SINGLE if single_file else SEGMENT_NAME_MULTI
    seg_path = utils.oslex_quote(os.path.join(dst_root, media_name))
    dst_playlist = utils.oslex_quote(os.path.join(dst_root, "playlist.m3u8"))

    cmd = [
        "ffmpeg",
        "-i",
        src,
        "-vn",
    ]

    # Loudness normalization happens here rather than by rewriting the source.
    # This pass already decodes and re-encodes, so a static gain is free, and
    # the lossless library stays untouched and re-encodable. The gain is
    # clamped against true peak upstream (loudness_measure.static_gain_db), so
    # it cannot introduce clipping.
    #
    # Doing it at serve time instead is not an option: WebKit cannot route HLS
    # audio through Web Audio (webkit bug 231656) and iOS ignores writes to
    # HTMLMediaElement.volume, so a browser client has no way to apply gain to
    # an HLS stream.
    if gain_db is not None and abs(gain_db) >= 0.05:
        cmd += ["-af", f"volume={gain_db:.3f}dB"]

    cmd += [
        "-b:a",
        bitrate,
        "-f",
        "hls",
        "-hls_time",
        "10",
        "-hls_list_size",
        "0",
        "-hls_segment_filename",
        seg_path,
        "-hls_segment_type",
        "fmp4",
        "-c:a",
        "libfdk_aac",
    ]

    if single_file:
        # -hls_fmp4_init_filename is deliberately omitted here: with
        # single_file ffmpeg writes the init segment into the media file and
        # ignores the option, so passing it only implies a file that never
        # appears.
        cmd += ["-hls_flags", "single_file"]
    else:
        cmd += ["-hls_fmp4_init_filename", "init.mp4"]

    cmd += [dst_playlist, "-y", "-v", "quiet", "-stats"]
    return cmd


def make_ffmpeg_hls_ladder_cmd(src, dst_roots: Dict[str, str], single_file=None, gain_db=None):
    """
    The whole ladder in one ffmpeg process: decode once, feed four encoders.

    The worklist carries a separate command per rung, and running them meant
    decoding the source four times and reading it off disk four times. Measured
    on one track under load: 13.73 s as four sequential processes, 4.61 s as
    one -- 3.0x, with byte-identical output at every rung. Two effects
    compound: the redundant decodes disappear (0.59 s each of a 3.07 s rung),
    and ffmpeg runs the four encoders concurrently rather than end to end.

    It also cuts source reads 4x. That matters most on a node whose library is
    a network mount -- the SMB node was pulling 32.6 MB/s to sustain 0.45
    tracks/s of 28.9 MB files -- and on the local node it takes read pressure
    off a single spinning disk that every worker on every node shares.

    `-map 0:a:0` rather than `-vn`: it names the first audio stream outright,
    which both drops embedded cover art and avoids a second audio stream being
    mapped into all four outputs.
    """
    if single_file is None:
        single_file = HLS_SINGLE_FILE

    media_name = SEGMENT_NAME_SINGLE if single_file else SEGMENT_NAME_MULTI
    cmd = ["ffmpeg", "-i", utils.oslex_quote(src)]

    for bitrate, dst_root in dst_roots.items():
        cmd += ["-map", "0:a:0"]

        # Per output, not once globally: -af is an output option, so a single
        # copy would apply to the first rung only and the other three would
        # ship un-normalized.
        if gain_db is not None and abs(gain_db) >= 0.05:
            cmd += ["-af", f"volume={gain_db:.3f}dB"]

        cmd += [
            "-b:a",
            bitrate,
            "-c:a",
            "libfdk_aac",
            "-f",
            "hls",
            "-hls_time",
            "10",
            "-hls_list_size",
            "0",
            "-hls_segment_filename",
            utils.oslex_quote(os.path.join(dst_root, media_name)),
            "-hls_segment_type",
            "fmp4",
        ]

        if single_file:
            cmd += ["-hls_flags", "single_file"]
        else:
            cmd += ["-hls_fmp4_init_filename", "init.mp4"]

        cmd += [utils.oslex_quote(os.path.join(dst_root, "playlist.m3u8"))]

    cmd += ["-y", "-v", "quiet", "-stats"]
    return cmd


def generate_worklist_from_ids(entry: dict):
    all_tracks = {}
    for album_id, album_data in entry.items():
        discs = album_data["Discs"]
        for disc_root, disc_data in discs.items():
            disc_tracks = disc_data["Tracks"]
            for track in disc_tracks:
                track_id = track["TrackMetadata"]["TrackId"]
                track_path = track["TrackPath"]
                all_tracks[track_id] = track_path

    return generate_worklist(all_tracks)


def load_gain_map():
    """
    Per-track gain in dB, keyed by source path, from loudness_measure.py.

    Missing measurements are not fatal: a track with no entry transcodes at its
    original level. That keeps the stage runnable before the measurement pass
    finishes, at the cost of those tracks being un-normalized.
    """
    path = utils.get_output_path(AudioNormalizerPathDef, LOUDNESS_OUTPUT_NAME)
    if not os.path.isfile(path):
        print(f"No loudness measurements at {path}; transcoding without gain.")
        return {}

    gains = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                gains[rec["path"]] = float(rec["gain_db"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
    return gains


def hls_base_dirs(all_tracks: Dict[str, str]) -> Dict[str, str]:
    """
    Output directory per track, guaranteed distinct.

    Output normally goes to `<album>/<track stem>/hls/<rung>/`, dropping the
    extension. That collides whenever an album ships the same song twice in
    different formats -- 204 pairs here, `track.flac` beside `track.mp3`, both
    claiming `track/`. Whichever encoded last would win and two TrackIds would
    point at one playlist, so a track would play the other's audio.

    Colliding stems keep the extension, as `track [mp3]`. The extension cannot
    simply be left on: a directory named `track.flac` would clash with the audio
    file of that name sitting beside it. Only the affected tracks are renamed,
    so the layout is unchanged for the other 163,879.
    """
    by_stem: Dict[str, list] = {}
    for track_id, track_path in all_tracks.items():
        parent = os.path.dirname(track_path)
        stem = os.path.splitext(os.path.basename(track_path))[0]
        by_stem.setdefault(os.path.join(parent, stem), []).append(track_path)

    bases = {}
    for track_id, track_path in all_tracks.items():
        parent = os.path.dirname(track_path)
        stem, ext = os.path.splitext(os.path.basename(track_path))
        base = os.path.join(parent, stem)
        # Two ways the plain stem fails. Another track in the worklist claims
        # it, or a FILE of that name already sits on disk -- two albums carry an
        # extensionless copy beside the .flac, and mkdir on that path fails.
        # isfile, not exists: on a rerun the directory is our own output.
        if len(by_stem[base]) > 1 or os.path.isfile(base):
            base = os.path.join(parent, f"{stem} [{ext.lstrip('.').lower()}]")
        bases[track_id] = base
    return bases


def generate_worklist(all_tracks: Dict[str, str]):
    gains = load_gain_map()
    missing = 0
    bases = hls_base_dirs(all_tracks)

    work = {}
    for track_id, track_path in all_tracks.items():
        hls_target_base_dir = bases[track_id]

        gain_db = gains.get(track_path)
        if gain_db is None:
            missing += 1

        work_group = {}
        for quality in target_qualities:
            dst_root = os.path.join(hls_target_base_dir, "hls", quality)
            work_group[quality] = {
                "src": track_path,
                "dst_root": dst_root,
                "gain_db": gain_db,
                "cmd": " ".join(
                    make_ffmpeg_hls_transcode_cmd(
                        track_path, dst_root, quality, gain_db=gain_db
                    )
                ),
            }
        work[track_id] = work_group

    if missing:
        print(f"WARNING: {missing} of {len(all_tracks)} tracks have no loudness "
              f"measurement and will transcode at their original level.")

    return work


def main():
    print(f"Load id assignment from {assigned_merged_output}")
    id_assignment = json_utils.json_load(assigned_merged_output)

    print(f"Generate HLS transcode worklist")
    result = generate_worklist_from_ids(id_assignment)

    print(f"Writing HLS transcode worklist to {hls_worklist_output}")
    json_utils.json_dump(result, hls_worklist_output)


if __name__ == "__main__":
    main()
