"""
Measures each track's loudness so a static gain can be applied at HLS transcode
time, instead of rewriting the source audio.

Why this replaces the two-pass normalizer:

  * `loudnorm`'s analysis pass runs at ~26x realtime because it simulates the
    whole normalization, limiter included. `ebur128` measures the same ITU-R
    BS.1770 quantities at ~156x. Measured on this corpus, that is ~8h instead of
    ~45h for 166,787 tracks.
  * The second pass rewrote every FLAC in place, lossily and irreversibly. The
    gain can instead be applied while transcoding to HLS, which already decodes
    and re-encodes every track, so it costs nothing extra and leaves the lossless
    library untouched.
  * A plain static gain of min(target_I - measured_I, target_TP - measured_TP)
    hit the target exactly on 10/10 sampled tracks. `loudnorm`'s extra machinery
    (dynamic fallback, `target_offset`) exists for broadcast material that must
    be pushed *up* against a peak ceiling; measured here, the true-peak clamp
    binds on 0% of tracks and only 1 in 1044 needs any boost at all.

Output is one JSON object per line:
    {"path": ..., "i": LUFS, "tp": dBTP, "lra": LU, "gain_db": float}

Resumable: paths already present in the output are skipped, so the run can be
interrupted freely. Results from an earlier `normalizer_pass1.py` run are picked
up too, since its measured_i/measured_tp are the same quantities.
"""

import json
import math
import os
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from Shared.utils import get_file_relative

# Streaming platforms converge on -14 LUFS (Spotify, YouTube, Tidal, Amazon);
# Apple uses -16. The pipeline previously targeted -24, which is the EBU R128
# *broadcast* figure and leaves a library noticeably quieter than anything else a
# listener plays. Changing this is cheap now that the gain lives in the transcode
# rather than in the files.
TARGET_I = -14.0
TARGET_TP = -1.0

# ebur128 is subprocess-bound and each ffmpeg pins one core, so throughput is
# roughly linear in workers up to the physical core count.
MAX_WORKERS = max(1, (os.cpu_count() or 4) - 2)

AUDIO_EXTENSIONS = (".flac", ".mp3", ".wav", ".wv", ".m4a")

output_root = get_file_relative(__file__, "output")
os.makedirs(output_root, exist_ok=True)
OUTPUT_PATH = os.path.join(output_root, "loudness.output.jsonl")
LEGACY_PASS1 = os.path.join(output_root, "normalize.firstpass_detect.output.json")

# ebur128 prints "-inf" for a digitally silent track's peak, and can print "nan"
# for a stream it could not gate. A digits-only pattern does not match those, so
# the summary parse failed and the track was counted as an ffmpeg failure -- 85
# tracks on this corpus, every one of them silence rather than a broken file.
_NUM = r"(-?(?:inf|nan|[\d.]+))"
_I = re.compile(r"I:\s*" + _NUM + r"\s*LUFS")
_TH = re.compile(r"Threshold:\s*" + _NUM + r"\s*LUFS")
_LRA = re.compile(r"LRA:\s*" + _NUM + r"\s*LU")
_PEAK = re.compile(r"Peak:\s*" + _NUM + r"\s*dBFS")

_lock = threading.Lock()


# ebur128 reports -70 LUFS for silence, and anything near it is either silent or
# below the measurement gate. Normalising such a track to the target means
# amplifying its noise floor by tens of dB.
SILENCE_FLOOR_LUFS = -60.0

# A boost this large means the source is quiet for a reason -- a field
# recording, a hidden track, an ambient interlude -- and forcing it to the target
# would misrepresent it and raise its noise floor. Measured on this corpus, only
# 0.15% of tracks want more than this.
MAX_BOOST_DB = 12.0


def static_gain_db(measured_i: float, measured_tp: float) -> float:
    """
    Gain that reaches the loudness target without pushing true peak past its own.

    Clamping against true peak is what makes this safe to apply blind: the gain
    can never introduce clipping, because the peak headroom bounds it.

    Two further limits, both from measuring this corpus:

      * A track at or below the silence floor is left alone. Three tracks
        measured exactly -70.0 LUFS, and the peak clamp does not help there
        because their peaks are equally tiny -- the naive formula asked for
        +56 dB.
      * Boost is capped. Attenuation is not, since turning a loud master down
        can never manufacture noise.
    """
    # -inf (silence) and nan (ungateable stream) both mean there is nothing to
    # normalise, and arithmetic on them would propagate into the gain.
    if not (math.isfinite(measured_i) and math.isfinite(measured_tp)):
        return 0.0
    if measured_i <= SILENCE_FLOOR_LUFS:
        return 0.0

    gain = min(TARGET_I - measured_i, TARGET_TP - measured_tp)
    return min(gain, MAX_BOOST_DB)


def measure(path: str):
    """Returns (i, tp, lra) via one ebur128 pass, or None if ffmpeg failed."""
    try:
        # Bytes, not text. ffmpeg echoes the input filename into its output, and
        # this library is full of Shift-JIS and GB18030 names, so decoding
        # stderr as UTF-8 raises UnicodeDecodeError on the undecodable byte --
        # which kills the worker and, through the executor, the whole run.
        proc = subprocess.run(
            [
                # -vn: a FLAC's embedded cover art is a video stream to ffmpeg,
                # and some in this library declare image/png while holding JPEG
                # bytes. Decoding that fails and takes the whole command down
                # with it, even though the audio is intact -- nine tracks on
                # this corpus. Nothing here needs the picture.
                "ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn",
                "-threads", "1", "-af", "ebur128=peak=true", "-f", "null", "-",
            ],
            capture_output=True,
            timeout=600,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    if proc.returncode != 0:
        return None

    # ebur128 prints its summary at the end of stderr. Only the numbers matter,
    # so any undecodable filename bytes can be replaced rather than raising.
    tail = proc.stderr[-2000:].decode("utf-8", errors="replace")
    i, lra, peak = _I.search(tail), _LRA.search(tail), _PEAK.search(tail)
    if not (i and lra and peak):
        return None
    return float(i.group(1)), float(peak.group(1)), float(lra.group(1))


def load_done():
    """Paths already measured, from this stage or an earlier normalizer_pass1 run."""
    done = {}

    if os.path.isfile(OUTPUT_PATH):
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    done[rec["path"]] = rec
                except (json.JSONDecodeError, KeyError):
                    continue

    if os.path.isfile(LEGACY_PASS1):
        carried = 0
        with open(LEGACY_PASS1, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    path = rec.get("path") or rec.get("file")
                    params = rec.get("normalization_params") or rec
                    i = float(params["measured_i"])
                    tp = float(params["measured_tp"])
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
                if path and path not in done:
                    done[path] = {
                        "path": path, "i": i, "tp": tp,
                        "lra": float(params.get("measured_lra", 0.0)),
                        "gain_db": round(static_gain_db(i, tp), 3),
                        "source": "loudnorm",
                    }
                    carried += 1
        if carried:
            print(f"Carried {carried} measurements over from normalizer_pass1")

    return done


def collect(root: str):
    files = []
    for path, _dirs, names in os.walk(root):
        for name in names:
            if name.lower().endswith(AUDIO_EXTENSIONS):
                files.append(os.path.join(path, name))
    return sorted(files)


def main():
    root = input("Enter TLMC root path: ").strip()
    if not os.path.isdir(root):
        print("Invalid path")
        sys.exit(1)

    done = load_done()
    if done:
        # Rewrite the output so carried-over records are persisted alongside new
        # ones, and the file is the single source of truth afterwards.
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            for rec in done.values():
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    files = collect(root)
    pending = [f for f in files if f not in done]
    print(f"Audio files      : {len(files)}")
    print(f"Already measured : {len(done)}")
    print(f"Pending          : {len(pending)}")
    print(f"Target           : {TARGET_I} LUFS, true peak {TARGET_TP} dBTP")
    print(f"Workers          : {MAX_WORKERS}")
    if not pending:
        print("Nothing to do.")
        return

    out = open(OUTPUT_PATH, "a", encoding="utf-8")
    state = {"n": 0, "failed": 0, "silent": 0}

    def work(path):
        # A single unmeasurable file must not take the run down with it: the
        # executor propagates a worker exception to the caller, which previously
        # ended the whole pass.
        try:
            result = measure(path)
        except Exception as e:  # noqa: BLE001 - deliberately broad
            print(f"\nmeasure failed for {path!r}: {e!r}")
            result = None
        with _lock:
            state["n"] += 1
            if result is None:
                state["failed"] += 1
            else:
                i, tp, lra = result
                # A silent track reads I = -70 LUFS with a peak of -inf, so the
                # peak is the non-finite one, not the loudness.
                if not (math.isfinite(i) and math.isfinite(tp)) or i <= SILENCE_FLOOR_LUFS:
                    state["silent"] += 1
                # json.dumps would write bare Infinity/NaN, which no strict JSON
                # reader accepts. Null says the same thing portably, and gain_db
                # is 0 either way.
                out.write(json.dumps({
                    "path": path,
                    "i": i if math.isfinite(i) else None,
                    "tp": tp if math.isfinite(tp) else None,
                    "lra": lra if math.isfinite(lra) else None,
                    "gain_db": round(static_gain_db(i, tp), 3),
                    "source": "ebur128",
                }, ensure_ascii=False) + "\n")
                out.flush()
            if state["n"] % 200 == 0:
                print(f"[{state['n']}/{len(pending)}] {state['failed']} failed", end="\r")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        list(executor.map(work, pending))

    out.close()
    print(f"\nMeasured {state['n'] - state['failed']} tracks, {state['failed']} failed")
    print(f"Of those, {state['silent']} are digitally silent (gain 0)")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
